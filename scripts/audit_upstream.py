#!/usr/bin/env python3
"""Static audit of pinned upstream installers; never execute or deploy a payload.

PE structures follow Microsoft's PE/COFF specification. This inventory is NOT
an ABI, synchronization, numerical, image-quality or performance validation.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import re
import struct
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
FOOTER = b'DLSSNR-SETUP-01\0'


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class PE:
    """Bounded PE32/PE32+ metadata reader; no code loading."""
    def __init__(self, data: bytes):
        self.data = data
        if self.take(0, 2) != b'MZ':
            raise ValueError('Not a PE image')
        header = self.unpack('<I', 60)[0]
        if self.take(header, 4) != b'PE\0\0':
            raise ValueError('Invalid PE signature')
        self.machine, count, _, _, _, optlen, self.flags = self.unpack('<HHIIIHH', header + 4)
        opt = header + 24
        magic = self.unpack('<H', opt)[0]
        if magic not in (0x10b, 0x20b) or not 1 <= count <= 96:
            raise ValueError('Unsupported PE header')
        self.pointer = 8 if magic == 0x20b else 4
        directories = 112 if self.pointer == 8 else 96
        if optlen < directories:
            raise ValueError('Truncated optional header')
        self.take(opt, optlen)
        self.headers = self.unpack('<I', opt + 60)[0]
        if self.headers < opt + optlen + count * 40:
            raise ValueError('Section table outside headers')
        self.take(0, self.headers)
        n = self.unpack('<I', opt + directories - 4)[0]
        if n > (optlen - directories) // 8:
            raise ValueError('Data directories outside header')
        self.dirs = [self.unpack('<II', opt + directories + i * 8) for i in range(n)]
        self.sections = []
        self.extent = self.headers
        for i in range(count):
            s = opt + optlen + i * 40
            name = self.take(s, 8).rstrip(b'\0').decode('ascii', errors='replace')
            virtual_size, rva, size, offset = self.unpack('<IIII', s + 8)
            if size:
                self.take(offset, size)
                self.extent = max(self.extent, offset + size)
            self.sections.append(dict(name=name, rva=rva, bytes=size, offset=offset,
                                      virtual_bytes=virtual_size))

    def take(self, offset: int, size: int) -> bytes:
        if offset < 0 or size < 0 or offset > len(self.data) - size:
            raise ValueError('PE range outside file')
        return self.data[offset:offset + size]

    def unpack(self, fmt: str, offset: int) -> tuple:
        return struct.unpack(fmt, self.take(offset, struct.calcsize(fmt)))

    def mapped(self, rva: int, size: int = 1) -> int:
        if 0 <= rva and rva + size <= self.headers:
            self.take(rva, size)
            return rva
        matches = [s['offset'] + rva - s['rva'] for s in self.sections
                   if s['rva'] <= rva and rva + size <= s['rva'] + s['bytes']]
        if len(matches) != 1:
            raise ValueError('Unmapped or ambiguous PE RVA')
        self.take(matches[0], size)
        return matches[0]

    def text(self, rva: int) -> str:
        out = bytearray()
        for i in range(1024):
            b = self.data[self.mapped(rva + i)]
            if not b:
                return out.decode('ascii')
            out.append(b)
        raise ValueError('Unterminated PE string')

    def imports(self) -> dict:
        if len(self.dirs) < 2 or not self.dirs[1][0]:
            return {}
        rva, size = self.dirs[1]
        result = {}
        for i in range(min(size // 20, 1024)):
            entry = self.unpack('<IIIII', self.mapped(rva + i * 20, 20))
            if not any(entry):
                return result
            lookup, _, _, name, address = entry
            symbols = []
            for j in range(65536):
                pos = self.mapped((lookup or address) + j * self.pointer, self.pointer)
                value = self.unpack('<Q' if self.pointer == 8 else '<I', pos)[0]
                if not value:
                    break
                if value & (1 << (self.pointer * 8 - 1)):
                    symbols.append('#' + str(value & 65535))
                else:
                    symbols.append(self.text(value + 2))
            else:
                raise ValueError('Unterminated import lookup')
            dll = self.text(name)
            if dll in result:
                raise ValueError('Duplicate import descriptor')
            result[dll] = symbols
        raise ValueError('Unterminated import directory')

    def delayed_imports(self) -> dict:
        if len(self.dirs) <= 13 or not self.dirs[13][0]:
            return {}
        rva, size = self.dirs[13]
        result = {}
        for i in range(min(size // 32, 1024)):
            entry = self.unpack('<8I', self.mapped(rva + 32 * i, 32))
            if not any(entry):
                return result
            flags, name, _, _, table, _, _, _ = entry
            if flags != 1:
                raise ValueError('Only RVA-based delay imports are supported')
            symbols = []
            for j in range(65536):
                value = self.unpack('<Q' if self.pointer == 8 else '<I',
                    self.mapped(table + j * self.pointer, self.pointer))[0]
                if not value:
                    break
                if value & (1 << (8 * self.pointer - 1)):
                    symbols.append('#' + str(value & 65535))
                else:
                    symbols.append(self.text(value + 2))
            else:
                raise ValueError('Unterminated delay-import table')
            dll = self.text(name)
            if dll in result:
                raise ValueError('Duplicate delay-import descriptor')
            result[dll] = symbols
        raise ValueError('Unterminated delay-import directory')

    def resources(self) -> list:
        if len(self.dirs) < 3 or not self.dirs[2][0]:
            return []
        base, length = self.dirs[2]
        visited, leaves = set(), []

        def at(off, size):
            if off < 0 or off + size > length:
                raise ValueError('Resource metadata outside directory')
            return self.mapped(base + off, size)

        def walk(off, path):
            if off in visited or len(path) > 8 or len(visited) >= 4096:
                raise ValueError('Cyclic or oversized resource directory')
            visited.add(off)
            count = sum(self.unpack('<HH', at(off + 12, 4)))
            if count > 4096:
                raise ValueError('Too many resources')
            for i in range(count):
                name, target = self.unpack('<II', at(off + 16 + i * 8, 8))
                if name & 0x80000000:
                    p = name & 0x7fffffff
                    size = self.unpack('<H', at(p, 2))[0] * 2
                    label = self.take(at(p + 2, size), size).decode('utf-16-le')
                else:
                    label = str(name)
                route = path + [label]
                if target & 0x80000000:
                    walk(target & 0x7fffffff, route)
                else:
                    rva, size, codepage, _ = self.unpack('<IIII', at(target, 16))
                    p = self.mapped(rva, size)
                    leaves.append(dict(path=route, offset=p, bytes=size, codepage=codepage,
                                       sha256=sha(self.take(p, size))))
        walk(0, [])
        return leaves


def shaders(data: bytes) -> list:
    result = []
    for match in re.finditer(b'DXBC', data):
        off = match.start()
        if off + 32 > len(data):
            continue
        version, size, count = struct.unpack_from('<III', data, off + 20)
        if version != 1 or not 0 < count <= 64 or not 32 + count * 4 <= size <= len(data) - off:
            continue
        chunks = []
        for i in range(count):
            chunk = struct.unpack_from('<I', data, off + 32 + i * 4)[0]
            if chunk < 32 + count * 4 or chunk + 8 > size:
                break
            length = struct.unpack_from('<I', data, off + chunk + 4)[0]
            if chunk + 8 + length > size:
                break
            chunks.append(data[off + chunk:off + chunk + 4].decode('ascii', errors='replace'))
        else:
            blob = data[off:off + size]
            fnv = 0xcbf29ce484222325
            for b in blob:
                fnv = ((fnv * 0x100000001b3) & 0xffffffffffffffff) ^ b
            result.append(dict(offset=off, bytes=size, sha256=sha(blob),
                               fnv1=f'{fnv:016x}', chunks=chunks))
    return result


def verify(data: bytes, pin: dict) -> None:
    if len(data) != pin['bytes'] or sha(data) != pin['sha256']:
        raise ValueError('Installer size/SHA256 does not match the pinned official asset')


def inventory(data: bytes) -> tuple[dict, list[tuple[str, bytes]]]:
    outer = PE(data)
    report = dict(setup_bytes=len(data), setup_sha256=sha(data),
                  setup_sections=outer.sections, setup_imports=outer.imports(),
                  resources=outer.resources(), legacy_footer=False, payloads=[])
    payloads = []
    if len(data) >= 32 and data[-32:-16] == FOOTER:
        size, config_size = struct.unpack_from('<QQ', data, len(data) - 16)
        offset = len(data) - 32 - size - config_size
        if offset < outer.extent or size < 64 or config_size > 1024 * 1024:
            raise ValueError('Invalid legacy payload bounds')
        PE(data[offset:offset + size])
        report['legacy_footer'] = True
        report['payload_bounds'] = [offset, size, config_size]
        payloads.append(('payload', data[offset:offset + size]))
        report['default_config'] = data[offset + size:-32].decode('utf-8')
    else:
        for i, resource in enumerate(report['resources']):
            start, size = resource['offset'], resource['bytes']
            if data[start:start + 2] == b'MZ':
                PE(data[start:start + size])
                payloads.append((f'resource-{i}', data[start:start + size]))
        if not payloads:
            # New graphical setups embed an include_bytes DLL inside .rdata,
            # not a resource or an EOF overlay. Inspect only bounded PE slices.
            for match in re.finditer(b'MZ', data):
                offset = match.start()
                section = next((s for s in outer.sections if
                    s['offset'] <= offset < s['offset'] + s['bytes']), None)
                if section is None:
                    continue
                end = section['offset'] + section['bytes']
                try:
                    candidate = PE(data[offset:end])
                except (ValueError, UnicodeError, struct.error):
                    continue
                if candidate.machine != 0x8664 or not candidate.flags & 0x2000:
                    continue
                payloads.append((f'embedded-{offset}', data[offset:offset+candidate.extent]))
                report.setdefault('embedded_payloads', []).append({
                    'offset': offset, 'bytes': candidate.extent})
                tail = data[offset+candidate.extent:min(end,offset+candidate.extent+4096)]
                if tail.startswith(b'[DlssNrOnAmd]\n') and b'HipDevice=-1\n' in tail:
                    limit = tail.index(b'HipDevice=-1\n') + len(b'HipDevice=-1\n')
                    report['default_config'] = tail[:limit].decode('utf-8')
        if not payloads:
            report['unrecognized_container'] = True
    for name, payload in payloads:
        pe = PE(payload)
        hints = sorted(set(m.group().decode('ascii') for m in re.finditer(
            rb'(?:__hip|hip[A-Z]|gfx1)[A-Za-z0-9_.$]{2,160}', payload)))
        report['payloads'].append(dict(name=name, bytes=len(payload), sha256=sha(payload),
                                      machine=pe.machine, dll=bool(pe.flags & 0x2000),
                                      sections=pe.sections, imports=pe.imports(), delayed_imports=pe.delayed_imports(),
                                      shader_containers=shaders(payload), symbol_hints=hints))
    return report, payloads


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--download', action='store_true', help='Download only pinned official fixtures')
    parser.add_argument('--fixtures', type=Path, default=ROOT / 'build/upstream-audit')
    args = parser.parse_args()
    pins = json.loads((ROOT / 'assets/upstream-candidates.json').read_text())
    args.fixtures.mkdir(parents=True, exist_ok=True)
    results = {'scope': 'static inspection only; no installer executed; no deployment', 'releases': {}}
    for version, pin in pins['releases'].items():
        path = args.fixtures / f'setup-{version}.exe'
        if args.download and not path.exists():
            url = ('https://github.com/danielblnc/DLSS-NR-on-AMD/releases/download/'
                   f'v{version}/dlssnr_on_amd_setup.exe')
            with urllib.request.urlopen(url, timeout=60) as response:
                data = response.read(pin['bytes'] + 1)
            verify(data, pin)
            path.write_bytes(data)
        with path.open('rb') as stream:
            data = stream.read(pin['bytes'] + 1)
        verify(data, pin)
        report, payloads = inventory(data)
        results['releases'][version] = report
        for name, payload in payloads:
            (args.fixtures / f'{version}-{name}.dll').write_bytes(payload)
    output = args.fixtures / 'audit.json'
    output.write_text(json.dumps(results, indent=2) + '\n')
    for version, report in results['releases'].items():
        print(version, json.dumps(report, separators=(',', ':')))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
