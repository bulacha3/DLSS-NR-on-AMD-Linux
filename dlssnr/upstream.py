"""Verify the official v0.5.0 setup and stage unmodified runtime files locally."""
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import struct
import tempfile
import urllib.request

VERSION = '0.5.0'
SETUP_URL = 'https://github.com/danielblnc/DLSS-NR-on-AMD/releases/download/v0.5.0/dlssnr_on_amd_setup.exe'
SETUP_BYTES = 41864192
SETUP_SHA256 = '39df94a0c94b8194135cb2f85aedcc9225a7a62a66fb8adee600729fceab145e'
PAYLOAD_SHA256 = 'cddfb09e019347957bf7b96c95c0e900e8d3062dfaed697a8a96b0a039aec31a'
PAYLOAD_OFFSET = 2496351
PAYLOAD_BYTES = 38703616
DEFAULT_CONFIG = b'[DlssNrOnAmd]\nEnabled=1\nLocalTone=0\nLocalStructure=1\nSkinStructure=-1\nStyle=0\nUseAutoMask=1\nToneChannels=0\nQuality=fast\nOverlayKey=End\nScale=0.03125\nTemporal=1\nTonemap=-1\nToneCurve=reinhard\nToneLift=0\nUseGameExposure=1\nUseFsrInputs=1\nUseDepth=1\nInterop=1\nPreUpscale=1\nPreHistory=0\nAsync=0\nInlineWaitMs=200\nHipDevice=-1\n'
FLAG_SHADER_OFFSET = 522656
FLAG_SHADER_BYTES = 1472
FLAG_SHADER_SHA256 = '0b85aab8db0ee8ba14019e32e3839bb2d321cde974371b30eb3742955b53084b'
FLAG_SHADER_HASH = '135ea1f88cbc832d'
# Compute is the compatibility default after the 007 graphics startup failure.
# Both paths use the Linux ordered handoff, with Async and CpuWait disabled.
DEFAULT_WAIT_METHOD = 'compute'
LINUX_SYNC_SETTINGS = {'Async': '0', 'SpinDraw': '0', 'CpuWait': '0', 'PollSpacing': '0'}
GRAPHICS_WAIT_SHADERS = {
    'pixel': (524128, 1152, 'd16612a9715be13134b209612f599e4a7fc76d406a7142d8bdca67d8e55327cf', 'f2010bee184ea0aa'),
    'vertex': (525280, 616, '6526515bce0be56016c40a78c54497f852d7bcf1c9237acbe759b36ad2cd2944', '97c89ca9f5ead0f9'),
}
GRAPHICS_WAIT_HASHES = {name: values[3] for name, values in GRAPHICS_WAIT_SHADERS.items()}
COMPONENTS = ('amdhip64_7.dll', 'd3d12.dll', 'd3d12core.dll', 'libdlssnr_hip_bridge.so')
HIP_IMPORTS = frozenset(('__hipPopCallConfiguration', '__hipPushCallConfiguration',
    '__hipRegisterFatBinary', '__hipRegisterFunction', '__hipRegisterVar',
    '__hipUnregisterFatBinary', 'hipDestroyExternalMemory', 'hipDeviceSynchronize',
    'hipDriverGetVersion', 'hipEventCreate', 'hipEventCreateWithFlags',
    'hipEventElapsedTime', 'hipEventQuery', 'hipEventRecord', 'hipEventSynchronize',
    'hipExternalMemoryGetMappedBuffer', 'hipFree', 'hipGetDevice', 'hipGetDeviceCount',
    'hipGetDevicePropertiesR0600', 'hipGetErrorString', 'hipGetLastError',
    'hipImportExternalMemory', 'hipLaunchKernel', 'hipMalloc', 'hipMemcpy',
    'hipMemcpyAsync', 'hipMemcpyToSymbol', 'hipMemset', 'hipMemsetAsync',
    'hipOccupancyMaxActiveBlocksPerMultiprocessor', 'hipRuntimeGetVersion', 'hipSetDevice', 'hipStreamCreateWithFlags',
    'hipStreamSynchronize', 'hipDeviceGetStreamPriorityRange', 'hipStreamCreateWithPriority', 'hipStreamDestroy'))


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
    # The graphical installer embeds the unmodified DLL in .rdata followed
    # immediately by its default INI. The entire installer is pinned above.
    offset, size, config_size = PAYLOAD_OFFSET, PAYLOAD_BYTES, len(DEFAULT_CONFIG)
    payload = data[offset:offset + size]
    config = data[offset + size:offset + size + config_size]
    if config != DEFAULT_CONFIG:
        raise ValueError('Unexpected embedded default configuration.')
    if digest(payload) != PAYLOAD_SHA256:
        raise ValueError('Unexpected embedded runtime.')
    shader = payload[FLAG_SHADER_OFFSET:FLAG_SHADER_OFFSET + FLAG_SHADER_BYTES]
    if digest(shader) != FLAG_SHADER_SHA256 or shader_hash(shader) != FLAG_SHADER_HASH:
        raise ValueError('Unexpected precompiled synchronization shader.')
    for name, (start, length, sha256, fnv) in GRAPHICS_WAIT_SHADERS.items():
        shader = payload[start:start + length]
        if digest(shader) != sha256 or shader_hash(shader) != fnv:
            raise ValueError('Unexpected graphics-wait ' + name + ' shader.')
    return payload, config, {
        'mod_version': VERSION, 'setup_sha256': SETUP_SHA256,
        'payload_sha256': PAYLOAD_SHA256, 'payload_offset': offset,
        'payload_bytes': size, 'flag_shader_sha256': FLAG_SHADER_SHA256,
        'flag_shader_hash': FLAG_SHADER_HASH, 'payload_modified': False,
        'gameplay_verified': False,
        'linux_sync_settings': dict(LINUX_SYNC_SETTINGS),
        'upstream_graphics_wait_supported': True,
        'inference_backend': 'original',
        'lmxxf_activation_allowed': False,
        'weight_conversion_version': '0.3.1',
        'graphics_wait_shaders': dict(GRAPHICS_WAIT_HASHES),
        'graphics_wait_gameplay_verified': False,
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
    with tempfile.TemporaryDirectory(prefix='dlssnr-v050-') as temporary:
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
