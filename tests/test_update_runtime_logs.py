"""Regression coverage for preserved runtime diagnostics during deployment updates."""
import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch

from dlssnr import deploy


class RuntimeLogUpdates(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.game = self.root / 'game/bin/x64'
        self.game.mkdir(parents=True)
        self.exe = self.game / 'game.exe'
        self.exe.write_bytes(b'test game')
        (self.game / 'version.dll').write_bytes(b'original game proxy')
        self.lib = self.root / 'hip.so'
        self.lib.write_bytes(b'fixture only; never loaded')
        self.weights = self.root / 'weights.bin'
        self.weights.write_bytes(b'DLSSNRW1fixture weights')
        self.package = self.root / 'package'
        (self.package / 'assets').mkdir(parents=True)
        self.env = patch.dict(os.environ, {'XDG_DATA_HOME': str(self.root / 'data')})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.set_components('one')
        self.install(replace_existing=True)
        self.store = self.game / deploy.STORE
        self.logs = self.store / 'logs'
        self.ini = self.game / deploy.INI
        self.ini.write_text(self.ini.read_text().replace('PreUpscale=1', 'PreUpscale=0'))
        self.set_components('two')

    def set_components(self, revision):
        hashes = {}
        for name in deploy.DLLS + (deploy.BRIDGE,):
            data = (name + revision).encode()
            (self.package / 'assets' / name).write_bytes(data)
            hashes[name] = hashlib.sha256(data).hexdigest()
        (self.package / 'assets/manifest.json').write_text(json.dumps({
            'files': hashes, 'graphics_wait_supported': True}))

    def install(self, **kwargs):
        return deploy.install_game(self.exe, self.package, {'library': str(self.lib)},
            {'index': 0, 'name': 'fixture GPU'}, {'root': str(self.root / 'runner')},
            self.weights, acknowledge_risk=True, **kwargs)

    def snapshot(self):
        result = {}
        for p in self.game.rglob('*'):
            st = p.lstat()
            data = p.read_bytes() if stat.S_ISREG(st.st_mode) else os.readlink(p) if p.is_symlink() else None
            result[str(p.relative_to(self.game))] = (st.st_mode, st.st_ino, st.st_mtime_ns, data)
        return result

    def add_reports(self):
        for name in ('hip.log', 'vkd3d.log', 'nr-profile.txt', 'kernel-profile.txt',
                     'resultado-etapa4.txt', 'c32-prepack.txt', 'trace.json', 'hip.log.1'):
            p = self.logs / name
            p.write_bytes(('diagnostic fixture: ' + name).encode())
            p.chmod(0o600)
        return {p.name: (p.read_bytes(), p.stat().st_mode, p.stat().st_ino, p.stat().st_mtime_ns)
                for p in self.logs.iterdir()}

    def assert_reports(self, expected):
        self.assertEqual({p.name: (p.read_bytes(), p.stat().st_mode, p.stat().st_ino, p.stat().st_mtime_ns)
                          for p in self.logs.iterdir()}, expected)

    def assert_refused_unchanged(self, message):
        before = self.snapshot()
        with self.assertRaisesRegex(RuntimeError, message):
            self.install()
        self.assertEqual(before, self.snapshot())

    def test_nr_profile_report_alone_reproduces_the_upgrade_case(self):
        report = self.logs / 'nr-profile.txt'
        report.write_bytes(b'profiling fixture')
        original = report.read_bytes()
        result = self.install()
        self.assertTrue(result['updated'])
        self.assertEqual(report.read_bytes(), original)

    def test_update_accepts_profiler_reports_without_changing_them(self):
        expected = self.add_reports()
        result = self.install()
        self.assertTrue(result['valid'])
        self.assertTrue(result['updated'])
        self.assertEqual((self.game / 'version.dll').read_bytes(), b'version.dlltwo')
        self.assertIn('PreUpscale=0', self.ini.read_text())
        self.assert_reports(expected)
        self.assertTrue(self.install()['idempotent'])
        self.assert_reports(expected)

    def test_dry_run_with_reports_changes_nothing(self):
        self.add_reports()
        before = self.snapshot()
        result = self.install(dry_run=True)
        self.assertTrue(result['update_planned'])
        self.assertEqual(before, self.snapshot())

    def test_changed_binary_is_still_rejected(self):
        self.add_reports()
        (self.game / 'version.dll').write_bytes(b'outside modification')
        self.assert_refused_unchanged('Deployed file changed')

    def test_changed_backup_is_still_rejected(self):
        self.add_reports()
        (self.store / 'backups/version.dll').write_bytes(b'outside modification')
        self.assert_refused_unchanged('Original backup changed')

    def test_unknown_files_outside_logs_are_still_rejected(self):
        for folder in (self.store, self.store/'runtime', self.store/'backups', self.store/'undo'):
            with self.subTest(folder=folder.name):
                p = folder / 'unmanaged.txt'
                p.write_bytes(b'keep this file')
                self.assert_refused_unchanged('Unknown file')
                p.unlink()

    def test_log_symlink_is_rejected_without_touching_destination(self):
        outside = self.root / 'external.txt'
        outside.write_bytes(b'private external fixture')
        p = self.logs / 'nr-profile.txt'
        for target in (outside, self.root/'missing.txt'):
            with self.subTest(broken=not target.exists()):
                p.symlink_to(target)
                self.assert_refused_unchanged('Unsafe symlink')
                p.unlink()
        self.assertEqual(outside.read_bytes(), b'private external fixture')

    def test_log_directory_symlink_is_rejected(self):
        self.logs.rmdir()
        outside = self.root / 'external-logs'
        outside.mkdir()
        self.logs.symlink_to(outside, target_is_directory=True)
        self.assert_refused_unchanged('Unsafe symlink')

    def test_nested_log_directory_is_not_adopted(self):
        (self.logs / 'nested').mkdir()
        self.assert_refused_unchanged('wrong path type')

    def test_log_fifo_is_not_opened_or_adopted(self):
        os.mkfifo(self.logs / 'nr-profile.txt')
        self.assert_refused_unchanged('wrong path type')

    def test_permission_changes_on_managed_binary_still_rejected(self):
        self.add_reports()
        (self.game / 'version.dll').chmod(0o600)
        self.assert_refused_unchanged('Deployed file mode changed')

    def test_update_failure_restores_binary_and_preserves_reports(self):
        expected = self.add_reports()
        old_ini = self.ini.read_bytes()
        copy = deploy._atomic_copy
        failed = False
        def fail_once(src, dst, *args, **kwargs):
            nonlocal failed
            if Path(dst) == self.game / 'd3d12core.dll' and not failed:
                failed = True
                raise OSError('injected update failure')
            return copy(src, dst, *args, **kwargs)
        with patch.object(deploy, '_atomic_copy', side_effect=fail_once):
            with self.assertRaisesRegex(OSError, 'injected update failure'):
                self.install()
        self.assertEqual((self.game / 'version.dll').read_bytes(), b'version.dllone')
        self.assertEqual(self.ini.read_bytes(), old_ini)
        self.assert_reports(expected)
        self.assertFalse((self.store / 'update.json').exists())
        self.assertTrue(self.install()['valid'])
        self.assert_reports(expected)

    def test_log_tolerance_cannot_enable_destructive_cleanup(self):
        self.add_reports()
        before = self.snapshot()
        with self.assertRaises(ValueError):
            deploy._cleanup(self.store, allow_runtime_logs=True)
        self.assertEqual(before, self.snapshot())

    def test_uninstall_does_not_gain_permission_to_delete_unknown_reports(self):
        self.add_reports()
        before = self.snapshot()
        with self.assertRaisesRegex(RuntimeError, 'Unknown file'):
            deploy.uninstall_game(self.exe)
        self.assertEqual(before, self.snapshot())


if __name__ == '__main__':
    unittest.main()
