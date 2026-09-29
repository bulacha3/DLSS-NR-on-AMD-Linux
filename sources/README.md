# Build from source

For installation, use the prebuilt portable release and [installation guide](../docs/INSTALL.md).

Build requirements: Linux x86_64, GCC/G++, Git, Python 3.11+, Meson 1.12.0,
Ninja 1.13.2 and glslangValidator. The build downloads the pinned LLVM/MinGW
compiler and vkd3d-proton sources with checksum verification.

From the repository root:

```sh
python3 scripts/fetch-toolchain.py build-toolchain
export PATH="$PWD/build-toolchain/llvm-mingw-20260826-ucrt-ubuntu-22.04-x86_64/bin:$PATH"
bash scripts/build-components.sh
```

This rebuilds the Linux HIP bridge and patched D3D12 components and creates
`dist/dlssnr-linux-portable.tar.gz` and its checksum for the existing CI flow.
To create the ZIP distributed to users, run:

```sh
python3 build_release.py --components-root build/components --archive-format zip
```

This creates `dist/dlssnr-linux-portable.zip` and its `.sha256` file. The current package uses
the original upstream 0.4.3 inference backend; it does not require lmxxf GPU
modules or the private research tree to build or install.

Use `bash scripts/build-components.sh /path/to/new-build` for a new build directory.
Component origins, hashes, licenses and exact source pins are recorded in
[PROVENANCE.json](../PROVENANCE.json) and [THIRD-PARTY.md](../THIRD-PARTY.md).
Packaging is deterministic for identical inputs; different toolchains may
produce different binaries. A fresh build does not inherit gameplay validation
merely because it uses the same version number.
