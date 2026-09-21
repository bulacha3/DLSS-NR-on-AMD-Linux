"""Exercise real game discovery and guided path selection without a GPU."""
from contextlib import redirect_stdout
import io
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

from dlssnr import cli, games


def write_executable(path):
    """A minimal x64 PE image, parsed by the production PE reader."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    image = bytearray(1024)
    image[:2] = b'MZ'
    struct.pack_into('<I', image, 0x3c, 0x80)
    image[0x80:0x84] = b'PE\0\0'
    struct.pack_into('<HHIIIHH', image, 0x84, 0x8664, 1, 0, 0, 0, 240, 0x22)
    optional = 0x98
    struct.pack_into('<H', image, optional, 0x20b)
    struct.pack_into('<Q', image, optional + 24, 0x140000000)
    struct.pack_into('<I', image, optional + 60, 512)
    struct.pack_into('<8sIIIIIIHHI', image, optional + 240,
                     b'.text\0\0\0', 512, 4096, 512, 512, 0, 0, 0, 0, 0x60000020)
    path.write_bytes(image)
    return path


class GameSelection(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='dlssnr-selection-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.package = self.root / 'installer'
        self.package.mkdir()
        self.game = self.root / 'Example Adventure'
        self.exe = write_executable(self.game / 'bin/x64/Adventure.exe')
        self.helper = write_executable(self.game / 'bin/x64/ErrorReporter.exe')

    def resolve(self, arguments=(), answers=(), *, interactive=True):
        args = cli.parser().parse_args(['install', *map(str, arguments)])
        output = io.StringIO()
        with patch.object(cli, 'PACKAGE_ROOT', self.package), \
                patch('builtins.input', side_effect=answers) as prompt, redirect_stdout(output):
            selected = cli.resolve_exe(args, interactive)
        return selected, prompt.call_count, output.getvalue()

    def test_pasted_directory_quotes_and_spaces_offer_executable_choice(self):
        for directory in (self.game, self.exe.parent):
            for quote in ('', '"', "'"):
                with self.subTest(directory=directory.name, quote=quote):
                    selected, count, output = self.resolve(answers=[f'{quote}{directory}{quote}', '1'])
                    self.assertEqual(selected, self.exe)
                    self.assertEqual(count, 2)
                    self.assertIn('Adventure.exe', output)
                    self.assertIn('ErrorReporter.exe', output)

    def test_pasted_exact_executable_quotes_and_spaces_need_no_menu(self):
        for quote in ('', '"', "'"):
            with self.subTest(quote=quote):
                selected, count, _ = self.resolve(answers=[f'{quote}{self.exe}{quote}'])
                self.assertEqual(selected, self.exe)
                self.assertEqual(count, 1)

    def test_different_game_layouts_use_real_discovery(self):
        for name, relative in (('Northern Quest', 'Retail/North.exe'),
                               ('Clockwork City', 'Project/Binaries/Win64/Clockwork-Shipping.exe'),
                               ('Harbor', 'Harbor.exe')):
            with self.subTest(layout=relative):
                game = self.root / name
                exe = write_executable(game / relative)
                selected, count, _ = self.resolve(answers=[str(game)])
                self.assertEqual(selected, exe)
                self.assertEqual(count, 1)

    def test_invalid_menu_numbers_retry_without_losing_directory(self):
        selected, count, _ = self.resolve(answers=[str(self.game), '0', '999', 'bad', '１', '2'])
        self.assertEqual(selected, self.helper)
        self.assertEqual(count, 6)

    def test_bad_path_retries_and_then_accepts_valid_executable(self):
        selected, count, _ = self.resolve(answers=[str(self.root / 'missing folder'), str(self.exe)])
        self.assertEqual(selected, self.exe)
        self.assertEqual(count, 2)

    def test_empty_path_and_empty_menu_cancel(self):
        for answers in ([''], ['""'], [str(self.root / 'missing'), ''], [str(self.game), '']):
            with self.subTest(answers=answers), self.assertRaises(cli.InstallerCancelled):
                self.resolve(answers=answers)

    def test_game_dir_argument_uses_interactive_menu(self):
        selected, count, _ = self.resolve(['--game-dir', self.game], ['2'])
        self.assertEqual(selected, self.helper)
        self.assertEqual(count, 1)

    def test_appid_resolves_directory_and_uses_interactive_menu(self):
        with patch.object(games, 'discover_games', return_value=[{'appid': '12345', 'path': self.game}]):
            selected, count, _ = self.resolve(['--appid', '12345'], ['1'])
        self.assertEqual(selected, self.exe)
        self.assertEqual(count, 1)

    def test_explicit_executable_never_prompts(self):
        for interactive in (True, False):
            with self.subTest(interactive=interactive):
                selected, count, _ = self.resolve(['--exe', self.exe], interactive=interactive)
                self.assertEqual(selected, self.exe)
                self.assertEqual(count, 0)

    def test_noninteractive_ambiguity_never_prompts(self):
        for arguments in (['--game-dir', self.game], ['--appid', '12345']):
            with self.subTest(arguments=arguments), \
                    patch.object(games, 'discover_games', return_value=[{'appid': '12345', 'path': self.game}]), \
                    self.assertRaisesRegex(RuntimeError, 'Multiple possible executables'):
                self.resolve(arguments, interactive=False)

    def test_symlink_and_executable_outside_requested_game_are_rejected(self):
        link = self.game / 'Alias.exe'
        link.symlink_to(self.exe)
        outside = write_executable(self.root / 'Another Game/Other.exe')
        cases = ((['--exe', link], 'symlink'),
                 (['--game-dir', self.game, '--exe', outside], 'outside'))
        for arguments, reason in cases:
            with self.subTest(reason=reason), self.assertRaisesRegex(RuntimeError, reason):
                self.resolve(arguments)
        selected, count, _ = self.resolve(answers=[str(link), str(self.exe)])
        self.assertEqual(selected, self.exe)
        self.assertEqual(count, 2)

    def test_shell_metacharacters_in_pasted_paths_remain_literal(self):
        game = self.root / 'Literal $(echo token) `echo token` ; $HOME'
        exe = write_executable(game / 'Literal.exe')
        with patch('os.system', side_effect=AssertionError('A path must not execute commands')), \
                patch('subprocess.run', side_effect=AssertionError('A path must not execute commands')):
            for quote in ('', '"', "'"):
                with self.subTest(quote=quote):
                    selected, count, _ = self.resolve(answers=[f'{quote}{game}{quote}'])
                    self.assertEqual(selected, exe)
                    self.assertEqual(count, 1)


if __name__ == '__main__':
    unittest.main()
