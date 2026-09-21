"""Filesystem helpers for the candidate installer."""
import os
from pathlib import Path
import tempfile

DEFAULT_GAME = Path.home()/'.local/share/Steam/steamapps/common/Cyberpunk 2077'

def checked_path(path, *, directory=False, missing=False):
    path = Path(os.path.abspath(path))
    for item in (path, *path.parents):
        if item.is_symlink():
            raise RuntimeError(f'Refusing symbolic link: {item}')
    if not missing or path.exists():
        if directory and not path.is_dir() or not directory and not path.is_file():
            raise RuntimeError(f'Unexpected file type or missing path: {path}')
    return path

def find_wrapper(game):
    game = checked_path(game, directory=True)
    if game.name == '.dlssnr-linux':
        choices = [game / 'launch.sh']
    else:
        # Bounded layouts used by the existing installer; never scan whole disks.
        choices = [game / '.dlssnr-linux/launch.sh', game / 'bin/x64/.dlssnr-linux/launch.sh']
        choices += list(game.glob('*/Binaries/Win64/.dlssnr-linux/launch.sh'))
        choices += [game / 'Retail/.dlssnr-linux/launch.sh']
    found = list(dict.fromkeys(p for p in choices if p.is_file()))
    if len(found) != 1:
        raise RuntimeError('Expected one installed mod. Use --game with the game folder or its .dlssnr-linux folder')
    return checked_path(found[0])

def atomic_file(path, data, mode=0o600):
    checked_path(path, missing=True)
    fd, name = tempfile.mkstemp(prefix='.preparing-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as file:
            file.write(data)
            file.flush()
            os.fsync(file.fileno())
        os.chmod(name, mode)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)
