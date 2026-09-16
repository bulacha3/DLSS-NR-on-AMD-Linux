# DLSS-NR on AMD for Linux

Experimental **DLSS 5 Neural Rendering** on supported AMD GPUs in DirectX 12 games through Wine/Proton.

Based on [danielblnc's DLSS-NR on AMD](https://github.com/danielblnc/DLSS-NR-on-AMD) and [guentra's Linux port](https://github.com/guentra/DLSS-NR-on-AMD-Linux).

**Upstream 0.3.1 · Linux 0.3.1-linux.1 · Experimental**

## Download

**[Download 0.3.1 Linux](https://github.com/bulacha3/DLSS-NR-on-AMD-Linux/releases/tag/v0.3.1-linux.1)** — get `dlssnr-linux-portable.tar.gz` and its `.sha256` file from **Assets**.

[What's changed](CHANGELOG.md) · [All releases](https://github.com/bulacha3/DLSS-NR-on-AMD-Linux/releases)

## Install

The game must already work in **DirectX 12 through Proton**. Close it, then:

```sh
sha256sum -c dlssnr-linux-portable.tar.gz.sha256
tar -xzf dlssnr-linux-portable.tar.gz
cd dlssnr-linux-portable
./install.sh
```

1. Select the actual game executable and the **same Proton runner** used by your launcher. Type `steam` to list installed runners.
2. Supply your own **`nvngx_dlssnr.dll` 310.8.0.0**, or converted weights. The installer checks HIP and offers a local runtime download if needed.
3. Paste the printed launch options into Steam. Apply the game profile below if OptiScaler is needed.
4. Enable the profile's upscaler in the game. **End** opens DLSS-NR; **Insert** opens OptiScaler.

**Compute synchronization is automatic on new installs. No `--wait-method` argument is required.** Install separately for each game. [Full guide →](docs/INSTALL.md)

## Tested games

| Game | Tested route with upstream 0.3.1 | Guide |
| --- | --- | --- |
| Cyberpunk 2077 | Native FSR 4.1.1 | [Setup](docs/games/cyberpunk-2077.md) |
| 007 First Light 1.2.0 | DLSS input → OptiScaler → FSR 4.1.1; compute waits | [Setup](docs/games/007-first-light.md) |
| Atomic Heart | DLSS input → OptiScaler → FSR 3.1.4 | [Setup](docs/games/atomic-heart.md) |

Bounded gameplay tests confirmed neural processing on an **AMD RDNA4 / Proton-CachyOS-SLR** configuration. Other GPUs, runners and games remain unverified.

## Requirements and known limits

- Linux x86_64, Python 3.10+, a compatible AMD GPU and HIP 7. Upstream targets RX 7000/9000; Linux validation is narrower.
- An interceptable **FSR 3 / FSR 4** path, native or through OptiScaler. **FSR 1 alone is insufficient.**
- **Graphics waits can crash 007 at startup.** Compute is the default; updates preserve a saved choice. [Switch an older installation](docs/TROUBLESHOOTING.md#007-crashes-immediately-with-graphics-waits).
- Pre-upscaling is enabled by default. Linux enforces `Async=0` and `CpuWait=0`. There is no guaranteed FPS improvement or Windows performance parity.
- NVIDIA files, weights, the original upstream installer/runtime and ROCm are **not bundled**. The upstream runtime is downloaded, verified and used unchanged.
- Long-session stability and the upstream memory-leak fix have not been independently validated. This integration does not add path tracing or bypass anti-cheat.

## Update or remove

Close the game and rerun `./install.sh` from the new package. Visual settings, the saved wait method and original-file backups are retained.

To remove it, run `./install.sh uninstall` and remove its launch options.

[Troubleshooting](docs/TROUBLESHOOTING.md) · [Sharing logs safely](docs/PRIVACY.md) · [Build from source](sources/README.md)

## Credits

[danielblnc](https://github.com/danielblnc/DLSS-NR-on-AMD) · [guentra](https://github.com/guentra/DLSS-NR-on-AMD-Linux) · [vkd3d-proton](https://github.com/HansKristian-Work/vkd3d-proton) · [OptiScaler](https://github.com/optiscaler/OptiScaler) and their contributors. Linux maintenance: **bulacha3**.

Independent community project, not affiliated with NVIDIA or AMD. [Source origins and licenses](THIRD-PARTY.md).
