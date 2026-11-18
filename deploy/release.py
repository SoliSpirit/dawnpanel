#!/usr/bin/python3
"""Root-owned narrow deployment wrapper; application commands run as dawnpanel."""
import fcntl
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import tarfile
import time

BASE = Path('/opt/dawnpanel')
SHA = re.compile(r'[0-9a-f]{40}')
MIN_FREE_BYTES = 1024**3
HEALTH = ['curl', '--fail', '--silent', '--max-time', '5', '-H', 'Host: dawnpanel.ir',
          '-H', 'X-Forwarded-Proto: https', 'http://127.0.0.1:18145/healthz/']


def release_pointer(base, name):
    link = base / name
    if not link.is_symlink():
        if link.exists():
            raise ValueError(f'{name} is not a release symlink')
        return None
    target = link.resolve(strict=True)
    releases = base / 'releases'
    if target.parent != releases or not SHA.fullmatch(target.name) or not target.is_dir():
        raise ValueError(f'{name} does not point to a DawnPanel release')
    return target


def write_pointer(base, name, target):
    tmp = base / (name + '.next')
    tmp.unlink(missing_ok=True)
    tmp.symlink_to(target)
    tmp.replace(base / name)


def remove_release_trees(paths, *, dry_run=False):
    # mountinfo also lists bind mounts, which Path.is_mount() can miss.
    mounted = [
        Path(re.sub(r'\\([0-7]{3})', lambda m: chr(int(m[1], 8)), line.split()[4]))
        for line in Path('/proc/self/mountinfo').read_text().splitlines()
    ]
    if any(mount.is_relative_to(path) for path in paths for mount in mounted):
        raise ValueError('A release contains a mount point; nothing pruned')
    for path in paths:
        if not dry_run:
            shutil.rmtree(path)
        print('Would prune' if dry_run else 'Pruned', path.name, flush=True)


def prune_releases(base, *, dry_run=False):
    """Only called under the deployment lock; never guess the rollback target."""
    releases = base / 'releases'
    if releases.is_symlink() or not releases.is_dir():
        raise ValueError('Invalid release root')
    current = release_pointer(base, 'current')
    previous = release_pointer(base, 'previous')
    if not current:
        raise ValueError('No valid current release; nothing pruned')
    candidates = sorted(p for p in releases.iterdir()
                        if SHA.fullmatch(p.name) and not p.is_symlink() and p.is_dir())
    if not previous and any(p != current for p in candidates):
        raise ValueError('No recorded rollback release; nothing pruned')
    stale = [p for p in candidates if p not in {current, previous}]
    remove_release_trees(stale, dry_run=dry_run)
    print('Kept releases:', current.name, previous.name if previous else '(no previous yet)', flush=True)
    return stale


def healthy():
    return subprocess.run(HEALTH, capture_output=True).returncode == 0


def deploy(sha):
    archive = Path('/var/lib/dawnpanel-deploy/incoming') / (sha + '.tar.gz')
    if not archive.is_file() or archive.is_symlink() or archive.stat().st_size > 100_000_000:
        raise SystemExit('Invalid archive')
    releases = BASE / 'releases'
    if releases.is_symlink() or not releases.is_dir():
        raise SystemExit('Invalid release root')
    previous = release_pointer(BASE, 'current')
    release = releases / sha
    if release.exists() or release.is_symlink():
        if previous == release and healthy():
            archive.unlink(missing_ok=True)
            print('Already deployed and healthy', sha)
            return
        raise SystemExit('Release directory exists but is not the healthy current release; inspect before retrying')
    if shutil.disk_usage(releases).free < MIN_FREE_BYTES:
        raise SystemExit('Deployment stopped: less than 1 GiB free on the release filesystem')

    release.mkdir(mode=0o755)
    switched = False
    try:
        with tarfile.open(archive) as tar:
            members = tar.getmembers()
            if sum(m.size for m in members) > 300_000_000:
                raise ValueError('Archive too large')
            for m in members:
                p = PurePosixPath(m.name)
                if (p.is_absolute() or '..' in p.parts or not (m.isfile() or m.isdir())
                        or any(x in p.parts for x in ['.git', 'private', '.env'])):
                    raise ValueError('Unsafe archive member')
                m.uid = m.gid = 0
                m.uname = m.gname = ''
                m.mode = 0o755 if m.isdir() else 0o644
            tar.extractall(release, members=members, filter='data')
        subprocess.run(['chown', '-R', 'dawnpanel:dawnpanel', str(release)], check=True)
        # Only schema/table privileges inside the dedicated database are available to the app.
        env = os.environ.copy()
        for line in Path('/etc/dawnpanel/web.env').read_text().splitlines():
            if line and not line.startswith('#'):
                k, v = line.split('=', 1)
                env[k] = v

        def run(args):
            subprocess.run(['runuser', '-u', 'dawnpanel', '--'] + args,
                           cwd=release, env=env, check=True)

        python = str(BASE / 'venv/bin/python')
        run([str(BASE / 'venv/bin/pip'), 'install', '--no-cache-dir', '-r', str(release / 'requirements.lock')])
        run([python, 'manage.py', 'check', '--deploy', '--fail-level', 'WARNING'])
        subprocess.run(['/usr/local/sbin/dawnpanel-backup'], check=True)
        run([python, 'manage.py', 'migrate', '--noinput'])
        run([python, 'manage.py', 'prepare_portal'])
        run([python, 'manage.py', 'collectstatic', '--noinput', '--verbosity', '0'])
        write_pointer(BASE, 'current', release)
        switched = True
        try:
            subprocess.run(['systemctl', 'restart', 'dawnpanel-web'], check=True)
            for _ in range(20):
                if healthy():
                    break
                time.sleep(1)
            else:
                raise RuntimeError('Health check failed')
            subprocess.run(['systemctl', 'try-restart', 'dawnpanel-bot'], check=True)
            if previous:
                write_pointer(BASE, 'previous', previous)
        except Exception:
            if previous:
                write_pointer(BASE, 'current', previous)
                web = subprocess.run(['systemctl', 'restart', 'dawnpanel-web'])
                bot = subprocess.run(['systemctl', 'try-restart', 'dawnpanel-bot'])
                if web.returncode == bot.returncode == 0 and healthy():
                    switched = False  # Safe to remove the failed candidate.
            raise
        print('Deployed', sha, flush=True)
        try:
            prune_releases(BASE)
        except (OSError, ValueError) as error:
            print(f'Deployed, but release cleanup failed: {error}', file=sys.stderr)
    finally:
        archive.unlink(missing_ok=True)
        if not switched and release.is_dir() and not release.is_symlink():
            try:
                remove_release_trees([release])
            except (OSError, ValueError) as error:
                print(f'Failed candidate could not be removed: {error}', file=sys.stderr)


def main(args):
    if os.geteuid() != 0:
        raise SystemExit('Run through configured sudo rule')
    cleanup = args in [['--prune-releases'], ['--prune-releases', '--dry-run']]
    if not cleanup and (len(args) != 1 or not SHA.fullmatch(args[0])):
        raise SystemExit('Expected commit SHA or --prune-releases [--dry-run]')
    with open('/run/lock/dawnpanel-deploy.lock', 'w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if cleanup:
            if not healthy():
                raise SystemExit('Current release is not healthy; nothing pruned')
            prune_releases(BASE, dry_run='--dry-run' in args)
        else:
            deploy(args[0])


if __name__ == '__main__':
    main(sys.argv[1:])
