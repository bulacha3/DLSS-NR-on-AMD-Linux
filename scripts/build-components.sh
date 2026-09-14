#!/usr/bin/env bash
set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"
export SOURCE_DATE_EPOCH=1789171200
build="${1:-$root/build}"
mkdir -p "$build/components" "$build/trampoline"
gcc -std=gnu11 -O2 -fPIC -shared -pthread -mtls-dialect=gnu \
  -Werror=incompatible-pointer-types native/hip_bridge.c -ldl \
  -o "$build/components/libdlssnr_hip_bridge.so"
llvm-dlltool -m i386:x86-64 -d sources/trampoline/kernel32.def -l "$build/trampoline/kernel32.lib"
llvm-dlltool -m i386:x86-64 -d sources/trampoline/ntdll.def -l "$build/trampoline/ntdll.lib"
clang --target=x86_64-pc-windows-msvc -O2 -fno-stack-protector \
  -c sources/trampoline/amdhip64_7_pe.c -o "$build/trampoline/amdhip64_7.obj"
lld-link /dll /entry:DllMain /nodefaultlib /machine:x64 /timestamp:0 \
  "/out:$build/components/amdhip64_7.dll" "$build/trampoline/amdhip64_7.obj" \
  "$build/trampoline/kernel32.lib" "$build/trampoline/ntdll.lib"
python3 sources/fetch_vkd3d.py "$build/vkd3d-source"
meson setup "$build/vkd3d" "$build/vkd3d-source" --cross-file sources/cross-win64.ini \
  --buildtype release -Denable_tests=false -Denable_extras=false \
  -Denable_profiling=false -Denable_renderdoc=false -Denable_descriptor_qa=false \
  -Denable_extended_emulation=false -Denable_trace=false
ninja -C "$build/vkd3d" -j "${JOBS:-2}"
cp "$build/vkd3d/libs/d3d12/d3d12.dll" "$build/components/"
cp "$build/vkd3d/libs/d3d12core/d3d12core.dll" "$build/components/"
python3 build_release.py --components-root "$build/components"
