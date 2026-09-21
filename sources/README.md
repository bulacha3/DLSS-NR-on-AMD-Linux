# Build from source

For installation, use the portable release and [installation guide](../docs/INSTALL.md).

Build requirements: Linux x86_64, GCC/G++, Git, Python 3.11+, Meson 1.12.0,
Ninja 1.13.2 and glslangValidator. The script downloads a checksum-verified
LLVM/MinGW toolchain and the pinned vkd3d-proton sources.

From the repository root:

```sh
python3 scripts/fetch-toolchain.py build-toolchain
export PATH="$PWD/build-toolchain/llvm-mingw-20260826-ucrt-ubuntu-22.04-x86_64/bin:$PATH"
bash scripts/build-components.sh
```

This rebuilds the base Linux bridge and patched D3D12 components, then packages
them with the included lmxxf GPU modules and host source. Output:
`dist/dlssnr-linux-portable.tar.gz` and its checksum. To rebuild in a fresh
directory, run `bash scripts/build-components.sh /path/to/new-build`.

The optimized host bridge is compiled locally during installation. The command
above does not recompile its GPU modules. Their source generators, custom HIP
sources, compiler record and module checksums are retained under
`experiments/lmxxf/stage4/`; pinned upstream sources and module-build tools are
under `experiments/lmxxf/`.

Dependency revisions and component origins are recorded in
[PROVENANCE.json](../PROVENANCE.json). Source and license notices accompany the
release. Packaging is deterministic for identical inputs; rebuilding with a
different compiler need not produce identical binaries.
