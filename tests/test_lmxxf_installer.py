"""Installer transaction/order contracts; no Wine, network or GPU required."""
from contextlib import ExitStack, redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

from dlssnr import assets, cli, conversion, deploy, games, lmxxf, runtime, upstream


class UnifiedFlow(unittest.TestCase):
    def run_flow(self, *, preparation_error=None, activation_error=None, arch='gfx1201', existing=False):
        with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
            root=Path(directory);exe=root/'Game.exe';exe.write_bytes(b'fixture')
            weights=root/'weights.bin';weights.write_bytes(b'fixture')
            order=[];out=io.StringIO();err=io.StringIO()
            stack.enter_context(redirect_stdout(out));stack.enter_context(redirect_stderr(err))
            stack.enter_context(patch.object(cli.sys.stdin,'isatty',return_value=False))
            stack.enter_context(patch.object(assets,'verify_assets',return_value={}))
            stack.enter_context(patch.object(assets,'require_deployable'))
            stack.enter_context(patch.object(assets,'validate_weights',return_value={}))
            stack.enter_context(patch.object(cli,'check_host',return_value={}))
            stack.enter_context(patch.object(cli,'resolve_exe',return_value=exe))
            stack.enter_context(patch.object(games,'inspect_game',return_value={
                'exe':exe,'dx12':True,'fsr_evidence':['FSR3'],'anti_cheat_evidence':[], 'version_loader':True}))
            runner=stack.enter_context(patch.object(cli,'resolve_proton',return_value={'root':root/'runner'}))
            stack.enter_context(patch.object(cli,'confirm_runner',side_effect=lambda a,p,i:p))
            stack.enter_context(patch.object(deploy,'running_game',return_value=False))
            rt={'library':str(root/'HIP.so'),'devices':[{'name':'AMD test GPU','arch':arch,'index':0}]}
            stack.enter_context(patch.object(cli,'ensure_runtime',return_value=rt))
            stack.enter_context(patch.object(runtime,'probe_runtime',return_value=rt))
            staged=stack.enter_context(patch.object(upstream,'prepared_package'))
            staged.return_value.__enter__.return_value=root
            stack.enter_context(patch.object(lmxxf,'existing_runtime',return_value={
                'DLSSNR_HIP_LIBRARY':rt['library'],'VKD3D_FILTER_DEVICE_NAME':'AMD test GPU'} if existing else None))
            def prepare(*a,**k):
                order.append('prepare')
                if preparation_error:raise preparation_error
                return root/'prepared'
            stack.enter_context(patch.object(cli,'candidate_weights',side_effect=prepare))
            stack.enter_context(patch.object(lmxxf,'launch_options',side_effect=lambda *a, **k:
                'OPT=1 /base/launch.sh %command% -dx12' if k.get('original_backend') else
                'OPT=1 /candidate/launch.sh %command% -dx12'))
            base={'installed':True,'valid':True,'pending':False,'launch_options':'/base/launch.sh %command%'}
            stack.enter_context(patch.object(deploy,'status_game',return_value=base))
            def install(*a,**k):order.append('base');return dict(base)
            deployed=stack.enter_context(patch.object(deploy,'install_game',side_effect=install))
            def activate(*a,**k):
                order.append('activate')
                if activation_error:raise activation_error
                return {'backend':'lmxxf','launch_options':'OPT=1 /candidate/launch.sh %command% -dx12','command_prefix':'/candidate/launch.sh'}
            active=stack.enter_context(patch.object(lmxxf,'activate',side_effect=activate))
            args=['install','--exe',str(exe),'--accept-risk','--confirm-runner','--data-dir',str(root/'data')]
            if not existing:args+=['--weights',str(weights)]
            rc=cli.main(args)
            return rc,out.getvalue(),err.getvalue(),order,runner.call_count,deployed.call_count,active.call_count

    def test_fresh_prepares_before_base_and_prints_only_final_launch_options(self):
        rc,out,err,order,*_=self.run_flow()
        self.assertEqual((rc,order),(0,['prepare','base','activate']),err)
        self.assertNotIn('/base/launch.sh',out)
        self.assertEqual(out.count('OPT=1 /candidate/launch.sh %command% -dx12'),1)

    def test_conversion_failure_leaves_game_untouched(self):
        rc,_,err,order,_,deployed,active=self.run_flow(preparation_error=RuntimeError('bad model'))
        self.assertEqual((rc,order,deployed,active),(2,['prepare'],0,0));self.assertIn('bad model',err)

    def test_activation_failure_reports_valid_base_without_false_success(self):
        rc,out,_,order,*_=self.run_flow(activation_error=RuntimeError('compiler failure'))
        self.assertEqual((rc,order),(2,['prepare','base','activate']))
        self.assertIn('/base/launch.sh %command%',out);self.assertIn('not activated',out)
        self.assertIn('OPT=1 /base/launch.sh %command% -dx12', out)
        self.assertNotIn('/candidate/launch.sh', out)
        self.assertNotIn('Optimized Linux backend installed',out)

    def test_existing_install_reuses_configuration_without_runner_or_base_update(self):
        rc,_,err,order,runner,deployed,_=self.run_flow(existing=True)
        self.assertEqual((rc,order,runner,deployed),(0,['prepare','activate'],0,0),err)

    def test_other_supported_gpu_keeps_original_backend(self):
        rc,out,err,order,*_=self.run_flow(arch='gfx1100')
        self.assertEqual((rc,order),(0,['base']),err)
        self.assertIn('original backend',out)


class ModelPreparation(unittest.TestCase):
    def test_complete_cache_reused_without_dll_or_numpy(self):
        with patch.object(lmxxf,'preflight'),patch.object(lmxxf,'backend',return_value=(Mock(),Path('/package'))),patch.object(lmxxf,'cached_weights',return_value=Path('/cache/prepared')),patch.object(lmxxf,'numpy_python') as numpy:
            self.assertEqual(lmxxf.prepare_weights('/package','/cache'),Path('/cache/prepared'))
            numpy.assert_not_called()

    def test_wrong_dll_hash_rejected_before_interpreter_or_converter(self):
        with tempfile.TemporaryDirectory() as temporary:
            dll=Path(temporary)/'model.dll';dll.write_bytes(b'wrong DLL')
            with patch.object(lmxxf,'preflight'),patch.object(lmxxf,'backend',return_value=(Mock(),Path('/package'))),patch.object(lmxxf,'cached_weights',return_value=None),patch.object(lmxxf,'numpy_python') as numpy:
                with self.assertRaisesRegex(RuntimeError,'does not match'):
                    lmxxf.prepare_weights('/package',temporary,dll)
                numpy.assert_not_called()

    def test_system_numpy_reuse_does_not_create_environment_or_download(self):
        with tempfile.TemporaryDirectory() as temporary,patch.object(lmxxf,'_numpy_works',return_value=True),patch.object(lmxxf.urllib.request,'urlopen') as download:
            lmxxf.numpy_python(temporary)
            self.assertEqual(list(Path(temporary).iterdir()),[]);download.assert_not_called()

    def test_unmanaged_private_python_is_never_executed(self):
        with tempfile.TemporaryDirectory() as temporary:
            env=Path(temporary)/'model-python';(env/'bin').mkdir(parents=True)
            (env/'bin/python').write_bytes(b'not a trusted interpreter')
            with patch.object(lmxxf,'_numpy_works',return_value=False) as probe:
                with self.assertRaises(RuntimeError):lmxxf.numpy_python(temporary)
                self.assertEqual(probe.call_count,1)

    def test_corrupt_download_never_reaches_pip(self):
        with tempfile.TemporaryDirectory() as temporary:
            with patch.object(lmxxf,'_numpy_works',return_value=False),patch.object(lmxxf.subprocess,'run',return_value=subprocess.CompletedProcess([],0)) as run,patch.object(lmxxf.urllib.request,'urlopen') as download:
                download.return_value.__enter__.return_value.read.return_value=b'corrupted wheel'
                with self.assertRaisesRegex(RuntimeError,'checksum'):lmxxf.numpy_python(temporary,quiet=True)
                self.assertEqual(run.call_count,1)
                self.assertIn('venv',run.call_args.args[0])

    def test_converter_sources_match_reviewed_pins(self):
        root=Path(__file__).resolve().parents[1]/'experiments/lmxxf'
        for name,digest in lmxxf.CONVERTER_HASHES.items():
            self.assertEqual(assets.sha256(root/name),digest)


if __name__=='__main__':unittest.main()
