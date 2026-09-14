# Build the experimental Linux v0.3.0 components

Use Linux x86_64, GCC, Git, Python 3.12+ for the build tools, Meson 1.12.0,
Ninja 1.13.2, and glslangValidator. The runtime installer needs Python 3.10+.
The GitHub Actions workflow performs these same steps.

Download the fixed LLVM/MinGW toolchain into a new directory:

```sh
python3 scripts/fetch-toolchain.py build-toolchain
export PATH="$PWD/build-toolchain/llvm-mingw-20260826-ucrt-ubuntu-22.04-x86_64/bin:$PATH"
bash scripts/build-components.sh
```

The toolchain download is authenticated using its published SHA-256. The build
script checks out vkd3d-proton commit
`35bdee1435c94f8c3548725fcb046595b263bd7e`, verifies the recorded submodule
commits and the patch digest, then builds all four components. Use a new build
directory for a clean build: `bash scripts/build-components.sh /path/to/new-build`.

Output: `dist/dlssnr-linux-portable.tar.gz` and its checksum.

## Runtime changes

The authentic guentra sources came from its experimental release archive,
SHA-256 `57b0b33caa79598ed33f23a6a7003f926059512ef48cd258fe8232781bef2d59`.
They include the actual Windows-to-Unix trampoline, external-memory bridge,
ordered submission logic and vkd3d patch.

The v0.3.0 trampoline exports all 33 required HIP functions, including
`hipEventCreateWithFlags`, `hipEventQuery`, `hipStreamCreateWithFlags` and
`hipStreamSynchronize`. Its changed table magic rejects the old layout.
Size arguments are explicitly 64 bits on Windows and Unix.

The exact original v0.3.0 synchronization shader has FNV-1 hash
`135ea1f88cbc832d`. Its root layout is UAV flags / four constants / UAV abortw.
The ordered patch retains its mode-0 producer dispatch and mode-2 status
dispatch. Repeated matching mode-1 wait slices share one producer/consumer split;
the original final status shader runs only in the consumer suffix, after the
HIP handoff completes. Token, frame, exact flag/abort addresses and repeated
wait constants must match. No upstream shader or native runtime bytes are patched.

This protocol is independently visible in the pinned v0.3.0 payload at RVAs
0x16b0c..0x16b62 (producer), 0x16c36..0x16cf0 (up to 4000 wait slices), and
0x16e71..0x16ec1 (final status). The DXBC mode-2 branch checks the HIP completion
word and updates success/failure status; suppressing it would hide failures.
The former two-mode parser incorrectly removed the device for a second wait
or any mode-2 dispatch. The diagnostic.2 user logs stop at queue claim, before
publishing captured input, consistently with that recording failure.

The HIP completion marker is launched on its original stream and synchronized
before releasing the D3D12 consumer. This initial integration is synchronous.
It does not implement an async Linux rendering path.

`diagnostic.4` adds an optional `GetDevice(ID3D12CommandQueue)` implementation
to the vkd3d DXGI presenter. `DLSSNR_SWAPCHAIN_QUEUE=1` returns the queue owned
by that exact swapchain with normal COM reference counting. All other IIDs,
and all calls without the option, retain upstream behavior. This supplies the
fallback used by the original NR DLL when a wrapper changes the swapchain's
identity between creation and presentation. It changes no NR binary, shader,
device-affinity check or ordered-handoff code. See the
[007 diagnosis](../docs/games/007-first-light.md).
The later 007 test confirms initialization and completed ordered neural jobs
when this option is combined with OptiScaler's `Inputs.EnableFfxInputs=false`
on its DLSS-to-FSR-3.1 route. The latter is a launch configuration change;
it does not require another D3D12 build.

## Validation

```sh
python3 -m unittest discover -s tests -v
gcc -std=gnu11 -O1 -g -fsanitize=address,undefined -fno-omit-frame-pointer \
  -pthread tests/native_contract.c -ldl -o build/native-contract
ASAN_OPTIONS=detect_leaks=0 ./build/native-contract
gcc -std=gnu11 -O1 -g -fsanitize=address,undefined -fno-omit-frame-pointer \
  -I /path/to/patched-vkd3d/libs/vkd3d \
  tests/vkd3d_ordered_contract.c -o build/vkd3d-contract
ASAN_OPTIONS=detect_leaks=0 ./build/vkd3d-contract
DLSSNR_TEST_SETUP=/path/to/official/setup.exe \
  DLSSNR_TEST_VKD3D_SOURCE=/path/to/patched-vkd3d \
  python3 -m unittest discover -s tests -v
```

The native failure test intentionally retains pins when simulated GPU
synchronization fails; leak detection is disabled for that deliberate quarantine.
The final Python test verifies real compiled exports, unchanged upstream
staging, archive determinism and absence of upstream payloads in the archive.
The vkd3d harness includes the actual patched `nr_ordered_commands.h`, with
mock Vulkan/bridge entry points, and replays both single-wait and 4000-slice
v0.3.0 sequences. It also rejects mismatched/unpaired operations and verifies
that a Vulkan prefix timeout cannot publish input, while HIP failure cannot
report a successful handoff. This is control-flow coverage, not a GPU test.
The swapchain regression extracts the actual `GetDevice` body from the pinned
Git source and the patched source, compiles both with COM mocks, and reproduces
the missing queue before the fix. It checks opt-in/default behavior, exact
queue identity across two devices and two queues on one device, reference
counting, preserved device/IUnknown queries, and propagated failures under
ASan/UBSan. The reconstructed checkout is required for this test.

Build output hashes are generated from the actual components. Determinism is
claimed for packaging identical inputs, not for arbitrary compilers or OS images.
No game, Wine conversion, AMD GPU, Vulkan/HIP interoperability or performance
validation was possible in the development environment. A subsequent
[Cyberpunk gameplay test](../docs/games/cyberpunk-2077.md) and
[007 gameplay test](../docs/games/007-first-light.md) validate neural
processing and the ordered GPU handoff on the tested AMD RDNA4 setup.
A subsequent [Atomic Heart test](../docs/games/atomic-heart.md)
passed with diagnostic.4 and the documented OptiScaler launch settings,
without another runtime or bridge change.
Those results do not validate every supported GPU or game.
