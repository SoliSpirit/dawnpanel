#!/usr/bin/python3
import os,json,pathlib,subprocess,gzip,datetime
private_config=json.loads(pathlib.Path('/etc/dawnpanel/config.json').read_text())
config=private_config['database']
base=pathlib.Path('/var/backups/dawnpanel');base.mkdir(mode=0o700,exist_ok=True);base.chmod(0o700)
name='database-'+datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')+'.sql.gz'
if private_config.get('profile_encryption_key'):
    key_target=base/name.replace('.sql.gz','.profile-key')
    descriptor=os.open(key_target,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(descriptor,'w') as key_file:key_file.write(private_config['profile_encryption_key'])
target=base/name;temporary=base/(name+'.partial')
env={**os.environ,'MYSQL_PWD':config['password']}
try:
    with gzip.open(temporary,'wb') as out:
        process=subprocess.Popen(['mariadb-dump','--single-transaction','--triggers','--hex-blob','-h',config['host'],'-u',config['user'],config['database']],env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        while chunk:=process.stdout.read(1024*1024):out.write(chunk)
        error=process.stderr.read();code=process.wait()
        if code:raise RuntimeError('Database backup failed; see database permissions')
    temporary.chmod(0o600);temporary.replace(target)
    print('Backup complete:',target.name)
finally:
    temporary.unlink(missing_ok=True)

# Product media lives outside release directories and must survive deployments/restores.
import tarfile
media=pathlib.Path('/var/lib/dawnpanel/media')
if media.is_dir():
    media_target=base/name.replace('.sql.gz','.media.tar.gz')
    media_temporary=pathlib.Path(str(media_target)+'.partial')
    def safe_member(info):
        return info if (info.isfile() or info.isdir()) and not info.issym() and not info.islnk() else None
    try:
        with tarfile.open(media_temporary,'w:gz') as archive:
            archive.add(media,arcname='media',recursive=True,filter=safe_member)
        media_temporary.chmod(0o600);media_temporary.replace(media_target)
        print('Media backup complete:',media_target.name)
    finally:
        media_temporary.unlink(missing_ok=True)
