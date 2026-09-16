# Build the experimental Linux 0.3.1 integration

Use Linux x86_64, GCC, Git, Python 3.12+, Meson 1.12.0, Ninja 1.13.2 and glslangValidator. The installed runtime needs Python 3.10+. GitHub Actions runs the same build and validation steps.

```sh
python3 scripts/fetch-toolchain.py build-toolchain
export PATH="$PWD/build-toolchain/llvm-mingw-20260826-ucrt-ubuntu-22.04-x86_64/bin:$PATH"
bash scripts/build-components.sh
```

The toolchain archive, vkd3d-proton commit, submodules and patch are pinned and verified. Use `bash scripts/build-components.sh /path/to/new-build` for a clean component build. Output: `dist/dlssnr-linux-portable.tar.gz` and its checksum.

## Source and runtime

The original guentra native/trampoline sources came from its experimental release archive, identified in [PROVENANCE.json](../PROVENANCE.json). Original notices are retained; see [THIRD-PARTY.md](../THIRD-PARTY.md).

The Windows-to-Unix trampoline exports all 33 HIP functions required by the pinned upstream 0.3.1 runtime, including its delay-loaded imports. The bridge uses ABI 2 and ordered submission ABI 3. The upstream runtime and shaders are used without byte modifications.

The D3D12 patch recognizes the exact upstream compute wait shader (`135ea1f88cbc832d`), graphics pixel shader (`9b67a44ca79c547f`) and vertex shader (`97c89ca9f5ead0f9`). It retains the original mode-0 producer and mode-2 status dispatches. Repeated matching wait slices share one producer/consumer split; the status shader runs after HIP completion. Token, frame, flag/abort addresses and wait constants must match. Unrelated game draws are untouched.

Both compute and graphics use the Linux ordered handoff; this is not the Windows GPU polling implementation. The HIP completion marker runs on its original stream, which is synchronized before releasing the D3D12 consumer. Async is unsupported; the installer enforces `Async=0` and `CpuWait=0`.

**Compute (`SpinDraw=0`) is the new-install default.** Graphics is an advanced opt-in: it worked in the tested Cyberpunk and Atomic Heart configurations but caused device loss in 007 First Light 1.2.0. The same 007 configuration worked after selecting compute. Updates preserve the saved method; no crash-triggered retry is implemented.

`DLSSNR_SWAPCHAIN_QUEUE=1` enables the optional `GetDevice(ID3D12CommandQueue)` fallback in the DXGI presenter. It returns only the queue owned by that swapchain, with normal COM reference counting. Other IIDs and calls without the option retain upstream behavior. [007 profile](../docs/games/007-first-light.md).

## Validation

After building, use the original official 0.3.1 setup as the fixture:

```sh
DLSSNR_TEST_SETUP=/path/to/dlssnr_on_amd_setup.exe \
  DLSSNR_TEST_VKD3D_SOURCE=build/vkd3d-source \
  python3 -m unittest discover -s tests -v

gcc -std=gnu11 -O1 -g -fsanitize=address,undefined -fno-omit-frame-pointer \
  -pthread tests/native_contract.c -ldl -o build/native-contract
ASAN_OPTIONS=detect_leaks=0 ./build/native-contract

gcc -std=gnu11 -O1 -g -fsanitize=address,undefined -fno-omit-frame-pointer \
  -I build/vkd3d-source/libs/vkd3d tests/vkd3d_ordered_contract.c \
  -o build/vkd3d-contract
ASAN_OPTIONS=detect_leaks=0 ./build/vkd3d-contract
```

Tests cover installer defaults, saved choices, update/rollback/uninstall, exact upstream staging, deterministic packaging and exclusion of upstream/NVIDIA files. The actual upstream recording function is replayed with mock COM objects for compute and graphics (1/64/4000 waits) against the patched header under ASan/UBSan. Malformed sequences, failure propagation and resource retention are covered separately. The swapchain test compares the original and patched function with COM mocks.

The native failure test deliberately retains resource pins when simulated GPU synchronization fails; leak detection is disabled for that quarantine. These CPU tests do not prove GPU stability or validate the upstream memory-leak fix.

Gameplay with the documented [Cyberpunk](../docs/games/cyberpunk-2077.md), [007](../docs/games/007-first-light.md) and [Atomic Heart](../docs/games/atomic-heart.md) profiles confirmed neural processing on a limited AMD RDNA4 / Proton configuration. Other configurations, long sessions, comparative image quality and performance gains remain unverified.

Packaging is deterministic for identical inputs. Binary identity across different compilers or OS images is not claimed. No game execution or GPU test is available in CI.
