#!/usr/bin/python3
"""Root-owned narrow deployment wrapper; application commands run as dawnpanel."""
import sys,os,re,tarfile,pathlib,subprocess,fcntl,shutil,time
BASE=pathlib.Path('/opt/dawnpanel')
if os.geteuid()!=0: raise SystemExit('Run through configured sudo rule')
if len(sys.argv)!=2 or not re.fullmatch('[0-9a-f]{40}',sys.argv[1]): raise SystemExit('Expected commit SHA')
sha=sys.argv[1]
lock=open('/run/lock/dawnpanel-deploy.lock','w');fcntl.flock(lock,fcntl.LOCK_EX)
archive=pathlib.Path('/var/lib/dawnpanel-deploy/incoming')/(sha+'.tar.gz')
if not archive.is_file() or archive.is_symlink() or archive.stat().st_size>100_000_000: raise SystemExit('Invalid archive')
release=BASE/'releases'/sha
if release.exists(): raise SystemExit('This release already exists')
release.mkdir(mode=0o755)
try:
    with tarfile.open(archive) as tar:
        members=tar.getmembers()
        if sum(m.size for m in members)>300_000_000: raise ValueError('Archive too large')
        for m in members:
            p=pathlib.PurePosixPath(m.name)
            if p.is_absolute() or '..' in p.parts or not (m.isfile() or m.isdir()) or any(x in p.parts for x in ['.git','private','.env']): raise ValueError('Unsafe archive member')
            m.uid=0;m.gid=0;m.uname='';m.gname='';m.mode=0o755 if m.isdir() else 0o644
        tar.extractall(release,members=members,filter='data')
    subprocess.run(['chown','-R','dawnpanel:dawnpanel',str(release)],check=True)
    # Only schema/table privileges inside the dedicated database are available to the app.
    env=os.environ.copy()
    for line in pathlib.Path('/etc/dawnpanel/web.env').read_text().splitlines():
        if line and not line.startswith('#'): k,v=line.split('=',1);env[k]=v
    def run(args): subprocess.run(['runuser','-u','dawnpanel','--']+args,cwd=release,env=env,check=True)
    run([str(BASE/'venv/bin/pip'),'install','-r',str(release/'requirements.lock')])
    run([str(BASE/'venv/bin/python'),'manage.py','check','--deploy','--fail-level','WARNING'])
    run([str(BASE/'venv/bin/python'),'manage.py','migrate','--noinput'])
    run([str(BASE/'venv/bin/python'),'manage.py','prepare_portal'])
    run([str(BASE/'venv/bin/python'),'manage.py','collectstatic','--noinput','--verbosity','0'])
    previous=(BASE/'current').resolve() if (BASE/'current').exists() else None
    tmp=BASE/'next';tmp.unlink(missing_ok=True);tmp.symlink_to(release);tmp.replace(BASE/'current')
    try:
        subprocess.run(['systemctl','restart','dawnpanel-web'],check=True)
        for i in range(20):
            check=subprocess.run(['curl','--fail','--silent','-H','Host: dawnpanel.ir','-H','X-Forwarded-Proto: https','http://127.0.0.1:18145/healthz/'],capture_output=True)
            if check.returncode==0: break
            time.sleep(1)
        else: raise RuntimeError('Health check failed')
        subprocess.run(['systemctl','try-restart','dawnpanel-bot'],check=True)
        print('Deployed',sha)
    except Exception:
        if previous:
            tmp=BASE/'next';tmp.unlink(missing_ok=True);tmp.symlink_to(previous);tmp.replace(BASE/'current')
            subprocess.run(['systemctl','restart','dawnpanel-web'])
            subprocess.run(['systemctl','try-restart','dawnpanel-bot'])
        raise
finally:
    archive.unlink(missing_ok=True)
