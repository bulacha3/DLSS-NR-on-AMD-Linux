"""Keep candidate provenance consistent with its real bridge contract."""
import hashlib
import json
from pathlib import Path
import re
import unittest
from dlssnr import upstream

ROOT = Path(__file__).resolve().parents[1]


class CandidateProvenance(unittest.TestCase):
    def test_contract_metadata_matches_source_and_manifest(self):
        p = json.loads((ROOT / 'PROVENANCE.json').read_text())
        m = json.loads((ROOT / 'assets/manifest.json').read_text())
        i = p['integration']
        self.assertEqual(p['installer_version'], m['version'])
        self.assertEqual(p['upstream_mod']['tag'], 'v' + upstream.VERSION)
        self.assertEqual(p['upstream_mod']['setup_sha256'], upstream.SETUP_SHA256)
        self.assertEqual(p['upstream_mod']['setup_bytes'], upstream.SETUP_BYTES)
        self.assertEqual(p['upstream_mod']['payload_sha256'], upstream.PAYLOAD_SHA256)
        self.assertEqual(i['hip_exports'], len(upstream.HIP_IMPORTS))
        magic = re.search(r'#define DLSSNR_HIP_MAGIC (0x[0-9A-Fa-f]+)ULL',
                          (ROOT / 'native/hip_bridge.h').read_text())
        self.assertIsNotNone(magic)
        self.assertEqual(int(i['hip_bridge_magic'], 16), int(magic[1], 16))
        self.assertEqual(i['hip_bridge_abi'], m['hip_bridge_abi'])
        self.assertEqual(i['ordered_abi'], m['ordered_abi'])
        self.assertEqual(i['flag_shader_offset'], upstream.FLAG_SHADER_OFFSET)
        self.assertEqual(i['flag_shader_bytes'], upstream.FLAG_SHADER_BYTES)
        self.assertEqual(i['flag_shader_sha256'], upstream.FLAG_SHADER_SHA256)
        self.assertEqual(i['vkd3d_shader_fnv1'], m['flag_shader_hash'])
        self.assertEqual(i['graphics_wait_shaders'], upstream.GRAPHICS_WAIT_HASHES)
        self.assertEqual(i['linux_sync_settings'], upstream.LINUX_SYNC_SETTINGS)
        self.assertEqual(p['optimized_backend']['automatic_activation'], False)
        self.assertEqual(p['inference_backend']['gpu_validated'], False)

    def test_source_digests_are_current(self):
        p = json.loads((ROOT / 'PROVENANCE.json').read_text())
        for name, digest in p['source_hashes'].items():
            with self.subTest(name=name):
                self.assertEqual(hashlib.sha256((ROOT / name).read_bytes()).hexdigest(), digest)


if __name__ == '__main__':
    unittest.main()
