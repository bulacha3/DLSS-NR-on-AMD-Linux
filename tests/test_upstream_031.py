"""Compatibility checks for the pinned 0.3.1 payload and Linux wait settings."""
import json
import os
from pathlib import Path
import struct
import subprocess
import tempfile
import unittest

from dlssnr import assets, deploy, upstream
from dlssnr.games import pe_info

ROOT = Path(__file__).resolve().parents[1]


class LinuxSyncConfigurationTests(unittest.TestCase):
    def test_install_and_upgrade_override_unsupported_waits(self):
        original = (b'[DlssNrOnAmd]\r\nEnabled=0\r\nPreUpscale=0\r\n'
                    b'Scale=0.05\r\nSpinDraw = 1 ; keep comment\r\n'
                    b'CpuWait=2\r\nAsync=1\r\n[Other]\r\nSpinDraw=1\r\n')
        for update in (False, True):
            with self.subTest(update=update):
                result = deploy._ini(original, 2, update=update).decode()
                self.assertIn(f'SpinDraw = {1 if update else 0} ; keep comment\r\n', result)
                self.assertIn('CpuWait=0\r\n', result)
                self.assertIn('Async=0\r\n', result)
                self.assertIn('[Other]\r\nSpinDraw=1\r\n', result)
                self.assertIn('Scale=0.05\r\n', result)
                if update:
                    self.assertIn('Enabled=0\r\n', result)
                    self.assertIn('PreUpscale=0\r\n', result)
        added = deploy._ini(b'', 0).decode()
        for name, value in upstream.LINUX_SYNC_SETTINGS.items():
            self.assertIn(f'{name}={value}\n', added)

    def test_duplicate_wait_keys_are_rejected(self):
        with self.assertRaisesRegex(RuntimeError, 'duplicate INI key'):
            deploy._ini(b'[DlssNrOnAmd]\nSpinDraw=0\nspindraw=1\n', 0, update=True)

    def test_old_or_incomplete_contract_cannot_be_staged(self):
        manifest = json.loads((ROOT / 'assets/manifest.json').read_text())
        manifest['files'] = {name: '0' * 64 for name in upstream.COMPONENTS}
        assets.require_deployable(manifest)
        for change in ({'mod_version': '0.3.0'}, {'linux_sync_settings': {}},
                       {'graphics_wait_supported': False}, {'graphics_wait_shaders': {}},
                       {'linux_sync_settings': {'Async': '0', 'SpinDraw': '1', 'CpuWait': '0'}}):
            with self.subTest(change=change), self.assertRaises(RuntimeError):
                assets.require_deployable(dict(manifest, **change))

    def test_saved_method_and_explicit_override(self):
        # Missing keys in an older 0.3.0 installation adopt the new default.
        for data in (b'', b'[DlssNrOnAmd]\nPreUpscale=0\n[Other]\nSpinDraw=0\n'):
            self.assertEqual(deploy._select_wait_method(data), 'compute')
        saved = b'[dLsSnRoNaMd]\r\n  spindraw = 0 ; previous choice\r\nPreUpscale=0\r\n'
        self.assertEqual(deploy._select_wait_method(saved), 'compute')
        updated = deploy._ini(saved, 0, update=True).decode()
        self.assertIn('spindraw = 0 ; previous choice', updated)
        self.assertIn('PreUpscale=0', updated)
        override = deploy._ini(saved, 0, update=True, wait_method='graphics').decode()
        self.assertIn('spindraw = 1 ; previous choice', override)
        self.assertEqual(deploy._ini(override.encode(), 0, update=True).decode(), override)
        invalid = b'[DlssNrOnAmd]\nSpinDraw=invalid\n'
        with self.assertRaisesRegex(RuntimeError, 'Unrecognized SpinDraw'):
            deploy._ini(invalid, 0, update=True)
        self.assertIn(b'SpinDraw=1', deploy._ini(invalid, 0, update=True, wait_method='graphics'))


@unittest.skipUnless(os.environ.get('DLSSNR_TEST_SETUP'), 'official 0.3.1 fixture not supplied')
class OfficialPayloadTests(unittest.TestCase):
    def payload(self):
        data = upstream.read_setup(os.environ['DLSSNR_TEST_SETUP'])
        return upstream.inspect_setup(data)[0]

    def test_delay_loaded_hip_imports_match_the_trampoline_contract(self):
        payload = self.payload()
        with tempfile.TemporaryDirectory() as tmp:
            dll = Path(tmp) / 'version.dll'; dll.write_bytes(payload)
            sections = pe_info(dll)['sections']
        def offset(rva):
            section = next(s for s in sections
                           if 0 <= rva-s['virtual_address'] < s['raw_size'])
            return section['raw_offset'] + rva-section['virtual_address']
        def name(rva):
            start = offset(rva)
            return payload[start:payload.index(0, start)].decode('ascii')
        nt = struct.unpack_from('<I', payload, 0x3c)[0]
        rva, size = struct.unpack_from('<II', payload, nt+24+112+13*8)
        found = set()
        for pos in range(offset(rva), offset(rva)+size, 32):
            attributes, module, _, _, imports, *_ = struct.unpack_from('<8I', payload, pos)
            if not attributes:
                break
            self.assertEqual(attributes, 1)
            if name(module).lower() != 'amdhip64_7.dll':
                continue
            pos = offset(imports)
            while (thunk := struct.unpack_from('<Q', payload, pos)[0]):
                self.assertLess(thunk, 1 << 63)  # named, not ordinal-only
                found.add(name(thunk+2)); pos += 8
        self.assertEqual(found, upstream.HIP_IMPORTS)

    @unittest.skipUnless(os.environ.get('DLSSNR_TEST_VKD3D_SOURCE'), 'patched vkd3d source not supplied')
    def test_actual_upstream_compute_and_graphics_recorder_with_the_bridge(self):
        payload = self.payload()
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            code = tmp / 'recording.bin'
            # Reviewed position-independent function: only RIP-relative globals
            # and mock COM calls. No upstream DLL initialization is executed.
            dll = tmp / 'version.dll'; dll.write_bytes(payload)
            sections = pe_info(dll)['sections']
            def at(rva, size):
                section = next(s for s in sections if 0 <= rva-s['virtual_address']
                               and rva-s['virtual_address']+size <= s['raw_size'])
                off = section['raw_offset'] + rva-section['virtual_address']
                return payload[off:off+size]
            code.write_bytes(at(0x17980, 0x180a6-0x17980) +
                             at(0x6cd40, 16) + at(0x6cd58, 16))
            binary = tmp / 'recording-contract'
            include = Path(os.environ['DLSSNR_TEST_VKD3D_SOURCE']).resolve() / 'libs/vkd3d'
            subprocess.run(['gcc', '-std=gnu11', '-O1', '-g',
                            '-fsanitize=address,undefined', '-fno-omit-frame-pointer',
                            '-I', str(include), str(ROOT/'tests/upstream_recording_contract.c'),
                            '-o', str(binary)], check=True, timeout=60)
            env = dict(os.environ, ASAN_OPTIONS='detect_leaks=0')
            result = subprocess.run([str(binary), str(code)], check=True, env=env,
                                    capture_output=True, text=True, timeout=15)
            self.assertIn('1/64/4000 waits', result.stdout)


if __name__ == '__main__':
    unittest.main()
