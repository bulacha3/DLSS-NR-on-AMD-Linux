from contextlib import ExitStack, redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

from dlssnr import assets, cli, deploy, games, upstream


class RunnerDiscoveryTests(unittest.TestCase):
    def make_runner(self, path, layout='files'):
        wine = path / layout / 'bin/wine'
        wine.parent.mkdir(parents=True, exist_ok=True)
        wine.write_bytes(b'discovery fixture, never executed')
        return path.resolve()

    def registration(self, path, target):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('"compatibilitytools" { "compat_tools" { "test-tool" { '
                        '"install_path" ' + json.dumps(str(target)) + ' } } }')

    def test_direct_user_and_system_layouts(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            steam = root / 'Steam'; steam.mkdir()
            system = root / 'system/compatibilitytools.d'
            expected = {
                self.make_runner(steam / 'steamapps/common/Proton - Experimental'),
                self.make_runner(steam / 'compatibilitytools.d/GE-Proton', 'dist'),
                self.make_runner(system / 'proton-cachyos-slr'),
                self.make_runner(system / 'proton-cachyos-native', ''),
            }
            (steam / 'compatibilitytools.d/cachyos-alias').symlink_to(system / 'proton-cachyos-slr')
            with patch.object(games, 'SYSTEM_COMPATIBILITY_ROOTS', (system,)):
                found = games.discover_protons(steam)
            self.assertEqual(set(found), expected)
            self.assertEqual(len(found), len(expected))

    def test_vdf_registrations_resolve_relative_and_absolute_paths(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            system = root / 'system/compatibilitytools.d'
            absolute = self.make_runner(root / 'elsewhere/Proton CachyOS')
            relative = self.make_runner(root / 'system/relative-runner', 'dist')
            self.registration(system / 'proton-cachyos-slr.vdf', absolute)
            self.registration(system / 'relative.vdf', '../relative-runner')
            self.registration(system / 'duplicate.vdf', absolute)
            with patch.object(games, 'SYSTEM_COMPATIBILITY_ROOTS', (system,)):
                found = games.discover_protons(root / 'missing-Steam')
            self.assertEqual(set(found), {absolute, relative})
            self.assertEqual(len(found), 2)

    def test_bad_registration_does_not_hide_other_runners(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            system = root / 'compatibilitytools.d'
            good = self.make_runner(system / 'good-runner')
            (system / 'broken.vdf').write_text('"compatibilitytools" {')
            self.registration(system / 'missing.vdf', root / 'missing-runner')
            self.registration(system / 'wrong-type.vdf', root / 'not-a-runner')
            with patch.object(games, 'SYSTEM_COMPATIBILITY_ROOTS', (system,)):
                with self.assertWarnsRegex(RuntimeWarning, 'registration skipped'):
                    found = games.discover_protons(root / 'missing-Steam')
            self.assertEqual(found, [good])


class RunnerSelectionTests(unittest.TestCase):
    FIRST = Path('/runners/Proton - Experimental')
    CACHY = Path('/system/compatibilitytools.d/proton-cachyos-slr')

    def run_selection(self, answers, *, initial=FIRST, available=None,
                      interactive=True, confirmed=False):
        available = [self.FIRST, self.CACHY] if available is None else available
        output, error = io.StringIO(), io.StringIO()
        with tempfile.TemporaryDirectory() as temp, ExitStack() as stack:
            weights = Path(temp) / 'weights.bin'
            weights.write_bytes(b'DLSSNRW1' + struct.pack('<II', 1, 37)
                                + b'\x04test' + struct.pack('<QQ', 0, 4) + b'data')
            stack.enter_context(redirect_stdout(output))
            stack.enter_context(redirect_stderr(error))
            stack.enter_context(patch.object(cli.sys.stdin, 'isatty', return_value=interactive))
            prompt = stack.enter_context(patch('builtins.input', side_effect=answers))
            stack.enter_context(patch.object(assets, 'verify_assets', return_value={}))
            stack.enter_context(patch.object(assets, 'require_deployable'))
            stack.enter_context(patch.object(cli, 'check_host', return_value={}))
            exe = Path(temp) / 'Game.exe'
            stack.enter_context(patch.object(cli, 'resolve_exe', return_value=exe))
            stack.enter_context(patch.object(games, 'inspect_game', return_value={
                'exe': exe, 'dx12': True, 'fsr_evidence': ['FSR3'],
                'anti_cheat_evidence': [], 'version_loader': True}))
            stack.enter_context(patch.object(games, 'discover_protons', return_value=available))
            def validate(path):
                path = Path(path)
                if path not in (self.FIRST, self.CACHY):
                    raise RuntimeError('Incompatible Proton: test missing runner')
                return {'root': path, 'wine': path / 'files/bin/wine'}
            stack.enter_context(patch.object(games, 'validate_proton', side_effect=validate))
            stack.enter_context(patch.object(deploy, 'running_game', return_value=False))
            probe = stack.enter_context(patch.object(cli, 'readonly_runtime', return_value={
                'library': '/example/hip.so',
                'devices': [{'index': 0, 'name': 'test GPU', 'arch': 'gfx1201'}]}))
            install_runtime = stack.enter_context(patch.object(cli, 'ensure_runtime'))
            download = stack.enter_context(patch.object(upstream, 'prepared_package'))
            deployment = stack.enter_context(patch.object(deploy, 'install_game'))
            emitted = stack.enter_context(patch.object(cli, 'emit'))
            args = ['install', '--exe', str(exe), '--dry-run', '--accept-risk', '--weights', str(weights)]
            if initial is not None:
                args += ['--runner', str(initial)]
            if confirmed:
                args += ['--confirm-runner']
            result = cli.main(args)
            install_runtime.assert_not_called()
            download.assert_not_called()
            deployment.assert_not_called()
        return result, output.getvalue(), error.getvalue(), emitted, probe, prompt

    def test_no_selects_another_runner(self):
        for no in ('n', 'N', '', 'não'):
            with self.subTest(answer=no):
                result, _, error, emitted, probe, _ = self.run_selection([no, 'steam', '2', 'y'])
                self.assertEqual(result, 0, error)
                self.assertEqual(emitted.call_args.args[0]['proton'], self.CACHY)
                probe.assert_called_once()

    def test_cancel_stops_before_runtime(self):
        for answers in (['q'], ['n', ''], ['n', 'steam', '']):
            with self.subTest(answers=answers):
                result, output, error, emitted, probe, _ = self.run_selection(answers)
                self.assertEqual(result, 130)
                self.assertIn('Cancelled:', output)
                self.assertEqual(error, '')
                emitted.assert_not_called()
                probe.assert_not_called()

    def test_invalid_reply_is_reprompted(self):
        result, output, error, emitted, probe, prompt = self.run_selection(['maybe', 'q'])
        self.assertEqual(result, 130)
        self.assertIn('Please answer y', output)
        self.assertEqual(error, '')
        self.assertEqual(prompt.call_count, 2)
        emitted.assert_not_called()
        probe.assert_not_called()

    def test_steam_discovery_is_explicit_even_with_one_runner(self):
        result, output, error, emitted, _, prompt = self.run_selection(
            ['steam', '1', 'y'], initial=None, available=[self.CACHY])
        self.assertEqual(result, 0, error)
        self.assertIn('1. ' + str(self.CACHY), output)
        self.assertEqual(prompt.call_count, 3)
        self.assertEqual(emitted.call_args.args[0]['proton'], self.CACHY)

    def test_bad_menu_number_is_retryable(self):
        result, output, error, emitted, _, _ = self.run_selection(
            ['steam', '99', '2', 'y'], initial=None)
        self.assertEqual(result, 0, error)
        self.assertIn('Choose a number from the list', output)
        self.assertEqual(emitted.call_args.args[0]['proton'], self.CACHY)

    def test_noninteractive_confirmation_is_still_required(self):
        result, _, error, emitted, probe, prompt = self.run_selection([], interactive=False)
        self.assertEqual(result, 2)
        self.assertIn('--confirm-runner', error)
        emitted.assert_not_called()
        probe.assert_not_called()
        prompt.assert_not_called()
        result, _, error, emitted, _, prompt = self.run_selection([], interactive=False, confirmed=True)
        self.assertEqual(result, 0, error)
        self.assertEqual(emitted.call_args.args[0]['proton'], self.FIRST)
        prompt.assert_not_called()

    def test_invalid_path_can_be_corrected(self):
        result, output, error, emitted, _, _ = self.run_selection(
            [str(self.CACHY), 'y'], initial=Path('/missing/runner'))
        self.assertEqual(result, 0, error)
        self.assertIn('test missing runner', output)
        self.assertEqual(emitted.call_args.args[0]['proton'], self.CACHY)


if __name__ == '__main__':
    unittest.main()
