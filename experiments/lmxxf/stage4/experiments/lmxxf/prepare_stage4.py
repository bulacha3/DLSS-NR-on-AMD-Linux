#!/usr/bin/env python3
"""Install the lmxxf candidate using prepared local weights."""
from __future__ import annotations
import argparse, hashlib, json, os, re, shlex, shutil, stat, subprocess, sys, tempfile, uuid
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from install_helpers import checked_path, atomic_file, find_wrapper, DEFAULT_GAME
ROOT = Path(__file__).resolve().parents[2]
PAYLOAD_SHA = 'b108d6407eb7f094a4f9111edd778eee7b978b648d413a9fc7aeedfdd914c154'
WEIGHTS_SHA = 'd80ef296eac0466f9d73f1db5085d33a99638072426d4fa984fb367fe9af402a'
WEIGHT_BYTES = 600340264
def sha(data): return hashlib.sha256(data).hexdigest()
def digest(path):
    with checked_path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()
def owned_directory(path):
    path = checked_path(path, directory=True, missing=True)
    path.mkdir(parents=True, mode=0o700, exist_ok=True)
    s = path.stat()
    if s.st_uid != os.getuid() or stat.S_IMODE(s.st_mode) & 0o022:
        raise RuntimeError(f'Cache must be owned by the current user and not writable by others: {path}')
    return path
def package_manifest(root):
    data = json.loads(checked_path(root/'package.json').read_text())
    if data.get('format') != 'lmxxf-stage4-package-v1' or not data.get('files'):
        raise RuntimeError('Unknown package manifest.')
    for name, expected in data['files'].items():
        p = Path(name)
        if p.is_absolute() or '..' in p.parts or not re.fullmatch('[0-9a-f]{64}', expected):
            raise RuntimeError('Invalid package path or hash.')
        if digest(root/p) != expected:
            raise RuntimeError(f'Package is incomplete or modified: {name}')
    return data
def weight_manifest(folder):
    data = json.loads(checked_path(folder/'conversion-provenance.json').read_text())
    files = data.get('files', {})
    if (data.get('format') != 'lmxxf-direct-dll-conversion-v1' or
            sha(json.dumps(files, sort_keys=True, separators=(',', ':')).encode()) != WEIGHTS_SHA or
            len(files) != 184 or sum(x['bytes'] for x in files.values()) != WEIGHT_BYTES):
        raise RuntimeError(f'Weights do not match the required format and hashes: {folder}')
    return data
def verify_weights(folder, data):
    for name, info in data['files'].items():
        p = checked_path(folder/(name+'.f32'))
        if p.stat().st_size != info['bytes'] or digest(p) != info['sha256']:
            raise RuntimeError(f'Missing or modified weight: {p}')
def find_weights(explicit, root):
    if explicit: candidates = [Path(explicit)]
    else:
        queue = [(p, 0) for p in dict.fromkeys((root.parent, Path.cwd(), Path.cwd().parent, Path.home()/'Downloads'))]
        candidates, seen = [], set()
        while queue and len(candidates) < 300:
            p, depth = queue.pop(0)
            key = os.path.abspath(p)
            if key in seen or p.is_symlink() or not p.is_dir(): continue
            seen.add(key); candidates.append(p)
            if depth < 2:
                try:
                    children = sorted(p.iterdir(), key=lambda x: ('etapa3' not in x.name.lower(), x.name))
                    queue += [(x, depth+1) for x in children[:300] if not x.name.startswith('.') and not x.is_symlink() and x.is_dir()]
                except OSError: pass
    for p in candidates:
        for suffix in ('', 'build/lmxxf/prepared-weights', 'prepared-weights'):
            f = p/suffix
            if not (f/'conversion-provenance.json').is_file(): continue
            f = checked_path(f, directory=True)
            try: weight_manifest(f)
            except (RuntimeError, ValueError): continue
            return f
    raise RuntimeError('Prepared weights not found. Add --weights "/path/to/prepared-weights".')
def input_path(value):
    """Accept a pasted/dragged path without evaluating shell syntax."""
    value = value.strip()
    if value[:1] in ("'", '"'):
        fields = shlex.split(value)
        if len(fields) != 1:
            raise ValueError('Enter one game path.')
        value = fields[0]
    if not value:
        raise EOFError
    return Path(value).expanduser().absolute()


def game_folder(path):
    path = Path(path).expanduser().absolute()
    if path.suffix.lower() == '.exe' and path.is_file():
        path = path.parent
    find_wrapper(path)
    return path


def discover_installed_games(base, home=None):
    """Read known state and bounded Steam layouts; never scan whole disks."""
    home = Path.home() if home is None else Path(home)
    result = {}; states = [base/'activation.json']
    states += sorted((base/'games').glob('*/activation.json'))[:1000]
    def add(path, label=None):
        try:
            path = game_folder(path); wrapper = find_wrapper(path)
            name = label or (path.parent.name if path.name == '.dlssnr-linux' else path.name)
            result.setdefault(str(wrapper), {'name': name, 'path': path})
        except (OSError, RuntimeError, ValueError):
            pass
    for state in states:
        try:
            data = json.loads(checked_path(state).read_text())
            if isinstance(data.get('original_launcher'), str):
                add(Path(data['original_launcher']).parent)
        except (OSError, RuntimeError, ValueError):
            pass
    roots = [home/'.local/share/Steam', home/'.steam/steam', home/'.steam/root',
             home/'.var/app/com.valvesoftware.Steam/.local/share/Steam']
    libraries = set()
    for root in roots:
        if not root.is_dir():
            continue
        root = root.resolve(); libraries.add(root)
        for config in (root/'steamapps/libraryfolders.vdf', root/'config/libraryfolders.vdf'):
            try:
                if config.stat().st_size > 4*1024*1024:
                    continue
                content = config.read_text()
                for match in re.finditer(r'"path"\s+"((?:[^"\\]|\\.)*)"', content, re.I):
                    value = re.sub(r'\\(["\\])', r'\1', match.group(1))
                    candidate = Path(value)
                    if candidate.is_absolute() and candidate.is_dir():
                        libraries.add(candidate.resolve())
            except (OSError, UnicodeError):
                pass
    for library in sorted(libraries)[:64]:
        common = library/'steamapps/common'
        try:
            for path in sorted(common.iterdir())[:5000]:
                if path.is_dir() and not path.is_symlink():
                    try:
                        wrapper = find_wrapper(path)
                        result[str(wrapper)] = {'name': path.name, 'path': path}
                    except (OSError, RuntimeError, ValueError):
                        pass
        except OSError:
            pass
    return sorted(result.values(), key=lambda item: (item['name'].casefold(), str(item['path'])))


def merge_launch_options(options, entry, original_wrapper):
    """Replace only the managed launcher, preserving all other shell text."""
    entry = str(entry); original_wrapper = str(original_wrapper)
    if not options or not options.strip():
        return shlex.quote(entry)+' %command%'
    if any(c in options for c in '\r\n\x00'):
        raise ValueError('Steam launch options must be one line.')
    # Keep original token spans: shlex.join would alter quoted environment values.
    word = re.compile(r"(?:[^\s'\"\\]|\\.|'[^']*'|\"(?:\\.|[^\"\\])*\")+")
    spans = []; offset = 0
    for match in word.finditer(options):
        if options[offset:match.start()].strip():
            raise ValueError('Unsupported quoting in Steam launch options.')
        raw = match.group(); parsed = shlex.split(raw)
        if len(parsed) != 1:
            raise ValueError('Unsupported quoting in Steam launch options.')
        spans.append((parsed[0], match.start(), match.end())); offset = match.end()
    if options[offset:].strip():
        raise ValueError('Unsupported quoting in Steam launch options.')
    commands = [i for i, item in enumerate(spans) if item[0] == '%command%']
    if len(commands) != 1:
        raise ValueError('Steam launch options must contain exactly one %command%.')
    index = commands[0]
    known = [item for item in spans[:index] if item[0] in (entry, original_wrapper)]
    if len(known) > 1:
        raise ValueError('More than one DLSS-NR launcher is present; keep only one.')
    if known:
        _, begin, end = known[0]
        return options[:begin]+shlex.quote(entry)+options[end:]
    if any(item[0].endswith('/launch.sh') for item in spans[:index]):
        raise ValueError('An unknown launch.sh is present. Replace it with the current game launcher first.')
    begin = spans[index][1]
    return options[:begin]+shlex.quote(entry)+' '+options[begin:]


def guided_setup(args, base):
    print('DLSS-NR Linux — lmxxf update')
    print('Close the game. Existing Proton and runtime settings will be reused.\n')
    print('1. Choose the game')
    choices = discover_installed_games(base)
    for index, item in enumerate(choices, 1):
        print(f"  {index}. {item['name']} — {item['path']}")
    if choices:
        print('Enter a number, or paste the game folder / executable path.')
    else:
        print('Paste the game folder or executable path.')
    while True:
        entered = input('Game (empty to cancel): ').strip()
        if not entered:
            raise EOFError
        try:
            if entered.isascii() and entered.isdecimal() and 1 <= int(entered) <= len(choices):
                args.game = choices[int(entered)-1]['path']
            else:
                args.game = game_folder(input_path(entered))
            break
        except (RuntimeError, OSError, ValueError) as error:
            print(str(error))
            print('This update requires an existing DLSS-NR Linux installation.')
            print('For a new game, first use install.sh from the full portable release:')
            print('https://github.com/bulacha3/DLSS-NR-on-AMD-Linux/releases')
    if args.restore:
        return args
    print('\n2. Reuse model data')
    cached = base/'assets'/WEIGHTS_SHA[:16]
    if cached.is_dir():
        weight_manifest(cached)
        print('Prepared model data found in the shared cache.')
    elif args.weights:
        weight_manifest(args.weights)
    else:
        try:
            args.weights = find_weights(None, ROOT)
            print('Prepared model data found automatically.')
        except RuntimeError:
            print('Prepared model data is required by this update package.')
            while True:
                try:
                    args.weights = input_path(input('Prepared weights folder (empty to cancel): '))
                    weight_manifest(args.weights)
                    break
                except (RuntimeError, OSError, ValueError) as error:
                    print(str(error))
    print('\n3. Keep Steam launch options')
    wrapper = find_wrapper(args.game); state_base, entry = installation_paths(wrapper, base)
    saved = ''
    try:
        saved = json.loads(checked_path(state_base/'activation.json').read_text()).get('steam_launch_options', '')
    except (RuntimeError, OSError, ValueError):
        pass
    if args.launch_options is None:
        if saved:
            print('Press Enter to keep the previously saved options, or paste the current Steam options.')
        else:
            print('Paste the current Steam launch options to preserve OptiScaler, HDR and other settings.')
            print('Leave empty only if Steam has no launch options.')
        while True:
            try:
                selected = input('Launch options: ').strip() or saved
                args.launch_options = merge_launch_options(selected, entry, wrapper)
                break
            except ValueError as error:
                print(str(error))
    print('\nPreparing the update...')
    return args


def clean_env():
    env = os.environ.copy()
    for k in tuple(env):
        if k in ('LD_PRELOAD','LD_AUDIT') or k.startswith(('DLSSNR_LMXXF','DLSSNR_C32','DLSSNR_ACTIVE_C32','DLSSNR_PROFILE')): env.pop(k)
    return env
def compile_host(root, output):
    cc, cxx = shutil.which('gcc'), shutil.which('g++')
    if not cc or not cxx: raise RuntimeError('gcc and g++ are required. Nothing was activated.')
    flags = ['-O2','-fPIC','-shared','-pthread']; env = clean_env()
    subprocess.run([cxx,'-std=c++17',*flags,'-fno-fast-math','-ffp-contract=off','-I',str(root/'runtime/include'),
                    str(root/'experiments/lmxxf/resident_backend.cpp'),'-ldl','-o',str(output/'liblmxxf_resident.so')],
                   check=True, env=env, timeout=240)
    subprocess.run([cc,'-std=gnu11',*flags,'-mtls-dialect=gnu','-DDLSSNR_LMXXF','-Werror=incompatible-pointer-types',
                    '-Werror=implicit-function-declaration',str(root/'native/hip_bridge.c'),'-ldl','-o',str(output/'libdlssnr_hip_bridge.so')],
                   check=True, env=env, timeout=120)
    subprocess.run([sys.executable,'-c','import ctypes,sys; ctypes.CDLL(sys.argv[1])',str(output/'liblmxxf_resident.so')],
                   check=True, env=env, timeout=20)
    report = output/'host-load.txt'
    env.update(LD_PRELOAD=str(output/'libdlssnr_hip_bridge.so'), DLSSNR_LMXXF='1',
               DLSSNR_LMXXF_REPORT=str(report), DLSSNR_HIP_LOG=str(output/'host-hip.txt'))
    subprocess.run(['/bin/true'], check=True, env=env, timeout=20)
    if 'bridge_loaded=1' not in report.read_text(): raise RuntimeError('The bridge did not load. Nothing was activated.')
    report.unlink(); (output/'host-hip.txt').unlink(missing_ok=True)
def require_hash(path, expected):
    return '\n'.join(['required='+shlex.quote(str(path)),
        'if [[ ! -f "$required" || -L "$required" ]] || ! actual=$(sha256sum < "$required") || [[ "${actual%% *}" != '+shlex.quote(expected)+' ]]; then',
        '  printf "lmxxf: missing or modified file: %s\\n" "$required" >&2', '  exit 1', 'fi'])
def build_wrapper(original, target, assets, report, hashes, key, profile=False):
    lines = original.splitlines(); pre = [i for i,s in enumerate(lines) if s.startswith('export LD_PRELOAD=')]
    ex = [i for i,s in enumerate(lines) if s == 'exec "$@"']
    if (lines[:2] != ['#!/bin/bash','set -e'] or len(pre)!=1 or len(ex)!=1 or pre[0]>=ex[0]
            or any(s.strip() for s in lines[ex[0]+1:])):
        raise RuntimeError('Unsupported launch.sh format. Nothing was activated.')
    q = shlex.quote
    result = lines[:pre[0]] + [require_hash(p,h) for p,h in hashes.items()]
    result += [
        'if ! sha256sum --check --status '+q(str(target/'runtime.sha256'))+'; then',
        '  printf "%s\\n" "lmxxf: weights or modules changed; run preparation again." >&2', '  exit 1','fi',
        'unset DLSSNR_ACTIVE_C32 DLSSNR_C32_PREPACK DLSSNR_C32_MODULE DLSSNR_C32_REPORT DLSSNR_PROFILE DLSSNR_PROFILE_REPORT',
        'export DLSSNR_LMXXF=1',
        'export DLSSNR_LMXXF_LIBRARY='+q(str(target/'liblmxxf_resident.so')),
        'export DLSSNR_LMXXF_MODULES='+q(str(target/'modules')),
        'export DLSSNR_LMXXF_ASSETS='+q(str(assets)),
        'export DLSSNR_RESEARCH_HIP_LIBRARY="${DLSSNR_HIP_LIBRARY:?Base HIP runtime is not configured}"',
        'export DLSSNR_LMXXF_REPORT='+q(str(report)),
        'export DLSSNR_LMXXF_GPU_PROFILE='+('1' if profile else '0'),
        'export DLSSNR_LMXXF_GPU_PROFILE_REPORT='+q(str(report.with_name('kernel-profile.txt'))),
        'export STEAM_COMPAT_MOUNTS="${STEAM_COMPAT_MOUNTS:+$STEAM_COMPAT_MOUNTS:}"'+q(str(target.parent.parent)),
        'export PRESSURE_VESSEL_FILESYSTEMS_RO="${PRESSURE_VESSEL_FILESYSTEMS_RO:+$PRESSURE_VESSEL_FILESYSTEMS_RO:}"'+q(str(target.parent.parent)),
        'export PRESSURE_VESSEL_FILESYSTEMS_RW="${PRESSURE_VESSEL_FILESYSTEMS_RW:+$PRESSURE_VESSEL_FILESYSTEMS_RW:}"'+q(str(report.parent)),
        'umask 077',
        'if [[ "$DLSSNR_LMXXF_GPU_PROFILE" == 1 ]]; then',
        '  if [[ -L "$DLSSNR_LMXXF_GPU_PROFILE_REPORT" ]]; then exit 1; fi',
        '  printf "%s\\n" '+q('build='+key)+' "profile_status=waiting_for_frames" "gpu_intervals_are_not_fps=1" > "$DLSSNR_LMXXF_GPU_PROFILE_REPORT"',
        'fi',
        'if [[ -L "$DLSSNR_LMXXF_REPORT" || -L "$DLSSNR_LMXXF_REPORT.previous" ]]; then exit 1; fi',
        'if [[ -f "$DLSSNR_LMXXF_REPORT" ]]; then cp -- "$DLSSNR_LMXXF_REPORT" "$DLSSNR_LMXXF_REPORT.previous"; fi',
        'printf "%s\\n" "lmxxf stage 4 - game integration" '+q('build='+key)+' "activation=after-one-original-frame" "worker_wall_ms_is_not_gpu_time_or_fps=1" > "$DLSSNR_LMXXF_REPORT"',
        'finish_stage4() {', '  local rc=$? line ran=0 failed=0 original=0 loaded=0 unsupported=0 result',
        '  while IFS= read -r line; do', '    case "$line" in',
        '      "[lmxxf-stage4] completed="*" backend=lmxxf "*) ran=1 ;;',
        '      "[lmxxf-stage4] error="*) failed=1 ;;',
        '      "[lmxxf-stage4] frame="*" unsupported="*) unsupported=1 ;;',
        '      "[lmxxf-stage4] completed="*" backend=original-"*)',
        '        original=1',
        '        case "$line" in *" next_eligible=0"|*" next_eligible=0 "*) unsupported=1 ;; esac ;;',
        '      "[lmxxf-stage4] bridge_loaded=1 "*) loaded=1 ;;', '    esac',
        '  done < "$DLSSNR_LMXXF_REPORT"',
        '  if (( failed && ran )); then result=backend_failed_after_lmxxf_frames;',
        '  elif (( failed )); then result=backend_failed;',
        '  elif (( ran && unsupported )); then result=lmxxf_partial;',
        '  elif (( ran )); then result=lmxxf_ran;',
        '  elif (( original )); then result=original_only;', '  elif (( loaded )); then result=bridge_loaded_no_frames;',
        '  else result=bridge_not_loaded; fi',
        '  printf "result=%s\\nunsupported_seen=%s\\nlauncher_exit=%s\\n" "$result" "$unsupported" "$rc" >> "$DLSSNR_LMXXF_REPORT"',
        '}', 'trap finish_stage4 EXIT',
        'export LD_PRELOAD='+q(str(target/'libdlssnr_hip_bridge.so'))+'"${LD_PRELOAD:+:$LD_PRELOAD}"',
    ]
    return '\n'.join(result+lines[pre[0]+1:ex[0]]+['set +e','"$@"','result=$?','exit "$result"',''])
def previous_entry(base, entry):
    p = checked_path(entry, missing=True); current = p.read_bytes() if p.exists() else None
    state_path = base/'activation.json'
    if state_path.exists():
        s = json.loads(checked_path(state_path).read_text())
        if s.get('active'):
            if s.get('entry') != str(entry) or current is None or sha(current) != s['installed_sha256']:
                raise RuntimeError('Launcher was modified after installation; it was not overwritten.')
            backup = checked_path(base/s['backup'])
            if digest(backup) != s['backup_sha256']: raise RuntimeError('Previous backup was modified.')
            return backup.read_bytes(), s['backup_mode'], current
    return current, (stat.S_IMODE(p.stat().st_mode)&0o777 if current is not None else 0o700), current
def restore(base, entry):
    path = checked_path(base/'activation.json'); s = json.loads(path.read_text())
    if not s.get('active'): print('The candidate is already disabled.'); return
    if s.get('entry') != str(entry) or digest(entry) != s['installed_sha256']:
        raise RuntimeError('launch.sh was modified after installation; changes were preserved.')
    backup = checked_path(base/s['backup'])
    if digest(backup) != s['backup_sha256']: raise RuntimeError('Backup is missing or modified. Nothing was replaced.')
    atomic_file(entry, backup.read_bytes(), s['backup_mode']); s['active'] = False
    atomic_file(path, (json.dumps(s,indent=2)+'\n').encode())
    print('Candidate disabled. The same Steam entry now uses the previous launcher.')

def installation_paths(wrapper, base, explicit_entry=None):
    """Reuse the known legacy game's entry; isolate every other game's state.

    Assets/build storage stays shared. Only state, backups and entry are local
    to each game. Merely selecting a game never rewrites another game's entry.
    """
    if explicit_entry is not None:
        return base, Path(explicit_entry)
    legacy = checked_path(base/'activation.json', missing=True)
    legacy_entry = base.parent/'c32-prepack/launch.sh'
    if legacy.exists():
        state = json.loads(legacy.read_text())
        if state.get('original_launcher') == str(wrapper):
            if state.get('entry') != str(legacy_entry):
                raise RuntimeError('Unexpected previous launcher path. Nothing was changed.')
            return base, legacy_entry
    elif wrapper == DEFAULT_GAME/'bin/x64/.dlssnr-linux/launch.sh':
        return base, legacy_entry
    identity = sha(str(wrapper).encode())[:20]
    game_base = base/'games'/identity
    return game_base, game_base/'launch.sh'

def prepare(game, explicit_weights=None, *, root=ROOT, base=None, entry=None, profile=False, launch_options=None):
    if sys.platform != 'linux' or os.uname().machine != 'x86_64': raise RuntimeError('Linux x86_64 is required.')
    base = Path(base) if base else Path.home()/'.local/share/dlssnr-linux/experiments/lmxxf-stage4'
    if any(c.isspace() for c in str(base)) or any(c in str(base) for c in ':\\'):
        raise RuntimeError('Cache path cannot contain whitespace, colons or backslashes.')
    package = package_manifest(root); wrapper = find_wrapper(game); original = wrapper.read_bytes()
    payload = checked_path(wrapper.parent.parent/'version.dll')
    if digest(payload) != PAYLOAD_SHA: raise RuntimeError('version.dll does not match the required Daniel 0.3.1 payload. Nothing was activated.')
    base = owned_directory(base)
    state_base, entry = installation_paths(wrapper, base, entry)
    if state_base != base: owned_directory(base/'games')
    state_base = owned_directory(state_base); owned_directory(entry.parent)
    for parent in (base.parent,base.parent.parent): owned_directory(parent)
    old, mode, expected_current = previous_entry(state_base,entry)
    if launch_options is None and (state_base/'activation.json').exists():
        launch_options = json.loads(checked_path(state_base/'activation.json').read_text()).get('steam_launch_options')
    steam_options = merge_launch_options(launch_options, entry, wrapper)
    if old is None: old = ('#!/bin/bash\nset -e\nexec '+shlex.quote(str(wrapper))+' "$@"\n').encode()
    report = checked_path(owned_directory(wrapper.parent/'logs')/'resultado-etapa4.txt',missing=True)
    assets_root = owned_directory(base/'assets'); assets = checked_path(assets_root/WEIGHTS_SHA[:16],directory=True,missing=True)
    if assets.exists():
        record = weight_manifest(assets); print('Checking prepared weights...',flush=True); verify_weights(assets,record)
    else:
        source = find_weights(explicit_weights,root); record = weight_manifest(source)
        if shutil.disk_usage(base).free < WEIGHT_BYTES+100_000_000: raise RuntimeError('Approximately 700 MB of free disk space is required.')
        print('Reusing and checking prepared weights...',flush=True)
        with tempfile.TemporaryDirectory(prefix='.weights-',dir=assets_root) as t:
            t = Path(t)
            for name,info in record['files'].items():
                src = checked_path(source/(name+'.f32'))
                if src.stat().st_size != info['bytes']: raise RuntimeError(f'Unexpected file size: {src}')
                shutil.copyfile(src,t/src.name)
            shutil.copyfile(checked_path(source/'conversion-provenance.json'),t/'conversion-provenance.json')
            verify_weights(t,record); os.rename(t,assets)
    builds = owned_directory(base/'builds'); key = sha(json.dumps(package['files'],sort_keys=True).encode())[:16]
    target = builds/(key+'-'+uuid.uuid4().hex[:12])
    print('Building the bridge and lmxxf backend...',flush=True)
    with tempfile.TemporaryDirectory(prefix='.build-',dir=builds) as temp:
        t = Path(temp); compile_host(root,t); shutil.copytree(root/'runtime/modules',t/'modules')
        hashes = {assets/(name+'.f32'):info['sha256'] for name,info in record['files'].items()}
        hashes[assets/'conversion-provenance.json'] = digest(assets/'conversion-provenance.json')
        for p in sorted((t/'modules').iterdir()): hashes[target/'modules'/p.name] = digest(p)
        sums = ''.join(f'{h}  {p}\n' for p,h in hashes.items()); (t/'runtime.sha256').write_text(sums)
        required = {wrapper:sha(original),payload:PAYLOAD_SHA,target/'runtime.sha256':sha(sums.encode())}
        for name in ('liblmxxf_resident.so','libdlssnr_hip_bridge.so'): required[target/name] = digest(t/name)
        launcher = build_wrapper(original.decode(),target,assets,report,required,key,profile=profile)
        (t/'launch.sh').write_text(launcher); (t/'launch.sh').chmod(0o700); (t/'original-launch.sh').write_bytes(original)
        subprocess.run(['/bin/bash','-n',str(t/'launch.sh')],check=True,env=clean_env())
        if wrapper.read_bytes()!=original or digest(payload)!=PAYLOAD_SHA: raise RuntimeError('Installation changed during preparation. Nothing was activated.')
        if (entry.read_bytes() if entry.exists() else None)!=expected_current: raise RuntimeError('Launcher changed during preparation. Nothing was activated.')
        os.rename(t,target)
    installed = ('#!/bin/bash\nset -e\n'+require_hash(target/'launch.sh',sha(launcher.encode()))+'\nexec '+shlex.quote(str(target/'launch.sh'))+' "$@"\n').encode()
    backup = 'before-stage4-'+sha(old)[:16]+'.sh'; atomic_file(state_base/backup,old,mode)
    s = {'format':'lmxxf-stage4-activation-v1','active':True,'entry':str(entry),'installed_sha256':sha(installed),
         'backup':backup,'backup_sha256':sha(old),'backup_mode':mode,'target':str(target),'original_launcher':str(wrapper),
         'report':str(report),'package':key,'steam_launch_options':steam_options}
    state = checked_path(state_base/'activation.json',missing=True); previous = state.read_bytes() if state.exists() else None
    atomic_file(state,(json.dumps(s,indent=2)+'\n').encode())
    try: atomic_file(entry,installed,0o700)
    except BaseException:
        if previous is None: state.unlink(missing_ok=True)
        else: atomic_file(state,previous)
        raise
    print('\nlmxxf v13 is ready for: '+str(game))
    print('Steam launch options:\n'+steam_options)
    if not launch_options:
        print('If Steam already has other options, keep them and replace only the DLSS-NR launcher path.')
    print('Keep the same Proton runner selected in Steam.')
    print('Local report: '+str(report))
    if profile:
        print('GPU profiling is enabled for a bounded window after 120 neural frames.')
        print('The normal graph is restored automatically. Profile timings are not FPS.')
        print('GPU profile report: '+str(report.with_name('kernel-profile.txt')))
    print('Restore: python3 prepare.py --restore --game '+shlex.quote(str(game)))
    return s
def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--game', type=Path, help='Installed game folder, executable or .dlssnr-linux folder')
    p.add_argument('--weights', type=Path, help='Prepared lmxxf weights or conversion folder')
    p.add_argument('--profile', action='store_true', help='Collect a bounded in-game GPU kernel profile')
    p.add_argument('--restore', action='store_true', help='Restore the previous launcher for this game')
    p.add_argument('--launch-options', help='Current Steam launch options to preserve while replacing the launcher')
    a = p.parse_args(argv)
    try:
        base = Path.home()/'.local/share/dlssnr-linux/experiments/lmxxf-stage4'
        if a.game is None:
            if not sys.stdin.isatty():
                p.error('Use ./install.sh in a terminal, or pass --game \"/path/to/game\".')
            a = guided_setup(a, base)
        else:
            a.game = game_folder(a.game)
        if a.restore:
            state_base, entry = installation_paths(find_wrapper(a.game), base)
            restore(state_base, entry)
        else:
            prepare(a.game, a.weights, profile=a.profile, launch_options=a.launch_options)
    except (EOFError, KeyboardInterrupt):
        print('Cancelled. Run the installer again when ready.', file=sys.stderr); return 130
    except (RuntimeError,OSError,ValueError,KeyError,subprocess.SubprocessError) as e:
        print(f'lmxxf: {e}',file=sys.stderr); return 1
    return 0
if __name__ == '__main__': sys.exit(main())
