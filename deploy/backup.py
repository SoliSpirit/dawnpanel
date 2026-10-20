#!/usr/bin/python3
import os,json,pathlib,subprocess,gzip,datetime
config=json.loads(pathlib.Path('/etc/dawnpanel/config.json').read_text())['database']
base=pathlib.Path('/var/backups/dawnpanel');base.mkdir(mode=0o700,exist_ok=True);base.chmod(0o700)
name='database-'+datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')+'.sql.gz'
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
