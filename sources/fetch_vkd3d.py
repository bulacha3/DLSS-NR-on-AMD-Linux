#!/usr/bin/env python3
"""Reconstruct the corresponding modified vkd3d source in a NEW directory.
Requires Git and network access; no builds, Wine or GPU execution.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

COMMIT = '35bdee1435c94f8c3548725fcb046595b263bd7e'
URL = 'https://github.com/HansKristian-Work/vkd3d-proton.git'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('destination', type=Path)
    args = parser.parse_args()
    target = args.destination.absolute()
    if target.exists():
        parser.error('destination must not exist (no existing checkout is modified)')
    sources = Path(__file__).resolve().parent
    provenance = json.loads((sources.parent / 'PROVENANCE.json').read_text())
    patch = sources / 'vkd3d-proton-ordered.patch'
    if hashlib.sha256(patch.read_bytes()).hexdigest() != provenance['vkd3d']['patch_sha256']:
        parser.error('patch checksum mismatch')
    subprocess.run(['git', 'clone', '--no-checkout', URL, str(target)], check=True)
    def git(*args):
        return subprocess.check_output(['git', '-C', str(target), *args], text=True)
    git('checkout', '--detach', COMMIT)
    if git('rev-parse', 'HEAD').strip() != COMMIT:
        raise RuntimeError('wrong source commit')
    git('submodule', 'update', '--init', '--recursive')
    for entry in json.loads((sources / 'vkd3d-submodules.json').read_text()):
        sha = subprocess.check_output(['git', '-C', str(target / entry['path']),
                                       'rev-parse', 'HEAD'], text=True).strip()
        if sha != entry['commit']:
            raise RuntimeError('wrong submodule commit: ' + entry['path'])
    git('apply', '--check', str(patch))
    git('apply', str(patch))
    print('Corresponding source ready:', target)
    print('No binaries built or executed.')


if __name__ == '__main__':
    main()
