"""Pinned legacy weight-conversion fixture; never deploy its runtime in the 0.4.0 candidate."""
import hashlib
from pathlib import Path
import struct

VERSION = '0.3.1'
SETUP_URL = 'https://github.com/danielblnc/DLSS-NR-on-AMD/releases/download/v0.3.1/dlssnr_on_amd_setup.exe'
SETUP_BYTES = 7598347
SETUP_SHA256 = 'cf7ada1486b499700a84846b342ca2b1defdb4db622843f812151f255f2ad63c'
PAYLOAD_SHA256 = 'b108d6407eb7f094a4f9111edd778eee7b978b648d413a9fc7aeedfdd914c154'
FLAG_SHADER_OFFSET = 436368
FLAG_SHADER_BYTES = 1472
FLAG_SHADER_SHA256 = '0b85aab8db0ee8ba14019e32e3839bb2d321cde974371b30eb3742955b53084b'
FLAG_SHADER_HASH = '135ea1f88cbc832d'
# Compute is the compatibility default after the 007 graphics startup failure.
# Both paths use the Linux ordered handoff, with Async and CpuWait disabled.
DEFAULT_WAIT_METHOD = 'compute'
LINUX_SYNC_SETTINGS = {'Async': '0', 'SpinDraw': '0', 'CpuWait': '0'}
GRAPHICS_WAIT_SHADERS = {
    'pixel': (437840, 1148, '3b1234bda72ee857362a81cfcbaf0c4ba66f55dfbbe97460689c578ccd12caf1', '9b67a44ca79c547f'),
    'vertex': (438992, 616, '6526515bce0be56016c40a78c54497f852d7bcf1c9237acbe759b36ad2cd2944', '97c89ca9f5ead0f9'),
}
GRAPHICS_WAIT_HASHES = {name: values[3] for name, values in GRAPHICS_WAIT_SHADERS.items()}
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
        raise ValueError('Expected the exact official DLSS-NR on AMD v' + VERSION + ' setup.')
    if data[-32:-16] != b'DLSSNR-SETUP-01\0':
        raise ValueError('Invalid setup footer.')
    size, config_size = struct.unpack_from('<QQ', data, len(data) - 16)
    offset = len(data) - 32 - config_size - size
    if (offset, size, config_size) != (293888, 7304192, 235):
        raise ValueError('Unexpected v0.3.1 payload bounds.')
    payload = data[offset:offset + size]
    if digest(payload) != PAYLOAD_SHA256:
        raise ValueError('Unexpected embedded runtime.')
    shader = payload[FLAG_SHADER_OFFSET:FLAG_SHADER_OFFSET + FLAG_SHADER_BYTES]
    if digest(shader) != FLAG_SHADER_SHA256 or shader_hash(shader) != FLAG_SHADER_HASH:
        raise ValueError('Unexpected precompiled synchronization shader.')
    for name, (start, length, sha256, fnv) in GRAPHICS_WAIT_SHADERS.items():
        shader = payload[start:start + length]
        if digest(shader) != sha256 or shader_hash(shader) != fnv:
            raise ValueError('Unexpected graphics-wait ' + name + ' shader.')
    return payload, data[offset + size:-32], {
        'mod_version': VERSION, 'setup_sha256': SETUP_SHA256,
        'payload_sha256': PAYLOAD_SHA256, 'payload_offset': offset,
        'payload_bytes': size, 'flag_shader_sha256': FLAG_SHADER_SHA256,
        'flag_shader_hash': FLAG_SHADER_HASH, 'payload_modified': False,
        'gameplay_verified': False,
        'linux_sync_settings': dict(LINUX_SYNC_SETTINGS),
        'upstream_graphics_wait_supported': True,
        'graphics_wait_shaders': dict(GRAPHICS_WAIT_HASHES),
        'graphics_wait_gameplay_verified': False,
    }


def read_setup(path):
    with Path(path).open('rb') as stream:
        data = stream.read(SETUP_BYTES + 1)
    inspect_setup(data)
    return data
