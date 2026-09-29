"""Keep fresh model extraction headless; never execute the graphical setup."""
import hashlib
import io
import json
import os
from pathlib import Path
import struct
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from dlssnr import conversion,legacy_converter

class LegacyConversion(unittest.TestCase):
    def test_verified_legacy_setup_not_the_gui_and_cache_does_not_download(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);assets=root/'assets';assets.mkdir()
            (assets/'amdhip64_7.dll').write_bytes(b'bridge fixture')
            (assets/'dlssnr_on_amd_setup.exe').write_bytes(b'GUI fixture must not run')
            files={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in assets.iterdir()}
            (assets/'manifest.json').write_text(json.dumps({'mod_version':'0.4.0','files':files}))
            wine=root/'runner/wine';wine.parent.mkdir();wine.touch();(wine.parent/'wineserver').touch()
            nvidia=root/'user.dll';nvidia.write_bytes(b'user fixture')
            input_sha=hashlib.sha256(nvidia.read_bytes()).hexdigest()
            name=b'fixture';start=16+1+len(name)+16
            weights=b'DLSSNRW1'+struct.pack('<II',1,start)+bytes([len(name)])+name+struct.pack('<QQ',0,4)+b'1234'
            calls=[]
            def run(argv,**kw):
                calls.append(argv)
                if argv[0]==str(wine):
                    self.assertEqual(Path(argv[1]).read_bytes(),b'pinned legacy fixture')
                    self.assertEqual(kw['input'],'y\ny\ny\n\n')
                    (kw['cwd']/'dlssnr_on_amd_weights.bin').write_bytes(weights)
                return subprocess.CompletedProcess(argv,0,stdout='ok')
            with patch.object(conversion,'KNOWN_NVIDIA_SHA',input_sha), \
                 patch('urllib.request.urlopen',side_effect=lambda url,timeout:io.BytesIO(b'pinned legacy fixture')) as url, \
                 patch.object(legacy_converter,'inspect_setup') as verify, \
                 patch('subprocess.run',side_effect=run):
                output=conversion.convert_weights(root,nvidia,{'wine':wine},root/'cache')
                self.assertEqual(output.read_bytes(),weights)
                self.assertEqual(url.call_args.args,(legacy_converter.SETUP_URL,))
                verify.assert_called_once_with(b'pinned legacy fixture')
                self.assertEqual(len(calls),3)
                output2=conversion.convert_weights(root,nvidia,{'wine':wine},root/'cache')
                self.assertEqual(output,output2)
                self.assertEqual(url.call_count,1)
                self.assertEqual(len(calls),3)

    @unittest.skipUnless(os.environ.get('DLSSNR_TEST_SETUP_031'),'official legacy converter fixture required')
    def test_real_converter_hash_pin(self):
        data=Path(os.environ['DLSSNR_TEST_SETUP_031']).read_bytes()
        legacy_converter.inspect_setup(data)
        with self.assertRaises(ValueError):legacy_converter.inspect_setup(data[:-1])

if __name__=='__main__':unittest.main()
