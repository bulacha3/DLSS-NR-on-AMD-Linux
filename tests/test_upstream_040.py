"""Current pinned upstream extraction, defaults, version fence and recording contracts."""
import json
import os
from pathlib import Path
import struct
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from dlssnr import upstream, legacy_converter, assets, deploy, lmxxf

ROOT=Path(__file__).resolve().parents[1]

class CandidatePolicyTests(unittest.TestCase):
    def test_legacy_backend_never_activates_on_new_payload(self):
        for arch in ('gfx1100','gfx1101','gfx1102','gfx1200','gfx1201'):
            self.assertFalse(lmxxf.supported({'arch':arch}))
        with patch.object(upstream,'VERSION','0.3.1'):
            self.assertTrue(lmxxf.supported({'arch':'gfx1201'}))

    def test_new_defaults_preserve_existing_visual_choices(self):
        data=b'[DlssNrOnAmd]\nStyle=2\nToneCurve=aces\nToneLift=0.15\nUseGameExposure=0\nLocalTone=0.7\nPollSpacing=37\n'
        out=deploy._ini(data,0,update=True).decode()
        for s in ('Style=2','ToneCurve=aces','ToneLift=0.15','UseGameExposure=0','LocalTone=0.7','PollSpacing=0'):
            self.assertIn(s+'\n',out)
        self.assertIn('Style=0\n',deploy._ini(b'',0).decode())
        self.assertIn('ToneCurve=reinhard\n',deploy._ini(b'',0).decode())
        self.assertEqual(deploy._ini(out.encode(),0,update=True),out.encode())

    def test_old_bridge_contract_is_rejected(self):
        m=json.loads((ROOT/'assets/manifest.json').read_text())
        m['files']={name:'0'*64 for name in upstream.COMPONENTS}
        assets.require_deployable(m)
        for delta in ({'hip_bridge_abi':2},{'mod_version':'0.3.1'},{'linux_sync_settings':{'Async':'0','SpinDraw':'0','CpuWait':'0'}}):
            with self.subTest(delta=delta),self.assertRaises(RuntimeError):
                assets.require_deployable(dict(m,**delta))

@unittest.skipUnless(os.environ.get('DLSSNR_TEST_SETUP'),'official current fixture required')
class Official040Tests(unittest.TestCase):
    def payload(self):
        return upstream.inspect_setup(upstream.read_setup(os.environ['DLSSNR_TEST_SETUP']))[0]

    def test_exact_container_and_configuration(self):
        data=Path(os.environ['DLSSNR_TEST_SETUP']).read_bytes()
        payload,config,report=upstream.inspect_setup(data)
        self.assertEqual(len(payload),upstream.PAYLOAD_BYTES)
        self.assertEqual(config,upstream.DEFAULT_CONFIG)
        self.assertFalse(report['gameplay_verified'])
        self.assertFalse(report['payload_modified'])
        for altered in (data[:-1],data+b'x',data[:100]+bytes([data[100]^1])+data[101:]):
            with self.assertRaises(ValueError): upstream.inspect_setup(altered)

    def test_delay_imports_exactly_match_the_bridge(self):
        import importlib.util
        spec=importlib.util.spec_from_file_location('audit',ROOT/'scripts/audit_upstream.py')
        audit=importlib.util.module_from_spec(spec);spec.loader.exec_module(audit)
        pe=audit.PE(self.payload());rva,size=pe.dirs[13];found=set()
        for off in range(0,size,32):
            flags,module,_,_,table,*_=pe.unpack('<8I',pe.mapped(rva+off,32))
            if not flags:break
            self.assertEqual(flags,1)
            if pe.text(module).lower()!='amdhip64_7.dll':continue
            for j in range(1024):
                value=pe.unpack('<Q',pe.mapped(table+8*j,8))[0]
                if not value:break
                self.assertLess(value,1<<63)
                found.add(pe.text(value+2))
        self.assertEqual(found,upstream.HIP_IMPORTS)
        self.assertEqual(found-legacy_converter.HIP_IMPORTS,
            {'hipGetDevice','hipOccupancyMaxActiveBlocksPerMultiprocessor',
             'hipDeviceGetStreamPriorityRange','hipStreamCreateWithPriority','hipStreamDestroy'})

    @unittest.skipUnless(os.environ.get('DLSSNR_TEST_VKD3D_SOURCE'),'patched vkd3d source required')
    def test_actual_current_recorder_with_ordered_bridge(self):
        import importlib.util
        spec=importlib.util.spec_from_file_location('audit',ROOT/'scripts/audit_upstream.py')
        audit=importlib.util.module_from_spec(spec);spec.loader.exec_module(audit)
        payload=self.payload();pe=audit.PE(payload)
        def at(rva,size):return payload[pe.mapped(rva,size):pe.mapped(rva,size)+size]
        with tempfile.TemporaryDirectory() as tmp:
            tmp=Path(tmp);code=tmp/'recording.bin'
            code.write_bytes(at(0x19b90,0x726)+at(0x834f0,16)+at(0x83508,16))
            binary=tmp/'recording-contract'
            include=Path(os.environ['DLSSNR_TEST_VKD3D_SOURCE']).resolve()/'libs/vkd3d'
            subprocess.run(['gcc','-std=gnu11','-O1','-g','-DDLSSNR_RECORD_050',
                '-fsanitize=address,undefined','-fno-omit-frame-pointer','-I',str(include),
                str(ROOT/'tests/upstream_recording_contract.c'),'-o',str(binary)],check=True,timeout=60)
            result=subprocess.run([str(binary),str(code)],check=True,capture_output=True,
                text=True,timeout=15,env=dict(os.environ,ASAN_OPTIONS='detect_leaks=0'))
            self.assertIn('1/64/4000 waits',result.stdout)

if __name__=='__main__':unittest.main()
