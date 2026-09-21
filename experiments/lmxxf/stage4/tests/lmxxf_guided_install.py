#!/usr/bin/env python3
"""Exercise guided updates and preserve Steam options without executing them."""
import contextlib
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('guided_stage4',ROOT/'experiments/lmxxf/prepare_stage4.py')
p=importlib.util.module_from_spec(spec);spec.loader.exec_module(p)

class TTY(io.StringIO):
    def isatty(self): return True

class GuidedInstaller(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='lmxxf-guided-')
        self.home=Path(self.temp.name)
        self.base=self.home/'.local/share/dlssnr-linux/experiments/lmxxf-stage4'
        self.game=self.home/'Steam Library/steamapps/common/Sample Game'
        self.mod=self.game/'Retail/.dlssnr-linux'
        self.mod.mkdir(parents=True)
        self.wrapper=self.mod/'launch.sh';self.wrapper.write_text('#!/bin/bash\n')
    def tearDown(self): self.temp.cleanup()
    def test_steam_discovery_uses_libraries_not_assumed_game(self):
        steam=self.home/'.local/share/Steam';(steam/'steamapps').mkdir(parents=True)
        library=self.home/'Steam Library'
        (steam/'steamapps/libraryfolders.vdf').write_text('"libraryfolders" { "1" { "path" "'+str(library)+'" } }')
        result=p.discover_installed_games(self.base,self.home)
        self.assertEqual(result,[{'name':'Sample Game','path':self.game}])
    def test_state_discovers_nonsteam_install(self):
        self.base.mkdir(parents=True)
        (self.base/'activation.json').write_text(json.dumps({'original_launcher':str(self.wrapper)}))
        result=p.discover_installed_games(self.base,self.home)
        self.assertEqual(len(result),1);self.assertEqual(result[0]['path'],self.mod)
    def test_merge_preserves_environment_quotes_and_game_arguments(self):
        entry=self.home/'cache/launch.sh'
        before='A="quoted $HOME; and `literal`" PROTON_OPTISCALER_CONFIG="Inputs.EnableFfxInputs=false;Menu.OverlayMenu=true" '
        after=' %command% -dx12 -option="a b"'
        current=before+p.shlex.quote(str(self.wrapper))+after
        self.assertEqual(p.merge_launch_options(current,entry,self.wrapper),before+p.shlex.quote(str(entry))+after)
        self.assertEqual(p.merge_launch_options('%command% -dx12',entry,self.wrapper),p.shlex.quote(str(entry))+' %command% -dx12')
    def test_invalid_commands_do_not_silently_drop_options(self):
        entry=self.home/'cache/launch.sh'
        for current in ('A=1', '%command% %command%', '"unterminated %command%', '/other/launch.sh %command%', '%command%\nrm -f anything'):
            with self.subTest(current=current), self.assertRaises(ValueError):
                p.merge_launch_options(current,entry,self.wrapper)
    def test_executable_and_quoted_paths_are_supported(self):
        exe=self.mod.parent/'Sample.exe';exe.write_bytes(b'MZ')
        self.assertEqual(p.game_folder(exe),exe.parent)
        self.assertEqual(p.input_path(p.shlex.quote(str(self.game))),self.game)
    def test_guided_update_reuses_cached_model_and_preserves_options(self):
        (self.base/'assets'/p.WEIGHTS_SHA[:16]).mkdir(parents=True)
        current='PROTON_ENABLE_HDR=1 '+p.shlex.quote(str(self.wrapper))+' %command% -dx12'
        calls=[]
        with patch.object(Path,'home',return_value=self.home), patch.object(p,'discover_installed_games',return_value=[{'name':'Sample Game','path':self.game}]), patch.object(p,'weight_manifest',return_value={}), patch.object(p,'find_weights',side_effect=AssertionError('Cached weights should be reused')), patch.object(p,'prepare',side_effect=lambda *a,**k:calls.append((a,k))), patch.object(sys,'stdin',TTY()), patch('builtins.input',side_effect=['1',current]), contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(p.main([]),0)
        self.assertEqual(calls[0][0],(self.game,None))
        self.assertIn('PROTON_ENABLE_HDR=1',calls[0][1]['launch_options'])
        self.assertTrue(calls[0][1]['launch_options'].endswith('%command% -dx12'))
        self.assertIn('Prepared model data found in the shared cache.',output.getvalue())
    def test_cancel_does_not_prepare(self):
        with patch.object(Path,'home',return_value=self.home), patch.object(p,'discover_installed_games',return_value=[]), patch.object(p,'prepare') as prepare, patch.object(sys,'stdin',TTY()), patch('builtins.input',return_value=''), contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(p.main([]),130)
        prepare.assert_not_called()
    def test_existing_command_line_does_not_prompt(self):
        with patch.object(p,'prepare') as prepare, patch('builtins.input',side_effect=AssertionError('CLI must not prompt')), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(p.main(['--game',str(self.game),'--profile']),0)
        self.assertEqual(prepare.call_args.args,(self.game,None))
        self.assertTrue(prepare.call_args.kwargs['profile'])

if __name__=='__main__':unittest.main()
