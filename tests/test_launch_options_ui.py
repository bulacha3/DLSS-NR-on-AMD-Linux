"""Steam options menu contracts using the real text-preserving merger."""
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import shlex
import tempfile
import unittest
from unittest.mock import patch

from dlssnr import deploy, lmxxf


class LaunchOptionsUI(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.folder = Path(self.temporary.name)
        self.package = Path(__file__).resolve().parents[1]
        self.exe = self.folder/'Example Game/bin/Game.exe'
        self.cache = self.folder/'cache'
        self.exe.parent.mkdir(parents=True)
        api, _ = lmxxf.backend(self.package)
        self.wrapper = self.exe.parent/deploy.STORE/'launch.sh'
        self.state, self.entry = api.installation_paths(self.wrapper, lmxxf.cache_base(self.cache))
        self.default = shlex.quote(str(self.entry))+' %command%'

    def save(self, value):
        self.state.mkdir(parents=True)
        (self.state/'activation.json').write_text(json.dumps({'steam_launch_options': value}))

    def run_menu(self, answers):
        output = io.StringIO()
        with patch('builtins.input', side_effect=answers), redirect_stdout(output):
            result = lmxxf.launch_options(self.package, self.cache, self.exe, interactive=True)
        return result, output.getvalue()

    def test_paste_preserves_quoted_settings_and_game_arguments(self):
        original = 'HDR=1 OPTISCALER="Inputs.Ffx=false;Menu.Overlay=true" '+shlex.quote(str(self.wrapper))+' %command% -dx12'
        result, output = self.run_menu(['1', original])
        self.assertEqual(result, original.replace(shlex.quote(str(self.wrapper)), shlex.quote(str(self.entry))))
        self.assertIn('Properties > General > Launch Options', output)
        self.assertFalse(self.state.exists())

    def test_saved_options_are_displayed_and_explicitly_reused(self):
        original = 'HDR=1 '+shlex.quote(str(self.wrapper))+' %command% -dx12'
        self.save(original)
        before = (self.state/'activation.json').read_bytes()
        result, output = self.run_menu(['1'])
        self.assertIn(original, output)
        self.assertEqual(result, 'HDR=1 '+self.default+' -dx12')
        self.assertEqual((self.state/'activation.json').read_bytes(), before)

    def test_empty_steam_field_requires_explicit_menu_choice(self):
        result, _ = self.run_menu(['1', '', '2'])
        self.assertEqual(result, self.default)

    def test_blank_paste_does_not_discard_saved_options(self):
        self.save('HDR=1 %command% -dx12')
        result, _ = self.run_menu(['2', '', '1'])
        self.assertEqual(result, 'HDR=1 '+self.default+' -dx12')

    def test_saved_options_can_be_replaced_with_an_explicit_empty_field(self):
        self.save('HDR=1 %command% -dx12')
        result, _ = self.run_menu(['3'])
        self.assertEqual(result, self.default)

    def test_typing_steam_explains_the_field_and_allows_retry(self):
        result, output = self.run_menu(['1', ' steam ', 'HDR=1 %command%'])
        self.assertEqual(result, 'HDR=1 '+self.default)
        self.assertIn('Steam is already selected as the launcher', output)
        self.assertIn('If that field is empty, press Enter', output)

    def test_invalid_options_are_correctable_without_leaving_the_installer(self):
        result, output = self.run_menu(['nonsense', '1', 'HDR=1', 'HDR=1 %command%'])
        self.assertEqual(result, 'HDR=1 '+self.default)
        self.assertIn('Choose one of the numbered options', output)
        self.assertIn('exactly one %command%', output)

    def test_menu_cancel_does_not_write_installation_state(self):
        for choice in ('', 'q', 'Q'):
            with self.subTest(choice=choice), self.assertRaises(KeyboardInterrupt):
                self.run_menu([choice])
        self.assertFalse(self.state.exists())

    def test_noninteractive_without_saved_options_returns_none(self):
        with patch('builtins.input', side_effect=AssertionError('unexpected prompt')):
            self.assertIsNone(lmxxf.launch_options(self.package, self.cache, self.exe))

    def test_noninteractive_reuses_saved_options(self):
        self.save('HDR=1 %command% -dx12')
        with patch('builtins.input', side_effect=AssertionError('unexpected prompt')):
            self.assertEqual(lmxxf.launch_options(self.package, self.cache, self.exe), 'HDR=1 '+self.default+' -dx12')

    def test_explicit_options_skip_the_menu_even_in_interactive_mode(self):
        self.save('HDR=1 %command%')
        with patch('builtins.input', side_effect=AssertionError('unexpected prompt')):
            self.assertEqual(lmxxf.launch_options(self.package, self.cache, self.exe,
                supplied='OPT=2 %command%', interactive=True), 'OPT=2 '+self.default)

    def test_pasted_shell_text_is_only_parsed_never_executed(self):
        marker = self.folder/'must-not-exist'
        original = 'CUSTOM="$(touch '+str(marker)+')" %command%'
        result, _ = self.run_menu(['1', original])
        self.assertEqual(result, original.replace('%command%', self.default))
        self.assertFalse(marker.exists())

    def test_argument_only_options_are_added_after_command(self):
        for original in ('-dx12 --skip-launcher', '+fps_max 120', '  --name "Example Game" -dx12'):
            with self.subTest(original=original):
                result, _ = self.run_menu(['1', original])
                self.assertEqual(result, self.default+' '+original)

    def test_environment_and_custom_commands_without_placeholder_are_rejected(self):
        for original in ('HDR=1', 'steam', 'gamemoderun -dx12'):
            with self.subTest(original=original), self.assertRaises(ValueError):
                lmxxf.launch_options(self.package, self.cache, self.exe, supplied=original)

    def test_argument_only_shell_syntax_is_not_reinterpreted(self):
        for original in ('-dx12; echo wrong', '-dx12 && echo wrong', '-dx12 | cat',
                         '-dx12 > result.txt', '-arg "$(echo wrong)"', '-arg `echo wrong`',
                         '-arg *.json', '-arg $HOME', '-arg "unterminated', '-arg\nvalue'):
            with self.subTest(original=original), self.assertRaises(ValueError):
                lmxxf.launch_options(self.package, self.cache, self.exe, supplied=original)

    def test_original_backend_replaces_candidate_and_preserves_all_other_options(self):
        original = 'HDR=1 OPT="A=1;B=2" '+shlex.quote(str(self.entry))+' %command% -dx12'
        result = lmxxf.launch_options(self.package, self.cache, self.exe,
            supplied=original, original_backend=True)
        self.assertEqual(result, original.replace(shlex.quote(str(self.entry)), shlex.quote(str(self.wrapper))))

    def test_original_backend_reuses_saved_options_without_duplicate_launcher(self):
        original = 'HDR=1 '+shlex.quote(str(self.entry))+' %command% -dx12'
        self.save(original)
        with patch('builtins.input', side_effect=AssertionError('unexpected prompt')):
            result = lmxxf.launch_options(self.package, self.cache, self.exe, original_backend=True)
        self.assertEqual(result, 'HDR=1 '+shlex.quote(str(self.wrapper))+' %command% -dx12')

    def test_original_backend_keeps_existing_base_wrapper(self):
        original = 'HDR=1 '+shlex.quote(str(self.wrapper))+' %command% -dx12'
        result = lmxxf.launch_options(self.package, self.cache, self.exe,
            supplied=original, original_backend=True)
        self.assertEqual(result, original)

    def test_original_backend_normalizes_plain_arguments(self):
        result = lmxxf.launch_options(self.package, self.cache, self.exe,
            supplied='-dx12 --skip-launcher', original_backend=True)
        self.assertEqual(result, shlex.quote(str(self.wrapper))+' %command% -dx12 --skip-launcher')


if __name__ == '__main__':
    unittest.main()
