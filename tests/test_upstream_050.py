"""Version and staged-payload contract, not a GPU performance test."""
from pathlib import Path
import hashlib
import json
import unittest
from dlssnr import upstream, deploy

ROOT=Path(__file__).resolve().parents[1]

class Release050(unittest.TestCase):
    def test_current_version_consistent(self):
        manifest=json.loads((ROOT/'assets/manifest.json').read_text())
        self.assertEqual(upstream.VERSION,'0.5.0')
        self.assertEqual(manifest['mod_version'],'0.5.0')
        self.assertEqual(manifest['version'],'0.5.0')
        self.assertIn('/v0.5.0/',upstream.SETUP_URL)
        self.assertEqual(upstream.SETUP_BYTES,41864192)
        self.assertEqual(upstream.PAYLOAD_BYTES,38703616)

    def test_preserve_settings_on_update(self):
        config=b'[DlssNrOnAmd]\nQuality=reference\nOverlayKey=F8\nScale=0.04\nLocalStructure=0.3\n'
        out=deploy._ini(config,0,update=True)
        for line in config.splitlines()[1:]:self.assertIn(line+b'\n',out)
        self.assertEqual(deploy._ini(out,0,update=True),out)

    def test_amd_handheld_support_not_silently_enabled(self):
        from dlssnr import cli
        self.assertEqual(cli.TARGETS,frozenset(('gfx1100','gfx1101','gfx1102','gfx1200','gfx1201')))

if __name__=='__main__':unittest.main()
