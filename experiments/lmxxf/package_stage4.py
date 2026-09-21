#!/usr/bin/env python3
"""Build the candidate ZIP from its installation manifest."""
import argparse
import hashlib
import json
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parent / 'stage4'

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    manifest = json.loads((ROOT / 'package.json').read_text())
    if manifest.get('format') != 'lmxxf-stage4-package-v1' or manifest.get('revision') != 13:
        raise SystemExit('Expected the reviewed v13 manifest.')
    files = {}
    for name, expected in manifest['files'].items():
        path = Path(name)
        if path.is_absolute() or '..' in path.parts or any((ROOT/q).is_symlink() for q in (path,*path.parents)):
            raise SystemExit('Invalid package path: ' + name)
        data = (ROOT/path).read_bytes()
        if hashlib.sha256(data).hexdigest() != expected:
            raise SystemExit('Package file changed: ' + name)
        files[name] = data
    files['package.json'] = (ROOT/'package.json').read_bytes()
    with zipfile.ZipFile(args.output, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, data in sorted(files.items()):
            info = zipfile.ZipInfo('dlssnr-lmxxf/' + name, date_time=(2026,9,21,0,0,0))
            info.external_attr = (0o100755 if name.endswith('.sh') else 0o100644) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, data)
    print(hashlib.sha256(args.output.read_bytes()).hexdigest(), args.output)

if __name__ == '__main__':
    main()
