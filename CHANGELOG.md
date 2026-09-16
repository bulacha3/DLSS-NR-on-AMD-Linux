# 0.3.1 Linux — Experimental

Linux integration of [DLSS-NR on AMD Alpha 0.3.1](https://github.com/danielblnc/DLSS-NR-on-AMD/releases/tag/v0.3.1). Package version: **0.3.1-linux.1**.

## Changes

- Uses the original upstream 0.3.1 runtime, including its announced frame-generation, RE Engine and memory-leak fixes.
- Adds support for upstream's graphics wait commands. **Compute remains the Linux default** for compatibility; no extra installer argument is needed.
- Preserves visual settings, original backups and the saved wait method when updating.
- Updates the installation and game guides for Cyberpunk 2077, Atomic Heart and 007 First Light.

## Known limits

- Graphics waits crash the tested 007 First Light 1.2.0 configuration. Compute works in that configuration and is selected automatically for new installs. An older installation that saved graphics needs a [one-time switch](https://github.com/bulacha3/DLSS-NR-on-AMD-Linux/blob/main/docs/TROUBLESHOOTING.md#007-crashes-immediately-with-graphics-waits).
- Successful gameplay in these three games is not universal compatibility. There is no verified FPS gain or Windows performance parity.
- The upstream RE Engine fixes, specific frame-generation bug and memory-leak fix have not been independently reproduced and validated here.

## Download and update

Download **`dlssnr-linux-portable.tar.gz`** and **`dlssnr-linux-portable.tar.gz.sha256`** below. Verify, extract and run `./install.sh` with the game closed. GitHub's **Source code** archives require building first.

The package contains the Linux bridge, installer and corresponding source. Supply your own `nvngx_dlssnr.dll` 310.8.0.0 or converted weights; no NVIDIA files, weights or game logs are included.

[Installation](https://github.com/bulacha3/DLSS-NR-on-AMD-Linux#install) · [Game profiles](https://github.com/bulacha3/DLSS-NR-on-AMD-Linux#tested-games)
