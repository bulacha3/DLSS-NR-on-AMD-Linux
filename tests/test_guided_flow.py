"""Run the complete interactive CLI; replace only external deployment services."""
from contextlib import ExitStack, redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import shlex
import tempfile
import unittest
from unittest.mock import patch

from dlssnr import assets, cli, deploy, games, lmxxf, runtime, upstream
from test_game_selection import write_executable


class GuidedFlow(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='dlssnr-wizard-')
        self.addCleanup(temporary.cleanup)
        self.home = Path(temporary.name)
        self.steam = self.home / '.local/share/Steam'
        self.game = self.steam / 'steamapps/common/Example Adventure'
        self.exe = write_executable(self.game / 'bin/x64/Adventure.exe')
        write_executable(self.game / 'bin/x64/ErrorReporter.exe')
        (self.steam / 'steamapps/appmanifest_12345.acf').write_text(
            '"AppState" { "appid" "12345" "name" "Example Adventure" '
            '"installdir" "Example Adventure" }')
        self.runner = self.steam / 'compatibilitytools.d/Example-Proton'
        wine = self.runner / 'files/bin/wine'
        wine.parent.mkdir(parents=True)
        wine.write_bytes(b'Runner discovery fixture, never executed')
        self.wrapper = self.exe.parent / deploy.STORE / 'launch.sh'
        self.weights = self.exe.parent / deploy.WEIGHTS
        self.weights.write_bytes(b'Model validation mocked; no model data included')
        self.cache = self.home / '.local/share/dlssnr-linux'
        self.api, _ = lmxxf.backend(cli.PACKAGE_ROOT)
        self.state_root, self.entry = self.api.installation_paths(self.wrapper, lmxxf.cache_base(self.cache))
        self.command = shlex.quote(str(self.entry)) + ' %command%'

    def run_wizard(self, answers, *, existing=False, saved=None, fsr_evidence=False):
        if saved is not None:
            self.state_root.mkdir(parents=True, exist_ok=True)
            (self.state_root / 'activation.json').write_text(json.dumps({'steam_launch_options': saved}))
        supplied = iter(answers)
        prompts, actions = [], []
        out, err = io.StringIO(), io.StringIO()

        def answer(prompt):
            prompts.append(prompt)
            try:
                return next(supplied)
            except StopIteration:
                self.fail('Unexpected prompt: ' + prompt + '\nOutput:\n' + out.getvalue())

        def validate_runner(path):
            path = Path(path).expanduser().resolve()
            if path != self.runner:
                raise RuntimeError('Choose a compatible runner directory.')
            return {'root': path, 'wine': path / 'files/bin/wine'}

        base = {'installed': True, 'valid': True, 'pending': False,
                'launch_options': shlex.quote(str(self.wrapper)) + ' %command%',
                'command_prefix': shlex.quote(str(self.wrapper))}

        def install(*args, **kwargs):
            actions.append(('install', args, kwargs))
            return dict(base)

        def activate(*args, **kwargs):
            actions.append(('activate', args, kwargs))
            return {'backend': 'lmxxf', 'launch_options': kwargs.get('launch_options') or self.command,
                    'command_prefix': shlex.quote(str(self.entry))}

        rt = {'library': str(self.home / 'HIP.so'),
              'devices': [{'index': 0, 'name': 'Synthetic supported device', 'arch': 'gfx1201'}]}
        with ExitStack() as stack:
            stack.enter_context(redirect_stdout(out))
            stack.enter_context(redirect_stderr(err))
            stack.enter_context(patch('builtins.input', side_effect=answer))
            stack.enter_context(patch.object(cli.sys.stdin, 'isatty', return_value=True))
            stack.enter_context(patch.object(Path, 'home', return_value=self.home))
            stack.enter_context(patch.dict(cli.os.environ, {'XDG_DATA_HOME': str(self.home / '.local/share')}))
            stack.enter_context(patch.object(games, 'SYSTEM_COMPATIBILITY_ROOTS', ()))
            # Real Steam manifest/runner discovery, executable selection, wizard,
            # runner confirmation and launch-option parsing remain in the path.
            stack.enter_context(patch.object(games, 'validate_proton', side_effect=validate_runner))
            stack.enter_context(patch.object(games, 'inspect_game', return_value={
                'exe': self.exe, 'dx12': True, 'anti_cheat_evidence': [], 'version_loader': True,
                'fsr_evidence': ['synthetic FSR evidence'] if fsr_evidence else []}))
            stack.enter_context(patch.object(assets, 'verify_assets', return_value={}))
            stack.enter_context(patch.object(assets, 'require_deployable'))
            stack.enter_context(patch.object(assets, 'validate_weights', return_value={}))
            stack.enter_context(patch.object(cli, 'check_host', return_value={}))
            stack.enter_context(patch.object(deploy, 'running_game', return_value=False))
            stack.enter_context(patch.object(runtime, 'ensure_runtime', return_value=rt))
            stack.enter_context(patch.object(runtime, 'probe_runtime', return_value=rt))
            stack.enter_context(patch.object(lmxxf, 'existing_runtime', return_value={
                'DLSSNR_HIP_LIBRARY': rt['library'],
                'VKD3D_FILTER_DEVICE_NAME': 'Synthetic supported device'} if existing else None))
            stack.enter_context(patch.object(cli, 'candidate_weights', return_value=self.home / 'prepared'))
            stage = stack.enter_context(patch.object(upstream, 'prepared_package'))
            stage.return_value.__enter__.return_value = cli.PACKAGE_ROOT
            stack.enter_context(patch.object(deploy, 'install_game', side_effect=install))
            stack.enter_context(patch.object(deploy, 'status_game', return_value=dict(base)))
            stack.enter_context(patch.object(lmxxf, 'activate', side_effect=activate))
            stack.enter_context(patch('urllib.request.urlopen', side_effect=AssertionError('No network in wizard tests')))
            code = cli.main([])
        self.assertEqual(list(supplied), [], 'Wizard returned before consuming the expected interaction.\n' + out.getvalue() + err.getvalue())
        return code, out.getvalue(), err.getvalue(), prompts, actions

    def assert_steps(self, output):
        positions = [output.index(f'{n}/5') for n in range(1, 6)]
        self.assertEqual(positions, sorted(positions))

    def test_fresh_steam_native_fsr_walks_every_step_and_prints_final_command(self):
        result = self.run_wizard(['1', '1', '1', '1', 'y', '1', 'y', '2'])
        code, out, err, prompts, actions = result
        self.assertEqual(code, 0, err)
        self.assert_steps(out)
        self.assertEqual([a[0] for a in actions], ['install', 'activate'])
        self.assertIn('In the game: select FSR 3/4.', out)
        self.assertIn(self.command, out)
        self.assertNotIn('In your launcher, set this command prefix', out)
        self.assertEqual(actions[0][1][0], self.exe)
        self.assertEqual(actions[0][1][4]['root'], self.runner)

    def test_existing_steam_optiscaler_preserves_full_options_after_runner_selection(self):
        before = 'PROTON_ENABLE_HDR=1 PROTON_OPTISCALER_CONFIG="Upscalers.Dx12Upscaler=fsr31;Menu.OverlayMenu=true" '
        current = before + shlex.quote(str(self.wrapper)) + ' %command% -dx12'
        code, out, err, prompts, actions = self.run_wizard(
            ['1', '1', '1', '1', 'y', '2', '1', current], existing=True)
        self.assertEqual(code, 0, err)
        self.assert_steps(out)
        self.assertEqual([a[0] for a in actions], ['activate'])
        self.assertIn('In the game: select DLSS', out)
        expected = before + shlex.quote(str(self.entry)) + ' %command% -dx12'
        self.assertEqual(actions[-1][2]['launch_options'], expected)
        self.assertIn(expected, out)
        self.assertLess(next(i for i, p in enumerate(prompts) if p.startswith('Wine/Proton runner')),
                        next(i for i, p in enumerate(prompts) if p.startswith('Paste the full')))

    def test_other_launcher_fresh_and_update_never_ask_for_steam_options(self):
        for existing, route in ((False, '1'), (True, '2')):
            with self.subTest(existing=existing, route=route):
                answers = ['2', f'"{self.exe}"', f'"{self.runner}"', 'y', route]
                if not existing:
                    answers.append('y')
                code, out, err, prompts, actions = self.run_wizard(answers, existing=existing)
                self.assertEqual(code, 0, err)
                self.assert_steps(out)
                self.assertFalse(any('Launch Options text' in p for p in prompts))
                self.assertNotIn('Steam > Properties > General > Launch Options: replace', out)
                self.assertIn('In your launcher, set this command prefix', out)
                self.assertIn(shlex.quote(str(self.entry)), out)
                self.assertNotIn(self.command, out)
                self.assertEqual(actions[-1][2]['launch_options'], None)

    def test_invalid_choices_paths_and_steam_text_retry_in_the_correct_step(self):
        current = 'PROTON_ENABLE_HDR=1 %command% -dx12'
        answers = ['bad', '1', '0', str(self.home / 'missing'), f'"{self.game}"',
                   '99', '1', '99', '1', 'y', 'bad', '2', 'y', 'bad', '1', 'steam', current]
        code, out, err, prompts, actions = self.run_wizard(answers)
        self.assertEqual(code, 0, err)
        self.assertIn('Steam is already selected as the launcher.', out)
        self.assertEqual(actions[-1][2]['launch_options'],
                         'PROTON_ENABLE_HDR=1 ' + self.command + ' -dx12')
        self.assertEqual(sum(p.startswith('Paste the full') for p in prompts), 2)

    def test_cancel_before_installation_at_each_meaningful_step(self):
        cases = ([''], ['1', ''], ['1', '1', ''], ['1', '1', '1', ''],
                 ['1', '1', '1', '1', 'q'], ['1', '1', '1', '1', 'y', '3'],
                 ['1', '1', '1', '1', 'y', '1', 'y', ''])
        for answers in cases:
            with self.subTest(answers=answers):
                code, out, err, prompts, actions = self.run_wizard(answers)
                self.assertEqual(code, 130, out + err)
                self.assertEqual(actions, [])

    def test_update_can_keep_saved_options_with_explicit_choice(self):
        saved = 'CUSTOM="literal $HOME; `value`" ' + self.command + ' -dx12'
        code, out, err, prompts, actions = self.run_wizard(
            ['1', '1', '1', '1', 'y', '1', '1'], existing=True, saved=saved)
        self.assertEqual(code, 0, err)
        self.assertIn('Previously saved launch options:', out)
        self.assertEqual(actions[-1][2]['launch_options'], saved)
        self.assertEqual([a[0] for a in actions], ['activate'])


if __name__ == '__main__':
    unittest.main()
