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
import zipfile
from dlssnr.games import pe_info
from dlssnr.upstream import COMPONENTS, HIP_IMPORTS
from dlssnr import upstream

ARCHIVE_ROOT = 'dlssnr-linux-portable'
PACKAGE_FILES = (
    'installer.py', 'install.sh', 'stage_upstream.py', 'build_release.py',
    'README.md', 'CHANGELOG.md', 'THIRD-PARTY.md', 'PROVENANCE.json', 'LICENSE',
    'docs/TROUBLESHOOTING.md', 'docs/INSTALL.md',
    'docs/games/cyberpunk-2077.md', 'docs/games/007-first-light.md', 'docs/games/atomic-heart.md',
    'dlssnr/assets.py', 'dlssnr/cli.py', 'dlssnr/conversion.py', 'dlssnr/lmxxf.py', 'dlssnr/numpy-wheels.json',
    'dlssnr/launch_support.py', 'dlssnr/deploy.py', 'dlssnr/legacy_converter.py', 'dlssnr/games.py', 'dlssnr/runtime.py', 'dlssnr/upstream.py',
    'native/hip_bridge.c', 'native/hip_bridge.h', 'native/nr_ordered.c', 'native/nr_ordered.h',
    'native/c32_prepack.c', 'native/c32_offsets.inc', 'native/active_c32.c',
    'sources/README.md', 'sources/fetch_vkd3d.py', 'sources/cross-win64.ini',
    'sources/vkd3d-submodules.json', 'sources/vkd3d-proton-ordered.patch',
    'sources/trampoline/amdhip64_7_pe.c', 'sources/trampoline/hip_bridge.h',
    'sources/trampoline/kernel32.def', 'sources/trampoline/ntdll.def',
    'scripts/build-components.sh', 'scripts/fetch-toolchain.py',
    'licenses/PROJECT-MIT.txt', 'licenses/vkd3d-proton-LICENSE',
    'licenses/vkd3d-proton-COPYING', 'licenses/vkd3d-proton-AUTHORS',
    'licenses/vkd3d-dependency-notices.txt',
    'licenses/LMXXF-MIT.txt', 'docs/releases/0.4.3.md', 'docs/releases/0.5.0.md',
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
            or b'DLSSNR_ORDERED_ABI_V3' not in bridge
            or b'DLSSNR_HIP_ABI_V4' not in bridge):
        raise ValueError('Missing x86_64 ordered HIP bridge')
    if b'NR: cannot establish producer/consumer boundary' not in content['d3d12core.dll']:
        raise ValueError('D3D12 core lacks the ordered integration patch')
    if b'method=%s' not in content['d3d12core.dll']:
        raise ValueError('D3D12 core lacks the compute/graphics wait integration')
    return content


def build_release(root, output_dir=None, components_root=None, archive_format="tar.gz"):
    if archive_format not in ("tar.gz", "zip"):
        raise ValueError("Supported archive formats: tar.gz, zip")
    root = Path(root).resolve(strict=True)
    generated = validate_components(components_root or root / 'build/components')
    content = {name: regular(root / name, root) for name in PACKAGE_FILES}
    # Historical builds can still package their pinned backend. Current releases
    # use the original inference path and ship no experimental GPU modules.
    if upstream.VERSION == '0.3.1':
        # Include the independently verified candidate allowlist only: never models,
        # local reports or developer build directories.
        candidate = root / 'experiments/lmxxf/stage4'
        candidate_manifest = json.loads(regular(candidate/'package.json', root))
        if candidate_manifest.get('format') != 'lmxxf-stage4-package-v1' or not candidate_manifest.get('files'):
            raise ValueError('Missing bundled backend manifest')
        for name, digest in candidate_manifest['files'].items():
            relative = Path(name)
            if relative.is_absolute() or '..' in relative.parts:
                raise ValueError('Invalid backend package path')
            data = regular(candidate/relative, root)
            if hashlib.sha256(data).hexdigest() != digest:
                raise ValueError('Modified backend package file: '+name)
            content[str((candidate/relative).relative_to(root))] = data
        content[str((candidate/'package.json').relative_to(root))] = regular(candidate/'package.json', root)
    manifest = json.loads((root / 'assets/manifest.json').read_text())
    # Hash actual build outputs. Different compilers need not produce identical DLLs.
    manifest['files'] = {name: hashlib.sha256(data).hexdigest() for name, data in generated.items()}
    content['assets/manifest.json'] = (json.dumps(manifest, indent=2) + '\n').encode()
    content.update({'assets/' + name: data for name, data in generated.items()})
    provenance = json.loads(content['PROVENANCE.json'])
    reference = provenance.get('base_components', {})
    provenance['packaged_components'] = {
        'files': manifest['files'],
        'matches_reference_release': manifest['files'] == reference.get('files'),
        'reference_release': reference.get('release'),
    }
    provenance['source_hashes'] = {
        name: hashlib.sha256(content[name]).hexdigest()
        for name in provenance.get('source_hashes', {}) if name in content
    }
    provenance['packaged_file_sha256'] = {
        name: hashlib.sha256(data).hexdigest()
        for name, data in sorted(content.items()) if name != 'PROVENANCE.json'
    }
    content['PROVENANCE.json'] = (json.dumps(provenance, indent=2) + '\n').encode()
    destination = Path(output_dir or root / 'dist')
    destination.mkdir(parents=True, exist_ok=True)
    archive = destination / (ARCHIVE_ROOT + '.' + archive_format)
    if archive_format == 'zip':
        with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zipped:
            for name in sorted(content):
                entry = zipfile.ZipInfo(ARCHIVE_ROOT + '/' + name, date_time=(1980, 1, 1, 0, 0, 0))
                entry.create_system = 3
                mode = 0o755 if name.endswith('.sh') else 0o644
                entry.external_attr = (0o100000 | mode) << 16
                entry.compress_type = zipfile.ZIP_DEFLATED
                zipped.writestr(entry, content[name], compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
    else:
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
    parser.add_argument('--archive-format', choices=('tar.gz', 'zip'), default='tar.gz')
    args = parser.parse_args()
    archive, checksum = build_release(Path(__file__).parent, args.output_dir, args.components_root, args.archive_format)
    print(archive)
    print(checksum)
