#!/usr/bin/env python3
"""Download and verify the fixed portable LLVM/MinGW toolchain."""
import hashlib
from pathlib import Path
import sys
import tarfile
import tempfile
import urllib.request

NAME = 'llvm-mingw-20260826-ucrt-ubuntu-22.04-x86_64'
URL = 'https://github.com/mstorsjo/llvm-mingw/releases/download/20260826/' + NAME + '.tar.xz'
SHA256 = 'cee8d2ce3da5145ce4dc882e70d0b0719a783d53a99752c60948fc0659975a65'
destination = Path(sys.argv[1]).resolve()
if destination.exists():
    raise SystemExit('Choose a new toolchain directory.')
with tempfile.TemporaryDirectory(prefix='dlssnr-compiler-') as temporary:
    archive = Path(temporary) / 'compiler.tar.xz'
    digest = hashlib.sha256()
    with urllib.request.urlopen(URL, timeout=60) as response, archive.open('wb') as output:
        while data := response.read(1024 * 1024):
            digest.update(data)
            output.write(data)
    if digest.hexdigest() != SHA256:
        raise SystemExit('Compiler checksum mismatch.')
    destination.mkdir(parents=True)
    with tarfile.open(archive) as source:
        source.extractall(destination, filter='data')
print(destination / NAME / 'bin')
