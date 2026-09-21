"""Automatic, user-local model preparation for the bundled Linux backend.

No NVIDIA data is downloaded or packaged. Candidate activation is a separate
transaction after the ordinary installer has established a working base.
"""
from contextlib import redirect_stdout
import fcntl
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shlex
import shutil
import stat
import subprocess
import sys
import sysconfig
import tempfile
import urllib.request

from . import assets, conversion, deploy

CONVERTER_HASHES = {
    'convert_weights.py': '8517a9d5592e2000b18522bf79a2480df5a78512514177a4ee4df3998f0597d3',
    'weight_assets.py': '29061876bdc5ffbcfd84e04fb86ad41c5db9728b3b812e81a8ad6164fe3167d9',
    'weight-records.json': 'f91a5ec0c98a1a18f76147defa444386b55250d6dd3340d7ada57d0d720440b2',
    'layout-recovery.json': '8efbd1654e1628be99873e00ad4eaa2e805a011dc318227d4b1c5bf5f7ecb833',
}


def supported(gpu):
    return gpu.get('arch', '').split(':', 1)[0] == 'gfx1201'


def backend(package_root):
    root = Path(package_root) / 'experiments/lmxxf/stage4'
    script = root / 'experiments/lmxxf/prepare_stage4.py'
    if not script.is_file():
        raise RuntimeError('The package is missing its Linux backend. Extract the complete portable archive again.')
    spec = importlib.util.spec_from_file_location('_dlssnr_bundled_backend', script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module, root


def cache_base(cache_root):
    return Path(cache_root) / 'experiments/lmxxf-stage4'


def preflight(cache_root):
    if sys.version_info < (3, 11):
        raise RuntimeError('The optimized installer requires Python 3.11 or newer.')
    if not shutil.which('gcc') or not shutil.which('g++'):
        raise RuntimeError('Install gcc and g++ with your distribution package manager, then run the installer again. No game files were changed.')
    base = str(cache_base(cache_root))
    if any(c.isspace() for c in base) or any(c in base for c in ':\\'):
        raise RuntimeError('The runtime cache path cannot contain spaces, colons or backslashes. Choose --data-dir /path/without/spaces.')


def cached_weights(package_root, cache_root):
    api, _ = backend(package_root)
    candidates = [cache_base(cache_root)/'assets'/api.WEIGHTS_SHA[:16],
                  Path(cache_root)/'weights'/conversion.KNOWN_NVIDIA_SHA/'lmxxf']
    for folder in candidates:
        if folder.exists() or folder.is_symlink():
            folder = deploy._safe(folder, directory=True)
            record = api.weight_manifest(folder)
            api.verify_weights(folder, record)
            return folder
    return None


def remembered_dll(cache_root):
    record = Path(cache_root)/'weights'/conversion.KNOWN_NVIDIA_SHA/'model-source.json'
    if not record.exists():
        return None
    data = json.loads(deploy._safe(record).read_text())
    if data.get('sha256') != conversion.KNOWN_NVIDIA_SHA:
        return None
    path = Path(data.get('path', ''))
    if path.is_absolute() and path.is_file() and not path.is_symlink():
        if assets.sha256(path) == conversion.KNOWN_NVIDIA_SHA:
            return path
    return None


def _environment():
    env = os.environ.copy()
    for name in ('PYTHONPATH', 'PYTHONHOME', 'LD_PRELOAD', 'LD_AUDIT', 'LD_LIBRARY_PATH'):
        env.pop(name, None)
    return env


def _numpy_works(python):
    if not Path(python).is_file():
        return False
    try:
        result = subprocess.run([str(python), '-I', '-c',
            'import sys,numpy as n; assert sys.version_info >= (3,11); '
            'assert n.dtype("<f4").itemsize == 4; assert n.ldexp(n.array([1],dtype=n.float32),-9)[0] == 1/512'],
            env=_environment(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30)
        return result.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def numpy_python(cache_root, *, quiet=False):
    """Reuse a working interpreter, otherwise install one hash-pinned wheel privately."""
    cache_root = Path(cache_root)
    managed = cache_root/'model-python'
    if _numpy_works(sys.executable):
        return Path(sys.executable)
    marker = 'DLSSNR private model converter Python\n'
    def verified_environment(folder, expected):
        if not folder.exists() and not folder.is_symlink():
            return False
        deploy._safe(folder, directory=True)
        mark = deploy._safe(folder/'.dlssnr-managed')
        for path in (folder, mark):
            info = path.stat()
            if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o022:
                raise RuntimeError('The private Python environment is not owned and protected by this user.')
        if mark.stat().st_nlink != 1 or mark.read_text() != expected:
            raise RuntimeError('Refusing to execute an unmanaged private Python environment.')
        deploy._safe(folder/'bin', directory=True, missing=True)
        return True
    for folder, expected in ((cache_root/'rocm-venv', 'DLSSNR managed ROCm venv\n'), (managed, marker)):
        if verified_environment(folder, expected) and _numpy_works(folder/'bin/python'):
            return folder/'bin/python'
    abi = 'cp'+str(sys.version_info.major)+str(sys.version_info.minor)
    if sysconfig.get_config_var('Py_GIL_DISABLED'):
        abi += 't'
    pins = json.loads(Path(__file__).with_name('numpy-wheels.json').read_text())
    wheel = pins['wheels'].get(abi)
    if sys.implementation.name != 'cpython' or wheel is None:
        raise RuntimeError('Automatic model conversion needs CPython 3.11–3.14 with NumPy. '
                           'Run this installer with a supported Python interpreter.')
    cache_root = deploy._safe(cache_root, directory=True, missing=True)
    cache_root.mkdir(parents=True, exist_ok=True)
    with deploy._safe(cache_root/'.model-python.lock', missing=True).open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError('Another model environment installation is running.') from exc
        if verified_environment(managed, marker) and _numpy_works(managed/'bin/python'):
            return managed/'bin/python'
        if managed.exists():
            deploy._safe(managed, directory=True)
            if deploy._safe(managed/'.dlssnr-managed').read_text() != marker:
                raise RuntimeError('Refusing to change an unmanaged model Python directory.')
        else:
            deploy._safe(managed, directory=True, missing=True).mkdir(mode=0o700)
            deploy._atomic_bytes(managed/'.dlssnr-managed', marker.encode())
        if not quiet:
            print('Preparing a private model converter: downloading verified NumPy (about 17 MB).', flush=True)
        # venv creates no system packages and does not inherit site-packages.
        result = subprocess.run([sys.executable, '-I', '-m', 'venv', str(managed)],
                                env=_environment(), capture_output=True, text=True, timeout=120)
        if result.returncode:
            raise RuntimeError('Python venv support is missing. Install your distribution’s python3-venv package, '
                               'then run the installer again. No game files were changed.')
        with tempfile.TemporaryDirectory(prefix='.numpy-', dir=cache_root) as temporary:
            target = Path(temporary)/wheel['filename']
            with urllib.request.urlopen(wheel['url'], timeout=60) as response:
                data = response.read(wheel['bytes']+1)
            if len(data) != wheel['bytes'] or hashlib.sha256(data).hexdigest() != wheel['sha256']:
                raise RuntimeError('NumPy download failed its pinned checksum. No game files were changed.')
            target.write_bytes(data)
            subprocess.run([str(managed/'bin/python'), '-I', '-m', 'pip', '--isolated', 'install',
                            '--no-index', '--no-deps', str(target)], env=_environment(),
                           stdout=subprocess.DEVNULL, check=True, timeout=120)
        if not _numpy_works(managed/'bin/python'):
            raise RuntimeError('The private model converter failed its import check.')
    return managed/'bin/python'


def launch_options(package_root, cache_root, exe, supplied=None, *, interactive=False,
                   original_backend=False):
    api, _ = backend(package_root)
    wrapper = Path(exe).parent/deploy.STORE/'launch.sh'
    base, entry = api.installation_paths(wrapper, cache_base(cache_root))
    saved = None
    state = base/'activation.json'
    if state.exists():
        saved = json.loads(deploy._safe(state).read_text()).get('steam_launch_options')
    target, previous = (wrapper, entry) if original_backend else (entry, wrapper)

    def merge(value):
        if value and value.strip():
            tokens = shlex.split(value)
            if '%command%' not in tokens and value.lstrip().startswith(('-', '+')):
                # Steam also accepts plain game arguments. Only normalize a
                # conservative argument subset, never shell commands or env vars.
                if any(c in value for c in '\r\n\x00;&|<>`$(){}*?[]!#~\\'):
                    raise ValueError('Argument-only launch options cannot contain shell syntax. '
                                     'For a custom command, include %command% explicitly.')
                value = '%command% '+value
        return api.merge_launch_options(value, target, previous)

    if supplied is not None:
        return merge(supplied)
    if not interactive:
        return merge(saved) if saved else None
    print('\nKeep your Steam launch options')
    print('In Steam: Library > right-click the game > Properties > General > Launch Options.')
    print('This field contains command text, not the launcher name or Proton version.')
    print('Keep its existing text to preserve OptiScaler, HDR and other settings.')
    while True:
        if saved:
            print('Previously saved launch options:')
            print(saved)
            print('  1. Keep the saved launch options above')
            paste, empty = '2', '3'
        else:
            paste, empty = '1', '2'
        print(f'  {paste}. Copy and paste the current Launch Options field from Steam')
        print(f'  {empty}. The Launch Options field in Steam is empty')
        choice = input('Choose a number (Enter or q to cancel): ').strip().lower()
        if choice in ('', 'q'):
            raise KeyboardInterrupt
        if saved and choice == '1':
            value = saved
        elif choice == empty:
            value = None
        elif choice == paste:
            while True:
                value = input('Paste the full Launch Options text (Enter to go back): ')
                if not value.strip():
                    break
                if value.strip().casefold() == 'steam':
                    print('Steam is already selected as the launcher. Here, paste the text from')
                    print('Properties > General > Launch Options, including %command% if present.')
                    print('If that field is empty, press Enter and choose the empty-field option.')
                    continue
                try:
                    return merge(value)
                except ValueError as exc:
                    print(str(exc))
                    print('Correct the pasted text, or press Enter to go back. Nothing was changed.')
            continue
        else:
            print('Choose one of the numbered options, or press Enter to cancel.')
            continue
        try:
            return merge(value)
        except ValueError as exc:
            print(str(exc))
            print('Choose another option. Nothing was changed.')


def prepare_weights(package_root, cache_root, nvidia_dll=None, *, quiet=False):
    preflight(cache_root)
    api, candidate = backend(package_root)
    api.package_manifest(candidate)
    found = cached_weights(package_root, cache_root)
    if found:
        return found
    source = Path(nvidia_dll).expanduser() if nvidia_dll else remembered_dll(cache_root)
    if source is None:
        raise RuntimeError('The optimized backend needs your original NVIDIA model DLL once. '
                           'Run install again with --nvidia-dll /path/to/nvngx_dlssnr.dll.')
    source = deploy._safe(source)
    if assets.sha256(source) != conversion.KNOWN_NVIDIA_SHA:
        raise RuntimeError('The NVIDIA model DLL does not match supported version 310.8.0.0. No game files were changed.')
    converter = Path(package_root)/'experiments/lmxxf'
    for name, expected in CONVERTER_HASHES.items():
        if assets.sha256(deploy._safe(converter/name)) != expected:
            raise RuntimeError('The model converter is incomplete or modified: '+name)
    python = numpy_python(cache_root, quiet=quiet)
    cache = deploy._safe(Path(cache_root)/'weights'/conversion.KNOWN_NVIDIA_SHA, directory=True, missing=True)
    cache.mkdir(parents=True, exist_ok=True)
    with deploy._safe(cache/'.lmxxf-convert.lock', missing=True).open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError('Another model conversion is running.') from exc
        output = cache/'lmxxf'
        if output.exists():
            api.verify_weights(output, api.weight_manifest(output))
            return output
        if shutil.disk_usage(cache).free < 1500*1024**2:
            raise RuntimeError('Model preparation needs about 1.5 GiB of free disk space.')
        if not quiet:
            print('Preparing the optimized model on the CPU. This is needed only once.', flush=True)
        with tempfile.TemporaryDirectory(prefix='.lmxxf-convert-', dir=cache) as temporary:
            generated = Path(temporary)/'prepared'
            script = converter/'convert_weights.py'
            command = ('import runpy,sys; p=sys.argv.pop(1); '
                       'sys.path.insert(0,p); s=sys.argv.pop(1); sys.argv[0]=s; '
                       'runpy.run_path(s,run_name="__main__")')
            result = subprocess.run([str(python), '-I', '-c', command, str(converter), str(script),
                                     str(source), str(generated)], env=_environment(),
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=600)
            if result.returncode:
                raise RuntimeError('Model conversion failed before game installation: '+result.stderr[-2000:])
            record = api.weight_manifest(generated)
            api.verify_weights(generated, record)
            generated.rename(output)
        deploy._atomic_bytes(cache/'model-source.json', (json.dumps({
            'path': str(source), 'sha256': conversion.KNOWN_NVIDIA_SHA})+'\n').encode())
    return output


def activate(package_root, cache_root, exe, prepared, *, launch_options=None, quiet=False):
    api, root = backend(package_root)
    # The full installer prints the final command once, after both transactions.
    with redirect_stdout(io.StringIO()):
        result = api.prepare(Path(exe).parent, prepared, root=root,
                             base=cache_base(cache_root), launch_options=launch_options)
    return {'backend': 'lmxxf', 'candidate': result,
            'launch_options': result['steam_launch_options'],
            'command_prefix': shlex.quote(result['entry'])}


def existing_runtime(exe):
    """Read only verified generated assignments; never source a shell script."""
    store = Path(exe).parent/deploy.STORE
    if not store.exists() and not store.is_symlink():
        return None
    status = deploy.status_game(exe)
    if not status.get('installed') or not status.get('valid') or status.get('pending'):
        return None
    text = deploy._safe(Path(exe).parent/deploy.STORE/'launch.sh').read_text()
    values = {}
    for line in text.splitlines():
        for name in ('DLSSNR_HIP_LIBRARY', 'VKD3D_FILTER_DEVICE_NAME'):
            prefix = 'export '+name+'='
            if line.startswith(prefix):
                parsed = shlex.split(line[len(prefix):])
                if len(parsed) != 1 or name in values:
                    raise RuntimeError('The saved runtime configuration is ambiguous.')
                values[name] = parsed[0]
    if set(values) != {'DLSSNR_HIP_LIBRARY', 'VKD3D_FILTER_DEVICE_NAME'}:
        return None
    return values
