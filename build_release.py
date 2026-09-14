#!/usr/bin/env python3
"""Package verified components; reproducible archive bytes for identical inputs."""
import argparse
import gzip
import hashlib
import io
import json
from pathlib import Path
import struct
import tarfile
from dlssnr.games import pe_info
from dlssnr.upstream import COMPONENTS, HIP_IMPORTS

ARCHIVE_ROOT = 'dlssnr-linux-portable'
PACKAGE_FILES = (
    'installer.py', 'install.sh', 'stage_upstream.py', 'build_release.py',
    'README.md', 'THIRD-PARTY.md', 'PROVENANCE.json', 'LICENSE',
    'docs/INSTALL.md', 'docs/TROUBLESHOOTING.md', 'docs/PRIVACY.md',
    'docs/games/cyberpunk-2077.md',
    'docs/games/007-first-light.md',
    'docs/games/atomic-heart.md',
    'dlssnr/assets.py', 'dlssnr/cli.py', 'dlssnr/conversion.py',
    'dlssnr/deploy.py', 'dlssnr/games.py', 'dlssnr/runtime.py', 'dlssnr/upstream.py',
    'native/hip_bridge.c', 'native/hip_bridge.h', 'native/nr_ordered.c', 'native/nr_ordered.h',
    'tests/native_contract.c', 'tests/vkd3d_ordered_contract.c',
    'tests/swapchain_queue_contract.c', 'tests/test_swapchain_queue.py',
    'sources/README.md', 'sources/fetch_vkd3d.py', 'sources/cross-win64.ini',
    'sources/vkd3d-submodules.json', 'sources/vkd3d-proton-ordered.patch',
    'sources/trampoline/amdhip64_7_pe.c', 'sources/trampoline/hip_bridge.h',
    'sources/trampoline/kernel32.def', 'sources/trampoline/ntdll.def',
    'scripts/build-components.sh', 'scripts/fetch-toolchain.py',
    'licenses/PROJECT-MIT.txt', 'licenses/vkd3d-proton-LICENSE',
    'licenses/vkd3d-proton-COPYING', 'licenses/vkd3d-proton-AUTHORS',
    'licenses/vkd3d-dependency-notices.txt',
)


def regular(path, parent):
    resolved = path.resolve(strict=True)
    if not resolved.is_relative_to(parent) or path.is_symlink() or not path.is_file():
        raise ValueError(f'Invalid release input: {path}')
    return resolved.read_bytes()


def validate_components(root):
    root = Path(root).resolve(strict=True)
    content = {name: regular(root / name, root) for name in COMPONENTS}
    for name in ('amdhip64_7.dll', 'd3d12.dll', 'd3d12core.dll'):
        info = pe_info(root / name)
        if info['machine'] != 0x8664 or not info['is_dll']:
            raise ValueError(f'{name} is not a Win64 DLL')
        if name == 'amdhip64_7.dll':
            missing = HIP_IMPORTS - set(info['exports'])
            if missing:
                raise ValueError('Trampoline is missing HIP exports: ' + ', '.join(sorted(missing)))
    bridge = content['libdlssnr_hip_bridge.so']
    if (bridge[:5] != b'\x7fELF\x02' or len(bridge) < 64
            or struct.unpack_from('<H', bridge, 18)[0] != 62
            or b'DLSSNR_ORDERED_ABI_V3' not in bridge):
        raise ValueError('Missing x86_64 ordered HIP bridge')
    if b'NR: cannot establish producer/consumer boundary' not in content['d3d12core.dll']:
        raise ValueError('D3D12 core lacks the ordered integration patch')
    return content


def build_release(root, output_dir=None, components_root=None):
    root = Path(root).resolve(strict=True)
    generated = validate_components(components_root or root / 'build/components')
    content = {name: regular(root / name, root) for name in PACKAGE_FILES}
    manifest = json.loads((root / 'assets/manifest.json').read_text())
    # Hash actual build outputs. Different compilers need not produce identical DLLs.
    manifest['files'] = {name: hashlib.sha256(data).hexdigest() for name, data in generated.items()}
    content['assets/manifest.json'] = (json.dumps(manifest, indent=2) + '\n').encode()
    content.update({'assets/' + name: data for name, data in generated.items()})
    destination = Path(output_dir or root / 'dist')
    destination.mkdir(parents=True, exist_ok=True)
    archive = destination / (ARCHIVE_ROOT + '.tar.gz')
    with archive.open('wb') as raw:
        with gzip.GzipFile(fileobj=raw, mode='wb', filename='', mtime=0, compresslevel=9) as zipped:
            with tarfile.open(fileobj=zipped, mode='w', format=tarfile.USTAR_FORMAT) as tar:
                for name in sorted(content):
                    entry = tarfile.TarInfo(ARCHIVE_ROOT + '/' + name)
                    entry.size = len(content[name])
                    entry.uid = entry.gid = entry.mtime = 0
                    entry.uname = entry.gname = ''
                    entry.mode = 0o755 if name.endswith('.sh') else 0o644
                    tar.addfile(entry, io.BytesIO(content[name]))
    checksum = archive.with_suffix(archive.suffix + '.sha256')
    checksum.write_text(hashlib.sha256(archive.read_bytes()).hexdigest() + '  ' + archive.name + '\n')
    return archive, checksum


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--components-root', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path)
    args = parser.parse_args()
    archive, checksum = build_release(Path(__file__).parent, args.output_dir, args.components_root)
    print(archive)
    print(checksum)
