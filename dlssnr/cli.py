"""English terminal interface for the per-game DLSS-NR installer."""
from __future__ import annotations

import argparse
from contextlib import ExitStack
import json
import os
from pathlib import Path
import platform
import subprocess
import sys

from . import assets, conversion, deploy, games, lmxxf, runtime, upstream

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
TARGETS = frozenset(('gfx1100', 'gfx1101', 'gfx1102', 'gfx1200', 'gfx1201'))


class InstallerCancelled(Exception):
    """A deliberate exit from an interactive selection."""


def parser():
    result = argparse.ArgumentParser(description='DLSS-NR on AMD Linux / Proton: per-game installer')
    commands = result.add_subparsers(dest='command')
    for name in ('list-games', 'list-protons'):
        command = commands.add_parser(name)
        command.add_argument('--steam-root', type=Path)
        command.add_argument('--json', action='store_true')
    for name in ('install', 'doctor', 'status', 'uninstall'):
        command = commands.add_parser(name)
        command.add_argument('--appid', help='Exact Steam application ID')
        command.add_argument('--exe', type=Path, help='Game Windows x64 executable')
        command.add_argument('--game-dir', type=Path, help='Game directory (default: directory containing install.sh)')
        command.add_argument('--steam-root', type=Path)
        command.add_argument('--json', action='store_true', help='Machine-readable JSON output')
        if name == 'uninstall':
            command.add_argument('--yes', action='store_true', help='Confirm restoring original files')
        if name in ('install', 'doctor'):
            command.add_argument('--runner', '--proton', dest='proton', type=Path,
                                 help='Installed Wine/Proton runner directory used by this game')
            command.add_argument('--confirm-runner', '--confirm-proton', dest='confirm_proton', action='store_true',
                                 help='Confirm this runner is used by your launcher or Wine command')
            command.add_argument('--gpu', help='HIP index or exact GPU name')
            command.add_argument('--hip-library', type=Path, help='Existing HIP7 library or SDK directory')
            command.add_argument('--data-dir', type=Path, help='Persistent user-local runtime/cache directory')
            command.add_argument('--install-rocm', action='store_true', help='Allow a verified AMD wheel download if needed')
            inputs = command.add_mutually_exclusive_group()
            inputs.add_argument('--weights', type=Path, help='Your existing DLSSNRW1 weights file')
            inputs.add_argument('--nvidia-dll', type=Path, help='Your legally obtained nvngx_dlssnr.dll (310.8.0.0)')
            command.add_argument('--accept-risk', action='store_true', help='Accept experimental injection risks')
            command.add_argument('--replace-existing', action='store_true', help='Back up and replace conflicting DLLs')
            command.add_argument('--allow-unconfirmed-loader', action='store_true',
                                 help='Allow installation without static evidence of mod loading; activation remains unverified')
            command.add_argument('--confirm-fsr', action='store_true',
                                 help='Confirm the game offers FSR 3 or FSR 4 when file inspection cannot detect it')
            command.add_argument('--setup', type=Path, help='Official v0.3.1 setup; otherwise downloaded and verified for installation')
            command.add_argument('--wait-method', choices=('compute', 'graphics'),
                                 help='Advanced override: default compute on new installs; updates keep the saved choice; graphics has a known 007 startup failure')
            command.add_argument('--dry-run', action='store_true', help='No writes, downloads or conversion')
            if name == 'install':
                command.add_argument('--launcher', choices=('steam', 'other'), help='Launcher used for this game')
                command.add_argument('--launch-options', help='Current complete Steam launch options; only the managed launcher is replaced')
    command = commands.add_parser('runtime', help='Check or install a user-local HIP7 runtime')
    command.add_argument('--hip-library', type=Path)
    command.add_argument('--data-dir', type=Path)
    command.add_argument('--install-rocm', action='store_true', help='Allow the pinned official AMD wheel')
    command.add_argument('--self-test', action='store_true', help='Explicit GPU memory-copy test (256 bytes)')
    command.add_argument('--json', action='store_true')
    return result


def choose(items, label, display):
    for index, item in enumerate(items, 1):
        print(f'  {index}. {display(item)}')
    answer = input(f'{label} (number; empty to cancel): ').strip()
    if not answer.isascii() or not answer.isdecimal() or not 1 <= int(answer) <= len(items):
        raise RuntimeError('Selection cancelled or invalid.')
    return items[int(answer) - 1]


def select_gpu(devices, requested, interactive):
    supported = [d for d in devices if d.get('arch', '').split(':', 1)[0] in TARGETS]
    if requested is not None:
        selected = [d for d in supported if str(d['index']) == requested or d['name'] == requested]
        if len(selected) == 1:
            return selected[0]
        raise RuntimeError('GPU missing, ambiguous or unsupported; use its exact HIP index with --gpu.')
    if len(supported) == 1:
        return supported[0]
    if not supported:
        raise RuntimeError('Unsupported GPU. Bundled targets: ' + ', '.join(sorted(TARGETS)))
    if interactive:
        return choose(supported, 'GPU', lambda d: f"HIP {d['index']}: {d['name']} ({d['arch']})")
    raise RuntimeError('Multiple compatible GPUs; select one explicitly with --gpu INDEX.')


def select_game_executable(root, explicit, interactive):
    """Keep ambiguity interactive for every game directory entry point."""
    try:
        return games.select_executable(root, explicit)
    except RuntimeError as exc:
        if not interactive or explicit is not None or not str(exc).startswith('Multiple possible executables'):
            raise
    root = Path(root).resolve()
    candidates = games.find_executables(root)
    print('Multiple executables found. Select the game itself, not a launcher or error reporter:')
    for index, candidate in enumerate(candidates, 1):
        print(f'  {index}. {candidate.relative_to(root)}')
    while True:
        answer = input('Game executable (number; empty to cancel): ').strip()
        if not answer:
            raise InstallerCancelled('No game selected; nothing installed.')
        if answer.isascii() and answer.isdecimal() and 1 <= int(answer) <= len(candidates):
            return games.select_executable(root, candidates[int(answer) - 1])
        print('Enter one of the listed numbers, or leave empty to cancel.')


def prompt_game_executable():
    print('Select the game folder or its Windows x64 .exe. Paths with spaces or surrounding quotes are accepted.')
    while True:
        entered = input('Game directory or .exe path (empty to cancel): ').strip()
        # Literal path input: never evaluate shell syntax or split embedded spaces.
        if len(entered) >= 2 and entered[0] == entered[-1] and entered[0] in ('"', "'"):
            entered = entered[1:-1]
        if not entered:
            raise InstallerCancelled('No game selected; nothing installed.')
        try:
            path = Path(entered).expanduser().absolute()
            return select_game_executable(path if path.is_dir() else path.parent,
                                          None if path.is_dir() else path, True)
        except (RuntimeError, OSError, ValueError) as exc:
            print(f'{exc}\nTry another game directory or .exe path, or leave empty to cancel.')


def menu_choice(prompt, choices):
    for key, label in choices.items():
        print(f'  {key}. {label}')
    while True:
        value = input(prompt + ' (number; empty to cancel): ').strip()
        if not value or value.casefold() == 'q':
            raise InstallerCancelled('Setup cancelled; nothing installed.')
        if value in choices:
            return value
        print('Choose a number from the list, or leave empty to cancel.')


def guided_game(args):
    print('1/5 — Launcher')
    if args.launcher is None:
        choice = menu_choice('Where do you launch this game?', {
            '1': 'Steam (including a game added as a non-Steam shortcut)',
            '2': 'Another launcher, such as Lutris, Heroic, or a Wine/Proton command'})
        args.launcher = 'steam' if choice == '1' else 'other'
    print('Launcher:', 'Steam' if args.launcher == 'steam' else 'Other launcher')
    print('\n2/5 — Game')
    if args.exe or args.game_dir or args.appid:
        return
    if args.launcher == 'steam':
        entries = games.discover_games(args.steam_root)
        if entries:
            options = {str(i): f"{entry['name']} — {entry['path']}" for i, entry in enumerate(entries, 1)}
            options['0'] = 'Browse by pasting a game folder or .exe path (also for non-Steam shortcuts)'
            selected = menu_choice('Select the game', options)
            if selected != '0':
                args.game_dir = Path(entries[int(selected) - 1]['path'])
                return
        else:
            print('No Steam library games found. Enter the game folder or executable below.')
    args._manual_game = True


def guided_upscaler(args, evidence):
    print('\n4/5 — Upscaling')
    print('DLSS-NR needs an FSR 3/4 processing path. Which route is configured for this game?')
    choice = menu_choice('Upscaler route', {
        '1': 'Native FSR 3 or FSR 4 in the game settings',
        '2': 'OptiScaler already configured: DLSS input with an FSR 3/4 backend',
        '3': 'Not sure / not configured yet'})
    if choice == '3':
        print('Check the game settings for FSR 3/4, or configure OptiScaler using the game setup guide.')
        print('Game setup guides: https://github.com/bulacha3/DLSS-NR-on-AMD-Linux#tested-games')
        raise InstallerCancelled('Confirm a supported upscaler route before installing.')
    args.confirm_fsr = True
    args._upscaler_route = 'native' if choice == '1' else 'optiscaler'
    if choice == '1':
        print('In the game, select FSR 3/4. Keep your preferred Quality or Balanced mode.')
    else:
        print('In the game, select DLSS; keep OptiScaler set to an FSR 3/4 backend.')
        print('This installer preserves your existing OptiScaler setup; it does not install or configure OptiScaler.')


def resolve_exe(args, interactive):
    if interactive and getattr(args, '_manual_game', False):
        return prompt_game_executable()
    if args.appid and (not args.appid.isascii() or not args.appid.isdecimal()):
        raise RuntimeError('--appid must be an exact numeric Steam ID.')
    if args.appid:
        if args.game_dir:
            raise RuntimeError('--game-dir and --appid cannot be combined.')
        entries = games.discover_games(args.steam_root)
        entries = [g for g in entries if g['appid'] == args.appid]
        if len(entries) != 1:
            raise RuntimeError('AppID missing or ambiguous; use --steam-root or --exe without --appid.')
        return select_game_executable(entries[0]['path'], args.exe, interactive)
    if args.exe and not args.game_dir:
        path = args.exe.expanduser().absolute()
        if path.is_symlink():
            raise RuntimeError('The game executable must not be a symlink.')
        return games.select_executable(path.parent, path)
    root = args.game_dir.expanduser().absolute() if args.game_dir else PACKAGE_ROOT
    # The release may be extracted as a subfolder instead of flattened into the game.
    # Never climb arbitrary ancestors or search the user's other games implicitly.
    if not args.game_dir and root.name == 'dlssnr-linux-portable':
        root = root.parent
    try:
        return select_game_executable(root, args.exe, interactive)
    except RuntimeError as exc:
        if not interactive or args.exe or not str(exc).startswith('No PE x64 executable found'):
            raise
    return prompt_game_executable()


def require(accepted, interactive, question, flag):
    if accepted:
        return
    if interactive and input(question + ' [y/N] ').strip().casefold() in ('y', 'yes'):
        return
    raise RuntimeError(f'Explicit confirmation required: {flag}. {question}')


def data_dir(args):
    base = args.data_dir or Path(os.environ.get('XDG_DATA_HOME') or Path.home() / '.local/share') / 'dlssnr-linux'
    base = Path(base).expanduser()
    if not base.is_absolute():
        raise RuntimeError('--data-dir / XDG_DATA_HOME must be absolute.')
    return base


def check_host(manifest):
    if platform.system() != 'Linux' or platform.machine() != 'x86_64':
        raise RuntimeError('This package requires Linux x86_64.')
    name, version = platform.libc_ver()
    minimum = tuple(map(int, manifest.get('minimum_glibc', '2.34').split('.')))
    if name != 'glibc' or tuple(map(int, version.split('.'))) < minimum:
        raise RuntimeError('glibc >= ' + '.'.join(map(str, minimum)) + ' is required by the prebuilt bridge.')
    if os.geteuid() == 0:
        raise RuntimeError('Do not run this installer as sudo/root; use the game owner account.')
    return {'system': platform.system(), 'machine': platform.machine(), 'glibc': version}


def _available_protons(args):
    valid, errors = [], []
    for candidate in games.discover_protons(args.steam_root):
        try:
            valid.append(games.validate_proton(candidate))
        except RuntimeError as exc:
            errors.append(str(exc))
    return valid, errors


def resolve_proton(args, interactive):
    if args.proton:
        try:
            return games.validate_proton(args.proton)
        except RuntimeError as exc:
            if not interactive:
                raise
            print(str(exc))
    if interactive:
        if getattr(args, '_guided', False) and args.launcher == 'steam':
            valid, errors = _available_protons(args)
            for error in errors:
                print('Skipped runner:', error)
            print('Use the runner selected in Steam > Properties > Compatibility for this game.')
            if valid:
                choices = {str(i): str(runner['root']) for i, runner in enumerate(valid, 1)}
                choices['0'] = 'Enter another Wine/Proton directory'
                selected = menu_choice('Wine/Proton runner', choices)
                if selected != '0':
                    return valid[int(selected) - 1]
            else:
                print('No compatible Steam runners found. Enter your installed runner folder below.')
        print('Enter the Wine/Proton runner directory used by this game.\n\n'
              'Examples:\n'
              '  Steam:  ~/.local/share/Steam/compatibilitytools.d/GE-Proton...\n'
              '  Lutris: ~/.local/share/lutris/runners/wine/wine-ge-...\n\n'
              "Select the runner's folder, not its bin/wine executable.\n"
              'Type "steam" to list Steam runners, or leave empty to cancel.\n')
        while True:
            entered = input('Runner directory: ').strip()
            if len(entered) >= 2 and entered[0] == entered[-1] and entered[0] in ('"', "'"):
                entered = entered[1:-1]
            if not entered:
                raise InstallerCancelled('No Wine/Proton runner selected; nothing installed.')
            if entered.casefold() != 'steam':
                try:
                    return games.validate_proton(Path(entered).expanduser())
                except RuntimeError as exc:
                    print(str(exc))
                    continue
            valid, errors = _available_protons(args)
            for error in errors:
                print('Skipped runner:', error)
            if not valid:
                print('No compatible Steam runners found. Enter your runner directory, or leave empty to cancel.')
                continue
            print('Compatible Steam runners (user libraries and system installations):')
            for index, runner in enumerate(valid, 1):
                print(f"  {index}. {runner['root']}")
            print('  0. Enter another Wine/Proton directory')
            while True:
                choice = input('Runner number (empty to cancel): ').strip()
                if not choice:
                    raise InstallerCancelled('No Wine/Proton runner selected; nothing installed.')
                if choice == '0':
                    break
                if choice.isascii() and choice.isdecimal() and 1 <= int(choice) <= len(valid):
                    return valid[int(choice) - 1]
                print('Choose a number from the list, or leave empty to cancel.')
    if not args.appid and not args.steam_root:
        raise RuntimeError('Specify --runner /path/to/runner (alias: --proton). Steam discovery is optional.')
    valid, errors = _available_protons(args)
    if len(valid) == 1:
        return valid[0]
    raise RuntimeError('Specify --runner /path/to/runner; multiple candidates or none compatible.\n' + '\n'.join(errors))


def confirm_runner(args, proton, interactive):
    if args.confirm_proton:
        return proton
    if not interactive:
        require(False, False, f"Does your launcher or Wine command use {proton['root']} for this game?",
                '--confirm-runner (alias: --confirm-proton)')
    print('Confirm the runner configured for this game: y = yes, n = choose another, q = cancel.')
    while True:
        answer = input(f"Does your launcher use {proton['root']} for this game? [y/N/q] ").strip().casefold()
        if answer in ('y', 'yes', 's', 'sim'):
            return proton
        if answer in ('q', 'quit', 'cancel', 'cancelar'):
            raise InstallerCancelled('Runner confirmation cancelled; nothing installed.')
        if answer in ('', 'n', 'no', 'nao', 'não'):
            print('Select the Wine/Proton runner actually configured in your launcher.')
            selection = argparse.Namespace(**vars(args))
            selection.proton = None
            proton = resolve_proton(selection, True)
        else:
            print('Please answer y to confirm, n to choose another runner, or q to cancel.')


def readonly_runtime(args):
    supplied = args.hip_library.expanduser().absolute() if args.hip_library else None
    if supplied and not supplied.is_dir():
        candidates = [supplied]
    else:
        candidates = runtime.discover_runtimes([supplied] if supplied else None,
                                               managed_root=data_dir(args) / 'rocm-venv')
        if supplied:
            candidates = [p for p in candidates if p.resolve().is_relative_to(supplied.resolve())]
    errors = []
    for candidate in candidates:
        try:
            return runtime.probe_runtime(candidate)
        except runtime.DriverUnavailable:
            raise
        except RuntimeError as exc:
            errors.append(str(exc))
    raise RuntimeError('HIP7 unavailable; doctor/--dry-run never download. '
                       'Use runtime --install-rocm or --hip-library.\n' + '\n'.join(errors))


def ensure_runtime(args, interactive):
    try:
        return runtime.ensure_runtime(data_dir(args), supplied=args.hip_library, allow_install=args.install_rocm)
    except runtime.DriverUnavailable:
        raise
    except RuntimeError as exc:
        if not interactive or args.hip_library or args.install_rocm or '--install-rocm' not in str(exc):
            raise
        print(str(exc))
        require(False, True, 'Download the pinned official AMD HIP7 wheel into your user directory (3 GiB free required)?', '--install-rocm')
        return runtime.ensure_runtime(data_dir(args), allow_install=True)


def emit(result, args):
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
        return
    if args.command == 'runtime':
        print('HIP7 verified:', result['library'])
        for device in result['devices']:
            print(f"  HIP {device['index']}: {device['name']} ({device['arch']})")
        print('GPU copy test:', 'completed' if args.self_test else 'not requested')
        return
    if args.command == 'doctor':
        print('Static and HIP prerequisites checked. No files modified.')
        print('Game:', result['game']['exe'])
        print('HIP:', result['runtime']['library'])
        print('GPU:', result['gpu']['name'])
        print('Checked Wine/Proton runner:', result['proton']['root'])
        for warning in result.get('warnings', []):
            print('Warning:', warning)
        print('Actual launcher/runner selection and in-game rendering are NOT verified.')
        return
    if result.get('dry_run'):
        print('Dry run completed; nothing installed.')
    elif result.get('updated') and result.get('valid'):
        print('Installation updated. Original backups and visual settings retained.')
    elif result.get('installed') and result.get('valid'):
        print('Installation verified.')
    elif result.get('installed') or result.get('pending'):
        print('Installation needs attention; read diagnostics before making changes.')
    else:
        print('No active managed installation.')
    if result.get('exe'):
        print('Game:', result['exe'])
    if result.get('proton'):
        print('Use this Wine/Proton runner in your launcher:', result['proton'])
    launcher = getattr(args, 'launcher', None)
    if result.get('launch_options') and launcher != 'other':
        print('\nSteam > Properties > General > Launch Options: replace that field with this complete line:')
        print(result['launch_options'])
    if result.get('command_prefix') and launcher != 'steam':
        print('\nIn your launcher, set this command prefix and keep the current runner, environment and game arguments:')
        print(result['command_prefix'])
        print('Do not add Steam\'s %command% token to this command prefix.')
    if result.get('valid'):
        route = getattr(args, '_upscaler_route', None)
        if route == 'native':
            print('In the game: select FSR 3/4. End opens the DLSS-NR menu.')
        elif route == 'optiscaler':
            print('In the game: select DLSS; OptiScaler must output FSR 3/4. Insert opens OptiScaler; End opens DLSS-NR.')
        else:
            print('Use the upscaler from the game setup guide. End opens the DLSS-NR menu.')
    if result.get('backend') == 'lmxxf':
        print('Optimized Linux backend installed. Model data will be reused for other games.')
    for warning in result.get('warnings', []):
        print('Warning:', warning)
    for note in result.get('notes', []):
        print('-', note)
    if args.command == 'uninstall':
        print('Remove the wrapper from your launcher command prefix or Steam launch options. Shared ROCm/bridge caches are retained.')


def candidate_weights(args, interactive):
    lmxxf.preflight(data_dir(args))
    api, root = lmxxf.backend(PACKAGE_ROOT)
    api.package_manifest(root)
    found = lmxxf.cached_weights(PACKAGE_ROOT, data_dir(args))
    if found:
        return found
    dll = args.nvidia_dll or lmxxf.remembered_dll(data_dir(args))
    if dll is None and interactive:
        entered = input('Path to your original NVIDIA model DLL (empty to cancel): ').strip()
        if not entered:
            raise InstallerCancelled('No model selected; nothing installed.')
        dll = Path(entered).expanduser()
    return lmxxf.prepare_weights(PACKAGE_ROOT, data_dir(args), dll, quiet=args.json)


def update_existing_candidate(args, exe, interactive):
    # Explicit base changes retain the normal installation path. Otherwise the
    # verified original launcher already contains all runtime/GPU selections.
    if (args.command != 'install' or args.dry_run or
            any(getattr(args, k, None) for k in ('proton', 'gpu', 'hip_library', 'setup', 'wait_method', 'weights'))):
        return None
    saved = lmxxf.existing_runtime(exe)
    if saved is None:
        return None
    if deploy.running_game(exe):
        raise RuntimeError('Close the game before installation.')
    rt = runtime.probe_runtime(Path(saved['DLSSNR_HIP_LIBRARY']))
    gpu = select_gpu(rt['devices'], saved['VKD3D_FILTER_DEVICE_NAME'], False)
    if not lmxxf.supported(gpu):
        return None
    if not args.json:
        print('Reusing this game’s verified installation, runtime and model data.')
    prepared = candidate_weights(args, interactive)
    if getattr(args, 'launcher', None) != 'other':
        if getattr(args, '_guided', False):
            print('\n5/5 — Steam launch configuration')
        args.launch_options = lmxxf.launch_options(PACKAGE_ROOT, data_dir(args), exe,
                                                  args.launch_options, interactive=interactive)
    elif getattr(args, '_guided', False):
        print('\n5/5 — Launcher configuration\nThe final command prefix will be printed after the update.')
    result = lmxxf.activate(PACKAGE_ROOT, data_dir(args), exe, prepared,
                            launch_options=args.launch_options, quiet=args.json)
    return dict(deploy.status_game(exe), **result, updated=True, exe=exe)


def main(argv=None):
    arguments = list(sys.argv[1:] if argv is None else argv)
    if not arguments and not sys.stdin.isatty():
        print('Usage: install --exe /path/game.exe; see --help.', file=sys.stderr)
        return 2
    args = parser().parse_args(arguments or ['install'])
    interactive = sys.stdin.isatty() and not args.json
    args._guided = interactive and args.command == 'install' and not args.dry_run
    contexts = ExitStack()
    package_root = PACKAGE_ROOT
    try:
        manifest = None
        if args.command == 'install':
            manifest = assets.verify_assets(PACKAGE_ROOT)
            assets.require_deployable(manifest)
            if args.dry_run:
                if args.setup:
                    upstream.read_setup(args.setup)
            if not args.json:
                print('DLSS-NR Linux installer:', manifest.get('version', 'unknown'))
                print('Mod to install: DLSS-NR on AMD', manifest.get('mod_version', 'unknown'))
                print()
        if args.command in ('list-games', 'list-protons'):
            if args.command == 'list-games':
                rows = games.discover_games(args.steam_root)
            else:
                rows = []
                for candidate in games.discover_protons(args.steam_root):
                    try:
                        games.validate_proton(candidate)
                        rows.append({'path': candidate, 'compatible': True})
                    except RuntimeError as exc:
                        rows.append({'path': candidate, 'compatible': False, 'reason': str(exc)})
            if args.json:
                print(json.dumps(rows, indent=2, ensure_ascii=False, default=str))
            else:
                for row in rows:
                    print(f"{row.get('appid', 'OK' if row.get('compatible') else 'INCOMPATIBLE')}  {row.get('name', '')}  {row['path']}")
                    if row.get('reason'):
                        print('  ' + row['reason'])
                if not rows:
                    print('No entries found. Use --steam-root or an explicit --exe / --proton path.')
            return 0
        if args.command == 'runtime':
            check_host({})
            rt = ensure_runtime(args, interactive)
            if args.self_test:
                rt = runtime.probe_runtime(rt['library'], self_test=True)
            emit(rt, args)
            return 0
        if args._guided:
            guided_game(args)
        if getattr(args, 'launcher', None) == 'other' and getattr(args, 'launch_options', None) is not None:
            raise RuntimeError('--launch-options is for Steam. Keep other-launcher arguments in that launcher.')
        exe = resolve_exe(args, interactive)
        if args.command == 'status':
            status = deploy.status_game(exe)
            emit(status, args)
            return 1 if status['pending'] else 0
        if args.command == 'uninstall':
            require(args.yes, interactive, 'Restore original files and uninstall?', '--yes')
            result = deploy.uninstall_game(exe)
            actual = deploy.status_game(exe)
            if actual['installed'] or actual['pending']:
                raise RuntimeError('Restore incomplete; retain all backups and the journal.')
            emit(result, args)
            return 0
        if manifest is None:
            manifest = assets.verify_assets(PACKAGE_ROOT)
        host = check_host(manifest)
        evidence = games.inspect_game(exe)
        if evidence['anti_cheat_evidence']:
            raise RuntimeError('Anti-cheat detected: refusing installation, no bypass. ' + ', '.join(evidence['anti_cheat_evidence']))
        if not evidence['dx12']:
            raise RuntimeError('No static DirectX 12 evidence found; automatic installation is not supported for this game.')
        if args.command == 'install' and not interactive:
            updated = update_existing_candidate(args, exe, False)
            if updated is not None:
                emit(updated, args)
                return 0
        if args._guided:
            print('Game executable:', exe)
            print('\n3/5 — Wine/Proton runner')
            print('Keep the runner already used by your launcher. This setup does not change the launcher\'s selection.')
        proton = resolve_proton(args, interactive)
        if args.command == 'install':
            proton = confirm_runner(args, proton, interactive)
        if args._guided:
            guided_upscaler(args, evidence)
        fsr_warnings = []
        evidence['fsr_confirmed_by_user'] = False
        if not evidence['fsr_evidence']:
            fsr_warnings.append('FSR was not detected in file or import names. It may be built into the game. '
                                'FSR detection or confirmation does not verify that the mod works in this game.')
            if args.command == 'install':
                require(args.confirm_fsr, interactive,
                        'FSR was not detected automatically. Does this game offer FSR 3 or FSR 4 upscaling '
                        '(confirmed in its settings or official documentation)?', '--confirm-fsr')
                evidence['fsr_confirmed_by_user'] = True
        loader_warnings = [] if evidence['version_loader'] else [
            'Mod loading is not confirmed by static imports. Dynamic loading may exist; '
            'copying version.dll alone does not guarantee activation.']
        if args.command == 'doctor':
            rt = readonly_runtime(args)
            gpu = select_gpu(rt['devices'], args.gpu, interactive)
            report = {'host': host, 'game': evidence, 'proton': proton, 'runtime': rt, 'gpu': gpu,
                      'gameplay_verified': False, 'steam_selection_verified': False, 'runner_selection_verified': False,
                      'warnings': fsr_warnings + loader_warnings}
            if args.weights:
                report['weights'] = assets.validate_weights(args.weights.expanduser())
            emit(report, args)
            return 0
        updated = update_existing_candidate(args, exe, interactive) if interactive else None
        if updated is not None:
            emit(dict(updated, proton=proton['root']), args)
            return 0
        if loader_warnings:
            require(args.allow_unconfirmed_loader, interactive,
                    loader_warnings[0] + ' Install anyway and verify mod loading in the game log?',
                    '--allow-unconfirmed-loader')
        if interactive:
            print('Game executable:', exe)
        require(args.accept_risk, interactive, 'Experimental injection may crash, render incorrectly or trigger anti-cheat. Continue?', '--accept-risk')
        if deploy.running_game(exe):
            raise RuntimeError('Close the game before installation.')
        rt = readonly_runtime(args) if args.dry_run else ensure_runtime(args, interactive)
        gpu = select_gpu(rt['devices'], args.gpu, interactive)
        if not args.dry_run:
            if not args.json and args.setup is None:
                print('Downloading and verifying the official v0.3.1 setup (about 8 MB)...')
            package_root = contexts.enter_context(upstream.prepared_package(PACKAGE_ROOT, args.setup))
        weights = args.weights.expanduser() if args.weights else exe.parent / deploy.WEIGHTS
        if not args.weights and not args.nvidia_dll and not weights.is_file():
            cached = data_dir(args)/'weights'/conversion.KNOWN_NVIDIA_SHA/deploy.WEIGHTS
            if cached.exists() or cached.is_symlink():
                cached = deploy._safe(cached)
                assets.validate_weights(cached)
                weights = cached
        if not args.weights and not args.nvidia_dll and not weights.is_file():
            roots = [exe.parent]
            if exe.parent.name.lower() == 'win64' and exe.parent.parent.name.lower() == 'binaries':
                roots.append(exe.parent.parent.parent.parent)
            local_root = args.game_dir or (PACKAGE_ROOT.parent if PACKAGE_ROOT.name == 'dlssnr-linux-portable' else PACKAGE_ROOT)
            local_root = local_root.expanduser().resolve()
            if exe.is_relative_to(local_root):
                roots.append(local_root)
            for root in dict.fromkeys(roots):
                for name in ('nvngx_dlssnr.dll', 'nvngx_dlss.dll'):
                    candidate = root / name
                    if candidate.is_file() and not candidate.is_symlink() and assets.sha256(candidate) == conversion.KNOWN_NVIDIA_SHA:
                        args.nvidia_dll = candidate
                        if not args.json:
                            print('Detected supported NVIDIA model DLL.')
                        break
                if args.nvidia_dll:
                    break
            if args.nvidia_dll is None:
                args.nvidia_dll = lmxxf.remembered_dll(data_dir(args))
        if not args.weights and not args.nvidia_dll and not weights.is_file() and interactive:
            path = input('Path to your NVIDIA model DLL or existing weights file (empty to cancel): ').strip()
            if not path:
                raise RuntimeError('No weights selected; nothing installed.')
            supplied = Path(path).expanduser()
            if supplied.suffix.lower() == '.dll':
                args.nvidia_dll = supplied
            else:
                weights = supplied
        if args.nvidia_dll:
            if args.dry_run:
                raise RuntimeError('--dry-run cannot convert a DLL; provide existing converted weights with --weights.')
            weights = conversion.convert_weights(package_root, args.nvidia_dll, proton, data_dir(args))
        assets.validate_weights(weights)
        if args.dry_run:
            emit({'dry_run': True, 'exe': exe, 'gpu': gpu, 'proton': proton['root'],
                  'fsr_confirmed_by_user': evidence['fsr_confirmed_by_user'],
                  'warnings': fsr_warnings + loader_warnings,
                  'notes': ['Prerequisites checked; no download, staging or game deployment was performed.']}, args)
            return 0
        prepared = candidate_weights(args, interactive) if lmxxf.supported(gpu) else None
        if getattr(args, 'launcher', None) != 'other':
            if args._guided:
                print('\n5/5 — Steam launch configuration')
            args.launch_options = lmxxf.launch_options(PACKAGE_ROOT, data_dir(args), exe,
                                                      args.launch_options, interactive=interactive,
                                                      original_backend=prepared is None)
        elif args._guided:
            print('\n5/5 — Launcher configuration\nThe final launch instructions will be printed after installation.')
        conflicts = [name for name in deploy.DLLS if (exe.parent / name).exists()]
        replace = args.replace_existing
        if conflicts and not replace and not (exe.parent / deploy.STORE).exists():
            require(False, interactive, 'Back up and replace existing files: ' + ', '.join(conflicts) + '?', '--replace-existing')
            replace = True
        result = deploy.install_game(exe, package_root, rt, gpu, proton, weights,
                                     acknowledge_risk=True, replace_existing=replace, dry_run=args.dry_run,
                                     wait_method=args.wait_method)
        if prepared is None and args.launch_options is not None:
            result['launch_options'] = args.launch_options
        candidate_failed = False
        if prepared is not None:
            try:
                if not args.json:
                    print('Preparing the optimized Linux backend...', flush=True)
                result.update(lmxxf.activate(PACKAGE_ROOT, data_dir(args), exe, prepared,
                                             launch_options=args.launch_options, quiet=args.json))
            except (RuntimeError, OSError, ValueError, subprocess.SubprocessError) as exc:
                candidate_failed = True
                result['backend'] = 'original'
                if args.launch_options is not None:
                    result['launch_options'] = lmxxf.launch_options(
                        PACKAGE_ROOT, data_dir(args), exe, args.launch_options, original_backend=True)
                result['warnings'] = ['The optimized backend was not activated: '+str(exc),
                                      'The base installation is valid. Use the base launch command below until preparation succeeds.']
        else:
            result['backend'] = 'original'
            result['notes'] = [*result.get('notes', []), 'This GPU uses the original backend; the bundled optimized kernels target gfx1201.']
        emit(dict(result, exe=exe, gpu=gpu, proton=proton['root'],
                  loader_evidence=evidence.get('loader_evidence', []),
                  fsr_confirmed_by_user=evidence['fsr_confirmed_by_user'],
                  mod_loading_verified=False,
                  warnings=fsr_warnings + loader_warnings + result.get('warnings', [])), args)
        return 2 if candidate_failed else 0
    except InstallerCancelled as exc:
        print(f'Cancelled: {exc}')
        return 130
    except (RuntimeError, OSError, ValueError, subprocess.SubprocessError) as exc:
        print(f'Error: {exc}', file=sys.stderr)
        return 2
    except (EOFError, KeyboardInterrupt):
        print('Cancelled. Run status before your next operation.', file=sys.stderr)
        return 130
    finally:
        contexts.close()
