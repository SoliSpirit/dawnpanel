#!/usr/bin/python3
"""Root-owned narrow deployment wrapper; application commands run as dawnpanel."""
import fcntl
import hashlib
import json
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
PROC = Path('/proc')
HEALTH = ['curl', '--fail', '--silent', '--max-time', '5', '-H', 'Host: dawnpanel.ir',
          '-H', 'X-Forwarded-Proto: https', 'http://127.0.0.1:18145/healthz/']
STATIC_PROBES = {
    'retail.css': ('text/css',), 'admin-panel.css': ('text/css',), 'admin-desk.css': ('text/css',),
    'workspace.js': ('application/javascript', 'text/javascript'),
    'fonts/Vazirmatn.woff2': ('font/woff2', 'application/font-woff2'),
}


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
    if not paths:
        return
    # mountinfo also lists bind mounts, which Path.is_mount() can miss.
    mounted = [
        Path(re.sub(r'\\([0-7]{3})', lambda m: chr(int(m[1], 8)), line.split()[4]))
        for line in Path('/proc/self/mountinfo').read_text().splitlines()
    ]
    if any(mount.is_relative_to(path) for path in paths for mount in mounted):
        raise ValueError('A release contains a mount point; nothing pruned')
    # In particular, an hourly job may still be running from the old release
    # after gunicorn and the bot have switched. Leave the whole batch for a retry.
    for pid in PROC.glob('[0-9]*'):
        try:
            handles = [pid / 'cwd', pid / 'exe', pid / 'root', *(pid / 'fd').iterdir()]
        except (FileNotFoundError, ProcessLookupError):
            continue
        for handle in handles:
            try:
                target = handle.readlink()
            except (FileNotFoundError, ProcessLookupError):
                continue
            if target.is_absolute() and any(target.is_relative_to(path) for path in paths):
                raise ValueError(f'Release in use by process {pid.name}; nothing pruned')
    for path in paths:
        if not dry_run:
            shutil.rmtree(path)
        print('Would prune' if dry_run else 'Pruned', path.name, flush=True)


def prune_releases(base, *, dry_run=False):
    """After a healthy switch, keep only current. Called under the deploy lock."""
    releases = base / 'releases'
    if releases.is_symlink() or not releases.is_dir():
        raise ValueError('Invalid release root')
    current = release_pointer(base, 'current')
    if not current:
        raise ValueError('No valid current release; nothing pruned')
    candidates = sorted(p for p in releases.iterdir()
                        if SHA.fullmatch(p.name) and not p.is_symlink() and p.is_dir())
    # Older wrappers left this symlink. Never traverse it to remove a target.
    legacy = base / 'previous'
    if legacy.exists() and not legacy.is_symlink():
        raise ValueError('Unexpected previous entry; nothing pruned')
    stale = [p for p in candidates if p != current]
    remove_release_trees(stale, dry_run=dry_run)
    if not dry_run and legacy.is_symlink():
        legacy.unlink()
    print('Active release:', current.name, flush=True)
    return stale


def web_ready():
    return subprocess.run(HEALTH, capture_output=True).returncode == 0


def static_ready(release):
    """Probe the hashed URLs a browser uses, served by Nginx, not by Gunicorn."""
    # The manifest is app-owned. Open it as the actual static reader, never root.
    asset = 'staticfiles.json'
    try:
        manifest = subprocess.run(
            ['runuser', '-u', 'www-data', '--', 'head', '-c', '1000001', str(release/'staticfiles'/asset)],
            check=True, capture_output=True, timeout=5).stdout
        if len(manifest) > 1_000_000:
            raise ValueError
        paths = json.loads(manifest)['paths']
        for asset, types in STATIC_PROBES.items():
            stem, suffix = asset.rsplit('.', 1)
            name = paths[asset]
            match = re.fullmatch(re.escape(stem) + r'\.([0-9a-f]{12})\.' + suffix, name)
            if not match:
                raise ValueError
            response = subprocess.run([
                'curl', '-q', '--silent', '--fail', '--max-time', '5', '--max-filesize', '2097152',
                '--noproxy', '*', '--resolve', 'dawnpanel.ir:443:127.0.0.1',
                '--write-out', r'\n%{http_code} %{content_type}', 'https://dawnpanel.ir/static/' + name,
            ], check=True, capture_output=True, timeout=7).stdout
            body, _, meta = response.rpartition(b'\n')
            status, _, mime = meta.decode('ascii').partition(' ')
            if (status != '200' or mime.partition(';')[0].strip().lower() not in types or not body
                    or hashlib.md5(body, usedforsecurity=False).hexdigest()[:12] != match[1]):
                raise ValueError
    except (OSError, subprocess.SubprocessError, KeyError, ValueError, TypeError):
        print(f'Public static health check failed: {asset}', file=sys.stderr, flush=True)
        return False
    return True


def healthy(release):
    return web_ready() and static_ready(release)


def create_release_dir(release):
    # mkdir's mode is filtered by the invoking shell's umask, including 0077.
    # Nginx needs search permission on this one parent to serve /static/.
    release.mkdir(mode=0o700)
    release.chmod(0o711)


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
        if previous == release and healthy(release):
            archive.unlink(missing_ok=True)
            print('Already deployed and healthy', sha)
            return
        raise SystemExit('Release directory exists but is not the healthy current release; inspect before retrying')
    if shutil.disk_usage(releases).free < MIN_FREE_BYTES:
        raise SystemExit('Deployment stopped: less than 1 GiB free on the release filesystem')

    create_release_dir(release)
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
                if web_ready():
                    break
                time.sleep(1)
            else:
                raise RuntimeError('Health check failed')
            if not static_ready(release):
                raise RuntimeError('Nginx is not serving this release’s assets')
            subprocess.run(['systemctl', 'try-restart', 'dawnpanel-bot'], check=True)
        except Exception:
            if previous:
                write_pointer(BASE, 'current', previous)
                web = subprocess.run(['systemctl', 'restart', 'dawnpanel-web'])
                bot = subprocess.run(['systemctl', 'try-restart', 'dawnpanel-bot'])
                if web.returncode == bot.returncode == 0 and healthy(previous):
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
            current = release_pointer(BASE, 'current')
            if not current or not healthy(current):
                raise SystemExit('Current release is not healthy; nothing pruned')
            prune_releases(BASE, dry_run='--dry-run' in args)
        else:
            deploy(args[0])


if __name__ == '__main__':
    main(sys.argv[1:])
