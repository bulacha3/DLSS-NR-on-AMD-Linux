"""Verify the official v0.3.0 setup and stage unmodified runtime files locally."""
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import struct
import tempfile
import urllib.request

VERSION = '0.3.0'
SETUP_URL = 'https://github.com/danielblnc/DLSS-NR-on-AMD/releases/download/v0.3.0/dlssnr_on_amd_setup.exe'
SETUP_BYTES = 7585035
SETUP_SHA256 = '26bb910cfe5dba85cb5e0fd050eaa6f79a73f0068026082afd4cf2c98cdd54dd'
PAYLOAD_SHA256 = '8321cae728d28cb7632d0d58d3d913e91132bf7645c126505698fbe4cd5a0138'
FLAG_SHADER_OFFSET = 427152
FLAG_SHADER_BYTES = 1472
FLAG_SHADER_SHA256 = '0b85aab8db0ee8ba14019e32e3839bb2d321cde974371b30eb3742955b53084b'
FLAG_SHADER_HASH = '135ea1f88cbc832d'
COMPONENTS = ('amdhip64_7.dll', 'd3d12.dll', 'd3d12core.dll', 'libdlssnr_hip_bridge.so')
HIP_IMPORTS = frozenset(('__hipPopCallConfiguration', '__hipPushCallConfiguration',
    '__hipRegisterFatBinary', '__hipRegisterFunction', '__hipRegisterVar',
    '__hipUnregisterFatBinary', 'hipDestroyExternalMemory', 'hipDeviceSynchronize',
    'hipDriverGetVersion', 'hipEventCreate', 'hipEventCreateWithFlags',
    'hipEventElapsedTime', 'hipEventQuery', 'hipEventRecord', 'hipEventSynchronize',
    'hipExternalMemoryGetMappedBuffer', 'hipFree', 'hipGetDeviceCount',
    'hipGetDevicePropertiesR0600', 'hipGetErrorString', 'hipGetLastError',
    'hipImportExternalMemory', 'hipLaunchKernel', 'hipMalloc', 'hipMemcpy',
    'hipMemcpyAsync', 'hipMemcpyToSymbol', 'hipMemset', 'hipMemsetAsync',
    'hipRuntimeGetVersion', 'hipSetDevice', 'hipStreamCreateWithFlags',
    'hipStreamSynchronize'))


def digest(data):
    return hashlib.sha256(data).hexdigest()


def shader_hash(data):
    # Exact FNV-1 used by pinned vkd3d-proton's vkd3d_shader_hash.
    value = 0xcbf29ce484222325
    for byte in data:
        value = ((value * 0x100000001b3) & 0xffffffffffffffff) ^ byte
    return f'{value:016x}'


def inspect_setup(data):
    if len(data) != SETUP_BYTES or digest(data) != SETUP_SHA256:
        raise ValueError('Expected the exact official DLSS-NR on AMD v0.3.0 setup.')
    if data[-32:-16] != b'DLSSNR-SETUP-01\0':
        raise ValueError('Invalid setup footer.')
    size, config_size = struct.unpack_from('<QQ', data, len(data) - 16)
    offset = len(data) - 32 - config_size - size
    if (offset, size, config_size) != (293888, 7290880, 235):
        raise ValueError('Unexpected v0.3.0 payload bounds.')
    payload = data[offset:offset + size]
    if digest(payload) != PAYLOAD_SHA256:
        raise ValueError('Unexpected embedded runtime.')
    shader = payload[FLAG_SHADER_OFFSET:FLAG_SHADER_OFFSET + FLAG_SHADER_BYTES]
    if digest(shader) != FLAG_SHADER_SHA256 or shader_hash(shader) != FLAG_SHADER_HASH:
        raise ValueError('Unexpected precompiled synchronization shader.')
    return payload, data[offset + size:-32], {
        'mod_version': VERSION, 'setup_sha256': SETUP_SHA256,
        'payload_sha256': PAYLOAD_SHA256, 'payload_offset': offset,
        'payload_bytes': size, 'flag_shader_sha256': FLAG_SHADER_SHA256,
        'flag_shader_hash': FLAG_SHADER_HASH, 'payload_modified': False,
        'gameplay_verified': False,
    }


def read_setup(path):
    with Path(path).open('rb') as stream:
        data = stream.read(SETUP_BYTES + 1)
    inspect_setup(data)
    return data


@contextmanager
def prepared_package(package_root, setup=None):
    from .assets import verify_assets, require_deployable
    root = Path(package_root)
    manifest = verify_assets(root)
    require_deployable(manifest)
    if setup is None:
        with urllib.request.urlopen(SETUP_URL, timeout=60) as response:
            data = response.read(SETUP_BYTES + 1)
    else:
        data = read_setup(setup)
    payload, config, report = inspect_setup(data)
    with tempfile.TemporaryDirectory(prefix='dlssnr-v030-') as temporary:
        prepared = Path(temporary)
        assets = prepared / 'assets'
        assets.mkdir()
        for name in COMPONENTS:
            content = (root / 'assets' / name).read_bytes()
            if digest(content) != manifest['files'][name]:
                raise RuntimeError('Component changed during staging: ' + name)
            (assets / name).write_bytes(content)
        inputs = {'dlssnr_on_amd_setup.exe': data, 'version.dll': payload}
        manifest = dict(manifest, files=dict(manifest['files']))
        for name, content in inputs.items():
            (assets / name).write_bytes(content)
            manifest['files'][name] = digest(content)
        (assets / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
        (prepared / 'staging.json').write_text(json.dumps(report, indent=2) + '\n')
        yield prepared
