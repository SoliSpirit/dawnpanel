import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from deploy.release import STATIC_PROBES, create_release_dir, healthy, prune_releases, remove_release_trees, write_pointer


class ReleaseRetentionTests(TestCase):
    def setUp(self):
        scratch = TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.base = Path(scratch.name)
        self.releases = self.base / 'releases'
        self.releases.mkdir()
        self.proc = self.base / 'proc'
        self.proc.mkdir()
        self.enterContext(patch('deploy.release.PROC', self.proc))
        self.older, self.previous, self.current = [self.release(char) for char in 'abc']
        write_pointer(self.base, 'current', self.current)
        write_pointer(self.base, 'previous', self.previous)

    def release(self, char):
        path = self.releases / (char * 40)
        path.mkdir()
        (path / 'version').write_text(char)
        return path

    def test_retains_exact_current_only_and_ignores_unmanaged_entries(self):
        failed = self.release('d')
        outside = self.base / 'backups'
        outside.mkdir()
        marker = outside / 'database'
        marker.touch()
        (failed / 'backup').symlink_to(outside)
        (self.releases / ('e' * 40)).symlink_to(outside)
        unknown = self.releases / 'manual-notes'
        unknown.mkdir()
        self.assertEqual(prune_releases(self.base), [self.older, self.previous, failed])
        for path in [self.current, marker, unknown]:
            self.assertTrue(path.exists())
        for path in [self.older, self.previous, failed]:
            self.assertFalse(path.exists())
        self.assertFalse((self.base / 'previous').is_symlink())
        self.assertEqual(prune_releases(self.base), [])

    def test_dry_run_does_not_delete(self):
        self.assertEqual(prune_releases(self.base, dry_run=True), [self.older, self.previous])
        self.assertTrue(self.older.is_dir())
        self.assertEqual((self.base / 'previous').resolve(strict=True), self.previous)

    def test_no_legacy_pointer_is_required_after_upgrade(self):
        (self.base / 'previous').unlink()
        self.assertEqual(prune_releases(self.base), [self.older, self.previous])

    def test_open_file_or_working_directory_defers_entire_batch(self):
        pid = self.proc / '123'
        (pid / 'fd').mkdir(parents=True)
        for handle, target in [(pid / 'fd/7', self.previous / 'version'), (pid / 'cwd', self.previous)]:
            with self.subTest(handle=handle):
                handle.symlink_to(target)
                with self.assertRaisesRegex(ValueError, 'in use'):
                    prune_releases(self.base)
                self.assertTrue(self.older.is_dir())
                self.assertEqual((self.base / 'previous').resolve(strict=True), self.previous)
                handle.unlink()

    def test_invalid_current_pointer_fails_closed(self):
        write_pointer(self.base, 'current', self.base)
        with self.assertRaisesRegex(ValueError, 'does not point'):
            prune_releases(self.base)
        self.assertTrue(self.older.is_dir())

    def test_nested_mount_blocks_cleanup(self):
        nested = self.older / 'mounted'
        with patch.object(Path, 'read_text', return_value=f'1 2 0:1 / {nested} rw - ext4 /dev/test rw\n'):
            with self.assertRaisesRegex(ValueError, 'mount point'):
                remove_release_trees([self.older])
        self.assertTrue(self.older.is_dir())


class StaticReleaseTests(TestCase):
    def test_restrictive_deployer_umask_does_not_break_nginx_traversal(self):
        with TemporaryDirectory() as temp:
            path = Path(temp)/('d'*40)
            previous = os.umask(0o077)
            try:
                create_release_dir(path)
                (path/'private-test').touch()
            finally:
                os.umask(previous)
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o711)
            self.assertEqual(stat.S_IMODE((path/'private-test').stat().st_mode), 0o600)

    def test_app_health_alone_cannot_approve_inaccessible_or_wrong_web_assets(self):
        body = b'fixture contents'
        digest = hashlib.md5(body, usedforsecurity=False).hexdigest()[:12]
        paths = {k: k.replace('.', f'.{digest}.') for k in STATIC_PROBES}
        modes = ('ok', 'denied', 'html', 'old-css', 'redirect', 'bad-manifest')
        for mode in modes:
            def check(cmd, **kwargs):
                if cmd[0] == 'runuser':
                    self.assertEqual(cmd[2], 'www-data')
                    data = paths if mode != 'bad-manifest' else {**paths, 'admin-desk.css': '../test'}
                    return subprocess.CompletedProcess(cmd, 0, json.dumps({'paths': data}).encode())
                if cmd[-1].endswith('/healthz/'):
                    return subprocess.CompletedProcess(cmd, 0, b'{"status":"ok"}')
                name = next(k for k, v in paths.items() if cmd[-1] == 'https://dawnpanel.ir/static/' + v)
                contents, status, mime = body, '200', STATIC_PROBES[name][0]
                if name == 'admin-desk.css':
                    if mode == 'denied':
                        raise subprocess.CalledProcessError(22, cmd)
                    if mode == 'html':
                        mime = 'text/html'
                    if mode == 'old-css':
                        contents = b'other contents'
                    if mode == 'redirect':
                        status = '302'
                return subprocess.CompletedProcess(cmd, 0, contents + f'\n{status} {mime}'.encode())
            with self.subTest(mode=mode), patch('deploy.release.subprocess.run', side_effect=check):
                self.assertEqual(healthy(Path('/example')), mode == 'ok')
