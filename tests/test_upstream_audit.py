"""Synthetic binary fixtures for the non-deploying upstream inspector."""
import importlib.util
from pathlib import Path
import struct
import unittest

spec = importlib.util.spec_from_file_location('audit_upstream', Path(__file__).resolve().parents[1] / 'scripts/audit_upstream.py')
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


def fixture():
    b = bytearray(0xa00)
    b[:2] = b'MZ'
    struct.pack_into('<I', b, 60, 0x80)
    b[0x80:0x84] = b'PE\0\0'
    struct.pack_into('<HHIIIHH', b, 0x84, 0x8664, 1, 0, 0, 0, 240, 0x2022)
    struct.pack_into('<H', b, 0x98, 0x20b)
    struct.pack_into('<I', b, 0x98 + 60, 0x200)
    struct.pack_into('<I', b, 0x98 + 108, 16)
    section = 0x98 + 240
    b[section:section + 8] = b'.rdata\0\0'
    struct.pack_into('<IIII', b, section + 8, 0x800, 0x1000, 0x800, 0x200)
    return b


class AuditTests(unittest.TestCase):
    def test_empty_image(self):
        pe = audit.PE(bytes(fixture()))
        self.assertEqual(pe.imports(), {})
        self.assertEqual(pe.resources(), [])
        self.assertEqual(pe.extent, 0xa00)

    def test_all_short_headers_rejected(self):
        b = bytes(fixture())
        for n in (0, 1, 60, 64, 132, 200, 300, 511, len(b)-1):
            with self.subTest(n=n), self.assertRaises(ValueError):
                audit.PE(b[:n])

    def test_mapped_range(self):
        pe = audit.PE(bytes(fixture()))
        self.assertEqual(pe.mapped(0x1040, 8), 0x240)
        for rva, size in ((-1, 1), (0x800, 1), (0x17ff, 2), (0x2000, 1)):
            with self.assertRaises(ValueError):
                pe.mapped(rva, size)

    def test_directories_bound(self):
        b = fixture()
        struct.pack_into('<I', b, 0x98 + 108, 999)
        with self.assertRaises(ValueError):
            audit.PE(bytes(b))

    def test_imports(self):
        b = fixture()
        struct.pack_into('<II', b, 0x98 + 120, 0x1000, 40)
        struct.pack_into('<IIIII', b, 0x200, 0x1100, 0, 0, 0x1080, 0x1100)
        b[0x280:0x28f] = b'amdhip64_7.dll\0\0'
        struct.pack_into('<QQQ', b, 0x300, 0x1140, (1<<63)|5, 0)
        b[0x340:0x34a] = b'\0\0hipInit\0'
        self.assertEqual(audit.PE(bytes(b)).imports(), {'amdhip64_7.dll': ['hipInit', '#5']})

    def test_import_directory_without_terminator(self):
        b = fixture()
        struct.pack_into('<II', b, 0x98 + 120, 0x1000, 20)
        struct.pack_into('<IIIII', b, 0x200, 0x1100, 0, 0, 0x1080, 0x1100)
        b[0x280:0x282] = b'x\0'
        with self.assertRaises(ValueError):
            audit.PE(bytes(b)).imports()

    def test_resource(self):
        b = fixture()
        struct.pack_into('<II', b, 0x98 + 128, 0x1000, 64)
        struct.pack_into('<HH', b, 0x20c, 0, 1)
        struct.pack_into('<II', b, 0x210, 10, 24)
        struct.pack_into('<IIII', b, 0x218, 0x1100, 4, 0, 0)
        b[0x300:0x304] = b'test'
        r = audit.PE(bytes(b)).resources()[0]
        self.assertEqual((r['path'], r['offset'], r['bytes'], r['sha256']), (['10'], 0x300, 4, audit.sha(b'test')))

    def test_resource_cycle(self):
        b = fixture()
        struct.pack_into('<II', b, 0x98 + 128, 0x1000, 64)
        struct.pack_into('<HH', b, 0x20c, 0, 1)
        struct.pack_into('<II', b, 0x210, 10, 0x80000000)
        with self.assertRaises(ValueError):
            audit.PE(bytes(b)).resources()

    def test_legacy_footer(self):
        outer, inner = bytes(fixture()), bytes(fixture())
        config = b'[DLSSNR]\nAsync=0\n'
        data = outer + inner + config + audit.FOOTER + struct.pack('<QQ', len(inner), len(config))
        report, payloads = audit.inventory(data)
        self.assertTrue(report['legacy_footer'])
        self.assertEqual(payloads, [('payload', inner)])
        self.assertEqual(report['payload_bounds'], [len(outer), len(inner), len(config)])


    def test_graphical_setup_embedded_dll_without_footer(self):
        b=fixture(); b.extend(bytes(0x1000))
        section=0x98+240
        struct.pack_into('<I',b,section+8,0x1800)
        struct.pack_into('<I',b,section+16,0x1800)
        inner=bytes(fixture()); b[0x400:0x400+len(inner)]=inner
        config=b'[DlssNrOnAmd]\nStyle=0\nHipDevice=-1\n'
        pos=0x400+len(inner);b[pos:pos+len(config)]=config
        report,payloads=audit.inventory(bytes(b))
        self.assertFalse(report['legacy_footer'])
        self.assertNotIn('unrecognized_container',report)
        self.assertEqual(report['embedded_payloads'],[{'offset':0x400,'bytes':len(inner)}])
        self.assertEqual(payloads,[('embedded-1024',inner)])
        self.assertEqual(report['default_config'],config.decode())

    def test_invalid_footer_bounds(self):
        b = bytes(fixture()) + audit.FOOTER + struct.pack('<QQ', 1<<50, 20)
        with self.assertRaises(ValueError):
            audit.inventory(b)

    def test_pin_rejects_modified_and_truncated(self):
        b = bytes(fixture())
        pin = {'bytes': len(b), 'sha256': audit.sha(b)}
        audit.verify(b, pin)
        for bad in (b[:-1], b + b'x', b'MY' + b[2:]):
            with self.assertRaises(ValueError):
                audit.verify(bad, pin)

    def test_shader_scanner_ignores_false_markers(self):
        self.assertEqual(audit.shaders(b'DXBC' + b'\0'*100), [])
        b = bytearray(48)
        b[:4] = b'DXBC'
        struct.pack_into('<III', b, 20, 1, 48, 1)
        struct.pack_into('<I', b, 32, 36)
        b[36:40] = b'DXIL'
        struct.pack_into('<I', b, 40, 4)
        result = audit.shaders(bytes(b))
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['chunks'], ['DXIL'])
        self.assertEqual(result[0]['sha256'], audit.sha(b))


if __name__ == '__main__':
    unittest.main()
