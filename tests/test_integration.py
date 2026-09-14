import hashlib
from contextlib import ExitStack, redirect_stderr, redirect_stdout
import io
import json
import os
from pathlib import Path
import struct
import tarfile
import tempfile
import unittest
from unittest.mock import patch

from dlssnr import assets, cli, deploy, games, upstream
import build_release

ROOT = Path(__file__).resolve().parents[1]


class IntegrationTests(unittest.TestCase):
    def test_reject_wrong_upstream(self):
        for data in (b'', b'MZ' + b'0' * 64):
            with self.assertRaises(ValueError):
                upstream.inspect_setup(data)

    def test_reject_metadata_only_release(self):
        with self.assertRaises(RuntimeError):
            assets.require_deployable({'mod_version': '0.3.0', 'files': {}})

    def test_configuration_defaults_and_update(self):
        initial = deploy._ini(b'', 1).decode()
        self.assertIn('PreUpscale=1', initial)
        self.assertIn('Async=0', initial)
        self.assertNotIn('Inline=1', initial)
        previous = b'[DlssNrOnAmd]\nPreUpscale=0\nScale=0.05\nAsync=1\n'
        updated = deploy._ini(previous, 2, update=True).decode()
        self.assertIn('PreUpscale=0', updated)
        self.assertIn('Scale=0.05', updated)
        self.assertIn('Async=0', updated)
        self.assertIn('HipDevice=2', updated)

    def test_install_update_uninstall_and_rollback(self):
        with tempfile.TemporaryDirectory() as temp:
            temp = Path(temp)
            game = temp / 'game'; game.mkdir()
            exe = game / 'game.exe'; exe.write_bytes(b'test game')
            original = b'user original dll'
            (game / 'version.dll').write_bytes(original)
            library = temp / 'hip.so'; library.write_bytes(b'test HIP library')
            weights = temp / 'weights.bin'; weights.write_bytes(b'DLSSNRW1' + b'test weights')
            package = temp / 'package'; (package / 'assets').mkdir(parents=True)
            def component_set(revision):
                hashes = {}
                for name in deploy.DLLS + (deploy.BRIDGE,):
                    content = (name + revision).encode()
                    (package / 'assets' / name).write_bytes(content)
                    hashes[name] = hashlib.sha256(content).hexdigest()
                (package / 'assets/manifest.json').write_text(json.dumps({'files': hashes}))
            component_set('one')
            runtime = {'library': str(library)}
            gpu = {'index': 0, 'name': 'test AMD'}
            runner = {'root': str(temp / 'runner')}
            with patch.dict(os.environ, {'XDG_DATA_HOME': str(temp / 'data')}):
                result = deploy.install_game(exe, package, runtime, gpu, runner, weights,
                    acknowledge_risk=True, replace_existing=True)
                self.assertTrue(result['valid'])
                self.assertIn(upstream.FLAG_SHADER_HASH, (game / deploy.STORE / 'launch.sh').read_text())
                ini = game / deploy.INI
                ini.write_text(ini.read_text().replace('PreUpscale=1', 'PreUpscale=0'))
                component_set('two')
                copy = deploy._atomic_copy
                failed = False
                def failing_copy(source, destination, *args, **kwargs):
                    nonlocal failed
                    if Path(destination) == game / 'd3d12core.dll' and not failed:
                        failed = True
                        raise OSError('simulated interrupted update')
                    return copy(source, destination, *args, **kwargs)
                with patch.object(deploy, '_atomic_copy', side_effect=failing_copy):
                    with self.assertRaises(OSError):
                        deploy.install_game(exe, package, runtime, gpu, runner, weights,
                            acknowledge_risk=True)
                self.assertEqual((game / 'version.dll').read_bytes(), b'version.dllone')
                result = deploy.install_game(exe, package, runtime, gpu, runner, weights,
                    acknowledge_risk=True)
                self.assertTrue(result['valid'])
                self.assertIn('PreUpscale=0', ini.read_text())
                deploy.uninstall_game(exe)
                self.assertEqual((game / 'version.dll').read_bytes(), original)
                self.assertFalse((game / 'd3d12.dll').exists())

    @unittest.skipUnless(os.environ.get('DLSSNR_TEST_SETUP'), 'official fixture path not supplied')
    def test_real_upstream_staging_and_deterministic_package(self):
        components = ROOT / 'build/components'
        with tempfile.TemporaryDirectory() as temp:
            temp = Path(temp)
            archive, checksum = build_release.build_release(ROOT, temp, components)
            first = archive.read_bytes()
            build_release.build_release(ROOT, temp, components)
            self.assertEqual(first, archive.read_bytes())
            with tarfile.open(archive) as source:
                names = source.getnames()
                self.assertNotIn('dlssnr-linux-portable/assets/version.dll', names)
                self.assertNotIn('dlssnr-linux-portable/assets/dlssnr_on_amd_setup.exe', names)
                source.extractall(temp / 'extracted', filter='data')
            package = temp / 'extracted/dlssnr-linux-portable'
            with upstream.prepared_package(package, os.environ['DLSSNR_TEST_SETUP']) as prepared:
                manifest = assets.verify_assets(prepared)
                assets.require_deployable(manifest)
                self.assertEqual(assets.sha256(prepared / 'assets/version.dll'), upstream.PAYLOAD_SHA256)
                self.assertEqual(assets.sha256(prepared / 'assets/dlssnr_on_amd_setup.exe'), upstream.SETUP_SHA256)
            self.assertFalse(prepared.exists())


class DetectionTests(unittest.TestCase):
    def run_detection(self, options=(), *, command='install', detected=False,
                      interactive=False, answer='', dx12=True, anti=()):
        evidence = {'exe': Path('/example/Game.exe'), 'dx12': dx12,
                    'fsr_evidence': ['amd_fidelityfx_upscaler_dx12.dll'] if detected else [],
                    'anti_cheat_evidence': list(anti), 'version_loader': True}
        output, error = io.StringIO(), io.StringIO()
        with ExitStack() as stack:
            stack.enter_context(redirect_stdout(output))
            stack.enter_context(redirect_stderr(error))
            stack.enter_context(patch.object(cli.sys.stdin, 'isatty', return_value=interactive))
            prompt = stack.enter_context(patch('builtins.input', return_value=answer))
            stack.enter_context(patch.object(assets, 'verify_assets', return_value={}))
            stack.enter_context(patch.object(assets, 'require_deployable'))
            stack.enter_context(patch.object(cli, 'check_host', return_value={}))
            stack.enter_context(patch.object(cli, 'resolve_exe', return_value=evidence['exe']))
            stack.enter_context(patch.object(games, 'inspect_game', return_value=evidence))
            runner = stack.enter_context(patch.object(cli, 'resolve_proton'))
            if command == 'doctor':
                runner.return_value = {'root': '/example/Proton'}
            else:
                # Stop at the next user-facing step; no Wine or GPU is needed.
                runner.side_effect = RuntimeError('Runner selection reached')
            stack.enter_context(patch.object(cli, 'readonly_runtime', return_value={
                'library': '/example/hip.so',
                'devices': [{'index': 0, 'name': 'test GPU', 'arch': 'gfx1201'}]}))
            download = stack.enter_context(patch.object(upstream, 'prepared_package',
                side_effect=AssertionError('Game detection must not download or stage the runtime')))
            result = cli.main([command, '--exe', str(evidence['exe']), *options])
            download.assert_not_called()
        return result, output.getvalue(), error.getvalue(), evidence, runner, prompt

    def test_missing_fsr_needs_its_own_confirmation(self):
        result, _, error, _, runner, prompt = self.run_detection(
            ['--accept-risk', '--confirm-runner', '--allow-unconfirmed-loader'])
        self.assertEqual(result, 2)
        self.assertIn('--confirm-fsr', error)
        runner.assert_not_called()
        prompt.assert_not_called()

    def test_embedded_fsr_confirmation_reaches_next_step(self):
        for options, interactive, answer, detected in (
                (['--confirm-fsr'], False, '', False),
                ([], True, 'y', False),
                ([], False, '', True)):
            with self.subTest(options=options, interactive=interactive, detected=detected):
                result, _, error, evidence, runner, _ = self.run_detection(
                    options, interactive=interactive, answer=answer, detected=detected)
                self.assertEqual(result, 2)
                self.assertIn('Runner selection reached', error)
                runner.assert_called_once()
                self.assertEqual(bool(evidence['fsr_evidence']), detected)
                self.assertEqual(evidence['fsr_confirmed_by_user'], not detected)

    def test_declined_fsr_confirmation_stops_installation(self):
        for answer in ('', 'n'):
            with self.subTest(answer=answer):
                result, _, error, _, runner, prompt = self.run_detection(
                    interactive=True, answer=answer)
                self.assertEqual(result, 2)
                self.assertIn('--confirm-fsr', error)
                runner.assert_not_called()
                prompt.assert_called_once()

    def test_fsr_confirmation_preserves_other_requirements(self):
        for dx12, anti, message in ((False, (), 'DirectX 12'),
                                   (True, ('EasyAntiCheat',), 'Anti-cheat detected')):
            with self.subTest(dx12=dx12, anti=anti):
                result, _, error, _, runner, prompt = self.run_detection(
                    ['--confirm-fsr'], interactive=True, answer='y', dx12=dx12, anti=anti)
                self.assertEqual(result, 2)
                self.assertIn(message, error)
                runner.assert_not_called()
                prompt.assert_not_called()

    def test_doctor_reports_unknown_fsr_without_requesting_confirmation(self):
        result, output, error, _, runner, prompt = self.run_detection(['--json'], command='doctor')
        self.assertEqual(result, 0, error)
        report = json.loads(output)
        self.assertEqual(report['game']['fsr_evidence'], [])
        self.assertFalse(report['game']['fsr_confirmed_by_user'])
        self.assertFalse(report['gameplay_verified'])
        self.assertTrue(any('FSR was not detected' in warning for warning in report['warnings']))
        runner.assert_called_once()
        prompt.assert_not_called()


if __name__ == '__main__':
    unittest.main()
