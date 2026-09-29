"""Shared launcher migration support; no inference code or GPU initialization.

Extracted without changing function bodies from the project's legacy installer.
The legacy cache names are required to migrate existing users, not to activate it.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import shlex

DEFAULT_GAME = Path.home()/'.local/share/Steam/steamapps/common/Cyberpunk 2077'
def sha(data): return hashlib.sha256(data).hexdigest()

def checked_path(path, *, directory=False, missing=False):
    path = Path(os.path.abspath(path))
    for item in (path, *path.parents):
        if item.is_symlink():
            raise RuntimeError(f'Refusing symbolic link: {item}')
    if not missing or path.exists():
        if directory and not path.is_dir() or not directory and not path.is_file():
            raise RuntimeError(f'Unexpected file type or missing path: {path}')
    return path

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
