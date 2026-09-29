"""Installer-only regressions; fake hardware, real per-game file transactions."""
from contextlib import ExitStack, contextmanager, redirect_stdout, redirect_stderr
import argparse
import errno
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, Mock
from dlssnr import cli, deploy, runtime


class FeedbackTests(unittest.TestCase):
    def render(self, result):
        out = io.StringIO()
        args = argparse.Namespace(json=False, command='install', launcher='steam')
        with redirect_stdout(out):
            cli.emit(result, args)
        return out.getvalue()

    def test_hidden_destination_and_installer_role_are_explicit(self):
        text = self.render({'installed': True, 'valid': True, 'exe': '/games/A/bin/x64/Game.exe',
                            'launch_options': "'/games/A/bin/x64/.dlssnr-linux/launch.sh' %command%"})
        self.assertIn('/games/A/bin/x64/.dlssnr-linux', text)
        self.assertIn('Ctrl+H', text)
        self.assertIn('does not install', text)
        self.assertIn('%command%', text)

    def test_failed_install_does_not_offer_launch_options(self):
        text = self.render({'installed': True, 'valid': False, 'pending': True,
                            'launch_options': 'MUST_NOT_APPEAR %command%', 'command_prefix': 'MUST_NOT_APPEAR'})
        self.assertNotIn('MUST_NOT_APPEAR', text)

    def test_dry_run_does_not_offer_launch_options(self):
        text = self.render({'installed': True, 'valid': True, 'dry_run': True,
                            'launch_options': 'MUST_NOT_APPEAR %command%'})
        self.assertNotIn('MUST_NOT_APPEAR', text)

    def test_missing_install_does_not_offer_launch_options(self):
        text = self.render({'installed': False, 'valid': False, 'launch_options': 'MUST_NOT_APPEAR'})
        self.assertNotIn('MUST_NOT_APPEAR', text)

    def test_unsupported_gpu_identifies_hardware_not_just_distro(self):
        with self.assertRaisesRegex(RuntimeError, 'gfx1033.*SteamOS'):
            cli.select_gpu([{'index': 0, 'name': 'Handheld GPU', 'arch': 'gfx1033'}], None, False)

    def test_mint_missing_venv_has_actionable_message(self):
        with patch.object(runtime.subprocess, 'run', return_value=Mock(returncode=1)), \
             patch.object(runtime.platform, 'freedesktop_os_release', return_value={'ID':'linuxmint'}):
            with self.assertRaisesRegex(RuntimeError, 'python3-venv.*No AMD wheel downloaded'):
                runtime._check_venv_support()

    def test_steamos_missing_venv_does_not_request_readonly_disable(self):
        with patch.object(runtime.subprocess, 'run', return_value=Mock(returncode=1)), \
             patch.object(runtime.platform, 'freedesktop_os_release', return_value={'ID':'steamos'}):
            with self.assertRaises(RuntimeError) as raised:
                runtime._check_venv_support()
            self.assertIn('keep the system read-only', str(raised.exception))
            self.assertNotIn('steamos-readonly disable', str(raised.exception))

    def test_venv_preflight_is_read_only(self):
        with patch.object(runtime.subprocess, 'run', return_value=Mock(returncode=0)) as run:
            runtime._check_venv_support()
            self.assertEqual(run.call_args.args[0][1:], ['-I', '-c', 'import venv, ensurepip'])


class TransactionFeedback(unittest.TestCase):
    def run_install(self, parent, *, fault=None, dry_run=False):
        # No real executables/libraries are loaded. Deployment and journal checks are real.
        parent=Path(parent)
        exe=parent/'library with spaces/Game/bin/x64/Game.exe';exe.parent.mkdir(parents=True)
        exe.write_bytes(b'fake game fixture')
        weights=parent/'weights.bin';weights.write_bytes(b'DLSSNRW1fixture')
        lib=parent/'hip.so';lib.write_bytes(b'fake HIP fixture')
        package=parent/'package';(package/'assets').mkdir(parents=True)
        hashes={}
        for name in deploy.DLLS+(deploy.BRIDGE,):
            raw=('fake component '+name).encode();(package/'assets'/name).write_bytes(raw)
            hashes[name]=hashlib.sha256(raw).hexdigest()
        manifest={'files':hashes, 'version':'fixture', 'mod_version':'fixture', 'graphics_wait_supported':True}
        (package/'assets/manifest.json').write_text(json.dumps(manifest))
        @contextmanager
        def prepared(*args, **kwargs):yield package
        out,err=io.StringIO(),io.StringIO()
        options=['install','--exe',str(exe),'--runner',str(parent/'runner'),'--confirm-runner',
                 '--weights',str(weights),'--accept-risk','--launcher','steam','--launch-options','%command%']
        if dry_run:options.append('--dry-run')
        with ExitStack() as stack:
            for cm in (redirect_stdout(out),redirect_stderr(err),
                patch.dict(os.environ,{'XDG_DATA_HOME':str(parent/'data')}),
                patch.object(cli.sys.stdin,'isatty',return_value=False),
                patch.object(cli,'PACKAGE_ROOT',package),
                patch.object(cli.assets,'verify_assets',return_value=manifest),
                patch.object(cli.assets,'require_deployable'),
                patch.object(cli.assets,'validate_weights',return_value={'bytes':weights.stat().st_size}),
                patch.object(cli,'check_host',return_value={'system':'Linux'}),
                patch.object(cli.games,'select_executable',return_value=exe),
                patch.object(cli.games,'inspect_game',return_value={'exe':exe,'dx12':True,'version_loader':True,'anti_cheat_evidence':[],'fsr_evidence':['FSR']}),
                patch.object(cli,'resolve_proton',return_value={'root':parent/'runner'}),
                patch.object(cli,'ensure_runtime',return_value={'library':str(lib),'devices':[{'index':0,'name':'Test AMD','arch':'gfx1201'}]}),
                patch.object(cli,'readonly_runtime',return_value={'library':str(lib),'devices':[{'index':0,'name':'Test AMD','arch':'gfx1201'}]}),
                patch.object(cli.upstream,'prepared_package',prepared),
                patch.object(cli.lmxxf,'launch_options',return_value=str(exe.parent/deploy.STORE/'launch.sh')+' %command%'),
                patch.object(deploy,'running_game',return_value=False)):
                stack.enter_context(cm)
            if fault is not None:stack.enter_context(patch.object(cli.deploy,'install_game',side_effect=fault))
            code=cli.main(options)
        return code,out.getvalue(),err.getvalue(),exe

    def test_install_creates_hidden_folder_before_any_game_launch(self):
        with tempfile.TemporaryDirectory() as tmp:
            code,out,err,exe=self.run_install(tmp)
            self.assertEqual(code,0,err)
            self.assertTrue((exe.parent/deploy.STORE/'launch.sh').is_file())
            self.assertTrue((exe.parent/deploy.STORE/'manifest.json').is_file())
            self.assertIn('created by the installer',out)

    def test_dry_run_does_not_create_mod_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            code,out,err,exe=self.run_install(tmp,dry_run=True)
            self.assertEqual(code,0,err)
            self.assertFalse((exe.parent/deploy.STORE).exists())
            self.assertNotIn('%command%',out)

    def test_read_only_game_directory_has_phase_and_no_launch_command(self):
        with tempfile.TemporaryDirectory() as tmp:
            code,out,err,exe=self.run_install(tmp,fault=OSError(errno.EROFS,'Read-only file system'))
            self.assertEqual(code,2)
            self.assertIn('Error during game file installation',err)
            self.assertIn('Read-only file system',err)
            self.assertNotIn('%command%',out)
            self.assertFalse((exe.parent/deploy.STORE).exists())

    def test_failed_final_verification_returns_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            code,out,err,exe=self.run_install(tmp,fault=lambda *a,**k:{'installed':True,'valid':False,'pending':True,'notes':['Fixture cache mismatch']})
            self.assertEqual(code,2)
            self.assertIn('Fixture cache mismatch',err)
            self.assertNotIn('%command%',out)


if __name__=='__main__':unittest.main()
