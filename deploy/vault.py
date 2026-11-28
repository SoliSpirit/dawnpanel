#!/usr/bin/python3
"""DawnPanel disaster recovery. Installed as a root-owned file, outside releases."""
import argparse
from contextlib import contextmanager
from datetime import datetime,timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path,PurePosixPath
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time

import requests
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey,Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import Encoding,PublicFormat

VAULT=Path('/var/backups/dawnpanel/vault')
KEYS=Path('/etc/dawnpanel-vault')
CONFIG=Path('/etc/dawnpanel/config.json')
APP=Path('/opt/dawnpanel')
PART=18*1024**2  # both upload AND cloud Bot API download fit
STAMP=re.compile(r'\d{8}T\d{12}Z')
SECTIONS={'database':'دیتابیس','media':'رسانه‌ها','application':'سایت و ربات','settings':'تنظیمات سرور','logs':'لاگ‌ها'}
CATALOG='فهرست بازیابی'


def check(ok,msg):
    if not ok:raise ValueError(msg)


def canonical(obj):
    return json.dumps(obj,sort_keys=True,separators=(',',':')).encode()


def save(path,obj):
    tmp=path.with_name('.'+path.name+'.new')
    with tmp.open('wb') as f:f.write(canonical(obj));f.flush();os.fsync(f.fileno())
    tmp.replace(path)


def read(path,default=None):
    if default is not None and not path.exists():return default
    check(path.stat().st_size<=8*1024**2,'Metadata too large')
    return json.loads(path.read_bytes())


@contextmanager
def lock(path,mode=fcntl.LOCK_EX):
    with open(path,'a+b') as f:
        fcntl.flock(f.fileno(),mode)
        yield


def init_keys():
    KEYS.mkdir(mode=0o700,exist_ok=True)
    VAULT.mkdir(mode=0o700,parents=True,exist_ok=True)
    ident=KEYS/'identity.agekey'
    if not ident.exists():
        subprocess.run(['age-keygen','-o',str(ident)],stderr=subprocess.DEVNULL,check=True)
    private=KEYS/'signing.key'
    if not private.exists():
        with private.open('xb') as f:f.write(os.urandom(32))
    raw=Ed25519PrivateKey.from_private_bytes(private.read_bytes()).public_key().public_bytes(Encoding.Raw,PublicFormat.Raw)
    pub=KEYS/'verify.pub'
    if pub.exists():check(pub.read_bytes()==raw,'Signing key mismatch')
    else:pub.write_bytes(raw)
    dest=KEYS/'recipient'
    result=subprocess.check_output(['age-keygen','-y',str(ident)]).strip()
    if dest.exists():check(dest.read_bytes().strip()==result,'Encryption key mismatch')
    else:dest.write_bytes(result+b'\n')
    print('Recovery keys ready. Make an offline copy of identity.agekey and verify.pub.')


def files_for_settings():
    files=[CONFIG,CONFIG.with_name('web.env')]
    files += [p for p in [CONFIG.with_name('chat-mail.env'),KEYS/'destination.json',KEYS/'recipient',KEYS/'verify.pub',
        Path('/usr/local/sbin/dawnpanel-deploy'),Path('/usr/local/sbin/dawnpanel-backup'),Path('/usr/local/sbin/dawnpanel-vault')] if p.is_file()]
    files += sorted(p for p in Path('/etc/systemd/system').glob('dawnpanel-*') if p.is_file() and p.suffix in ('.timer','.service'))
    nginx=Path('/etc/nginx/sites-enabled/dawnpanel.conf')
    if nginx.is_file():files.append(nginx.resolve())
    return files


def archive_section(section,output,tmp,release,db):
    if section=='database':
        with (tmp/'database.sql').open('xb') as f:
            subprocess.run(['mariadb-dump','--single-transaction','--quick','--hex-blob','--triggers','--events','--routines',
                '--default-character-set=utf8mb4','-h',db['host'],'-P',str(db.get('port',3306)),'-u',db['user'],db['database']],
                env={**os.environ,'MYSQL_PWD':db['password']},stdout=f,check=True)
        args=['tar','czf','-','-C',str(tmp),'database.sql']
    elif section=='settings':
        args=['tar','czf','-','-C','/',*[str(p.relative_to('/')) for p in files_for_settings()]]
    else:
        root,name=(release.parent,release.name) if section=='application' else (Path('/var/lib/dawnpanel'),section)
        args=['runuser','-u','dawnpanel','--','tar','czf','-','--one-file-system','--hard-dereference',
            '--exclude=__pycache__','--exclude=*.pyc','--exclude=staticfiles','--exclude=.git','--exclude=local.sqlite3','-C',str(root),name]
    # Only tar runs as the app user for app-controlled trees; it cannot read the vault or root's keys.
    with subprocess.Popen(args,stdout=subprocess.PIPE) as tar:
        try:
            subprocess.run(['age','-R',str(KEYS/'recipient'),'-o',str(output)],stdin=tar.stdout,check=True)
        finally:tar.stdout.close()
        check(tar.wait()==0,'Could not archive '+section)
    if section=='database':(tmp/'database.sql').unlink()


def snapshot():
    VAULT.mkdir(mode=0o700,parents=True,exist_ok=True)
    with lock(VAULT/'.snapshot.lock'),lock('/run/lock/dawnpanel-deploy.lock',fcntl.LOCK_SH):
        release=(APP/'current').resolve(strict=True)
        check(release.parent==APP/'releases' and re.fullmatch('[0-9a-f]{40}',release.name),'Invalid active release')
        check(shutil.disk_usage(VAULT).free>1024**3,'Less than 1 GiB free')
        now=datetime.now(timezone.utc);stamp=now.strftime('%Y%m%dT%H%M%S%fZ')
        data={'version':1,'id':stamp,'release':release.name,'sections':{}}
        with tempfile.TemporaryDirectory(prefix='.building-',dir=VAULT) as temp:
            work=Path(temp);bundle=work/'bundle';bundle.mkdir()
            for section in SECTIONS:
                encrypted=work/'payload.age';archive_section(section,encrypted,work,release,read(CONFIG)['database'])
                chunks=[]
                with encrypted.open('rb') as f:
                    while block:=f.read(PART):
                        filename=f'{stamp}-{section}-{len(chunks)+1:04d}.age'
                        (bundle/filename).write_bytes(block)
                        chunks.append({'name':filename,'size':len(block),'sha256':hashlib.sha256(block).hexdigest()})
                encrypted.unlink();data['sections'][section]=chunks
            signer=Ed25519PrivateKey.from_private_bytes((KEYS/'signing.key').read_bytes())
            save(bundle/'index.json',{'manifest':data,'signature':signer.sign(canonical(data)).hex()})
            bundle.rename(VAULT/stamp)
        print('Encrypted snapshot:',stamp)
        # Keep two weeks on disk; never remove pending transfers.
        for old in sets()[:-14]:
            if read(old/'delivery.json',{}).get('complete'):shutil.rmtree(old)


def sets():
    return sorted(p for p in VAULT.iterdir() if STAMP.fullmatch(p.name) and p.is_dir() and not p.is_symlink()) if VAULT.exists() else []


def verified(index):
    wrapper=read(index);manifest=wrapper['manifest']
    Ed25519PublicKey.from_public_bytes((KEYS/'verify.pub').read_bytes()).verify(bytes.fromhex(wrapper['signature']),canonical(manifest))
    stamp=manifest['id']
    check(STAMP.fullmatch(stamp) and manifest['version']==1 and set(manifest['sections'])==set(SECTIONS),'Incorrect snapshot index')
    for section,parts in manifest['sections'].items():
        check(0<len(parts)<=9999,'Invalid section')
        for i,item in enumerate(parts,1):
            check(item['name']==f'{stamp}-{section}-{i:04d}.age' and 0<item['size']<=PART and re.fullmatch('[0-9a-f]{64}',item['sha256']),'Invalid part')
    return manifest


def remote_index(index,group,sent):
    wrapper=read(index)
    locator={'id':wrapper['manifest']['id'],'chat_id':group,'files':{k:v['file_id'] for k,v in sent.items()}}
    signer=Ed25519PrivateKey.from_private_bytes((KEYS/'signing.key').read_bytes())
    return canonical({**wrapper,'locator':locator,'locator_signature':signer.sign(canonical(locator)).hex()})


def part_bytes(folder,item):
    f=folder/item['name'];check(not f.is_symlink() and f.stat().st_size==item['size'],'Part missing or incomplete')
    data=f.read_bytes();check(hashlib.sha256(data).hexdigest()==item['sha256'],'Part hash mismatch')
    return data


class RemoteError(Exception):
    def __init__(self,code,reason='telegram',wait=0):
        self.code,self.reason,self.wait=code,reason,wait
        super().__init__(f'{reason} ({code}); transfer remains queued')


class Bot:
    def __init__(self):
        cfg=read(CONFIG)['telegram'];self.admins=[int(i) for i in cfg['admin_ids'] if str(i).isdigit()]
        self.http=requests.Session();self.http.trust_env=False
        self.url='https://api.telegram.org/bot'+cfg['token']+'/'

    def call(self,method,params=None,files=None):
        try:
            r=self.http.post(self.url+method,data=params or {},files=files,timeout=(5,70),allow_redirects=False)
            d=r.json()
        except (requests.RequestException,ValueError):raise RemoteError(0,'network') from None
        if not d.get('ok') or r.status_code!=200:
            why=str(d.get('description','')).lower();code=r.status_code
            reason='topic_missing' if code==400 and ('thread not found' in why or 'topic_closed' in why) else 'telegram'
            wait=d.get('parameters',{}).get('retry_after',0)
            raise RemoteError(code,reason,min(86400,max(0,int(wait))) if isinstance(wait,int) else 0)
        return d['result']

    def validate_group(self,gid):
        check(re.fullmatch(r'-100[0-9]{5,13}',str(gid)),'Expected a numeric private forum supergroup ID')
        chat=self.call('getChat',{'chat_id':gid})
        check(chat.get('id')==gid and chat.get('type')=='supergroup' and chat.get('is_forum') and not chat.get('username') and not chat.get('active_usernames') and not chat.get('linked_chat_id'),'Expected a private, unlinked forum group')
        me=self.call('getMe')
        rights=self.call('getChatMember',{'chat_id':gid,'user_id':me['id']})
        check(rights.get('status')=='administrator' and rights.get('can_manage_topics'),'Bot needs Manage Topics')
        for uid in self.admins:
            if self.call('getChatMember',{'chat_id':gid,'user_id':uid}).get('status') in ('creator','administrator'):return
        raise ValueError('A configured private bot admin must administer this group')


def upload(*,limit=18,bot=None):
    dest=KEYS/'destination.json'
    if not dest.exists():return
    with lock(VAULT/'.upload.lock'):
        retry=read(VAULT/'.retry.json',{})
        if time.time()<retry.get('after',0):return
        pending=[p for p in sets() if not read(p/'delivery.json',{}).get('complete')]
        if not pending:return
        bot=bot or Bot();gid=read(dest)['chat_id']
        try:
            bot.validate_group(gid)
            topicfile=VAULT/f'.topics-{gid}.json';topics=read(topicfile,{})
            for folder in pending:
                m=verified(folder/'index.json');state=read(folder/'delivery.json',{'chat_id':gid,'sent':{}})
                check(state['chat_id']==gid,'Destination changed during a partial delivery')
                entries=[(SECTIONS[s],p['name'],p) for s,parts in m['sections'].items() for p in parts]
                entries.append((CATALOG,m['id']+'-index.json',None))
                for title,name,item in entries:
                    if name in state['sent']:continue
                    if title not in topics:
                        topics[title]=bot.call('createForumTopic',{'chat_id':gid,'name':title})['message_thread_id'];save(topicfile,topics)
                    raw=part_bytes(folder,item) if item else remote_index(folder/'index.json',gid,state['sent'])
                    try:
                        sent=bot.call('sendDocument',{'chat_id':gid,'message_thread_id':topics[title],
                            'caption':f'دان‌پنل · {title}\n{m["id"]}\n{name}'},
                            files={'document':(name,raw,'application/octet-stream')})
                    except RemoteError as exc:
                        if exc.reason=='topic_missing':topics.pop(title,None);save(topicfile,topics)
                        raise
                    check(sent.get('chat',{}).get('id')==gid and sent.get('message_thread_id')==topics[title] and sent.get('document',{}).get('file_id'),'Unexpected delivery target')
                    state['sent'][name]={'message_id':sent['message_id'],'file_id':sent['document']['file_id']}
                    save(folder/'delivery.json',state);limit-=1
                    if not limit:return
                state['complete']=True;save(folder/'delivery.json',state)
            save(VAULT/'.retry.json',{})
        except RemoteError as exc:
            n=retry.get('attempts',0)+1
            save(VAULT/'.retry.json',{'attempts':n,'after':time.time()+max(exc.wait,min(3600,30*2**min(n,7))),'code':exc.code})
            raise


def download(index,dest):
    m=verified(index);wrapper=read(index);loc=wrapper['locator']
    Ed25519PublicKey.from_public_bytes((KEYS/'verify.pub').read_bytes()).verify(bytes.fromhex(wrapper['locator_signature']),canonical(loc))
    check(loc['id']==m['id'],'Different snapshot')
    bot=Bot()
    dest.mkdir(mode=0o700,exist_ok=True)
    check(not dest.is_symlink() and dest.stat().st_uid==0 and dest.stat().st_mode&0o077==0,'Choose a root-private recovery directory')
    for it in (part for parts in m['sections'].values() for part in parts):
        if (dest/it['name']).exists():part_bytes(dest,it);continue
        ref=bot.call('getFile',{'file_id':loc['files'][it['name']]})
        key=ref.get('file_path','')
        check(re.fullmatch(r'documents/[A-Za-z0-9_.-]+',key) and ref.get('file_size')==it['size'],'Unexpected file path/size')
        url=bot.url.replace('https://api.telegram.org/bot','https://api.telegram.org/file/bot')+key
        with tempfile.NamedTemporaryFile(dir=dest) as tmp:
            try:
                with bot.http.get(url,stream=True,timeout=(5,50),allow_redirects=False) as response:
                    check(response.status_code==200,'Could not download Telegram file')
                    for b in response.iter_content(65536):
                        tmp.write(b);check(tmp.tell()<=it['size'],'Part too large')
            except requests.RequestException:raise RemoteError(0,'download interrupted') from None
            tmp.flush();tmp.seek(0);check(hashlib.file_digest(tmp,'sha256').hexdigest()==it['sha256'] and Path(tmp.name).stat().st_size==it['size'],'Part hash mismatch')
            os.link(tmp.name,dest/it['name'])
    save(dest/'index.json',wrapper);print('Downloaded signed snapshot:',m['id'])


def restore(index,dest,dbname=None,socket=None):
    m=verified(index);check(not dest.exists() and dest.parent.is_dir(),'Choose a new recovery directory')
    if dbname:check(re.fullmatch(r'dawnrestore_[a-z0-9_]{1,48}',dbname),'Use a NEW database named dawnrestore_...')
    with tempfile.TemporaryDirectory(prefix='.restore-',dir=dest.parent) as temp:
        work=Path(temp);out=work/'verified';out.mkdir()
        for s,parts in m['sections'].items():
            cipher=work/'part.age';archive=work/'archive.tar.gz'
            with cipher.open('wb') as f:
                for it in parts:f.write(part_bytes(index.parent,it))
            subprocess.run(['age','--decrypt','-i',str(KEYS/'identity.agekey'),'-o',str(archive),str(cipher)],check=True)
            target=out/s;target.mkdir()
            with tarfile.open(archive,'r:gz') as tar:
                for member in tar:
                    p=PurePosixPath(member.name)
                    check(not p.is_absolute() and '..' not in p.parts and (member.isfile() or member.isdir()),'Unexpected archive entry')
                    tar.extract(member,target,filter='data')
            archive.unlink();cipher.unlink()
        if dbname:
            args=['mariadb','--no-defaults','--protocol=SOCKET',*(['--socket='+socket] if socket else [])]
            subprocess.run([*args,'-e',f'CREATE DATABASE `{dbname}` CHARACTER SET utf8mb4'],check=True)
            with (out/'database/database.sql').open('rb') as sql:subprocess.run([*args,dbname],stdin=sql,check=True)
        out.rename(dest)
    print('Verified recovery:',dest,dbname or '(files only)')


def main():
    os.umask(0o077)
    check(os.geteuid()==0,'Root access required')
    p=argparse.ArgumentParser();sub=p.add_subparsers(dest='cmd',required=True)
    for name in ('init','snapshot','send','status'):sub.add_parser(name)
    g=sub.add_parser('connect');g.add_argument('chat_id',type=int)
    g=sub.add_parser('download');g.add_argument('index',type=Path);g.add_argument('directory',type=Path)
    r=sub.add_parser('restore');r.add_argument('index',type=Path);r.add_argument('new_directory',type=Path)
    r.add_argument('--new-db');r.add_argument('--socket')
    a=p.parse_args()
    if a.cmd=='init':init_keys()
    elif a.cmd=='snapshot':snapshot()
    elif a.cmd=='send':upload()
    elif a.cmd=='status':
        rows=sets();print('Snapshots:',len(rows),'latest:',rows[-1].name if rows else 'none',
            'queued:',sum(not read(row/'delivery.json',{}).get('complete') for row in rows),'destination configured:',(KEYS/'destination.json').exists())
    elif a.cmd=='connect':
        Bot().validate_group(a.chat_id);save(KEYS/'destination.json',{'chat_id':a.chat_id});print('Private backup forum configured.')
    elif a.cmd=='download':download(a.index,a.directory)
    else:restore(a.index,a.new_directory,a.new_db,a.socket)


if __name__=='__main__':
    try:main()
    except Exception as exc:
        # Never expose API token URLs, config values, or decrypted archive contents.
        print(f'Vault: {exc}' if type(exc) in (RemoteError,ValueError) else 'Vault failed: '+type(exc).__name__,file=sys.stderr);sys.exit(1)
