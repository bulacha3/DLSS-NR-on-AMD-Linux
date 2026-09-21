# DLSS-NR on AMD for Linux

Experimental **DLSS 5 Neural Rendering** on supported AMD GPUs in DirectX 12 games through Wine/Proton.

Based on [danielblnc's DLSS-NR on AMD](https://github.com/danielblnc/DLSS-NR-on-AMD) and [guentra's Linux port](https://github.com/guentra/DLSS-NR-on-AMD-Linux), with work from [lmxxf](https://github.com/lmxxf/dlss5-on-amd-9070xt-porting).

## Download

**[Download](https://github.com/bulacha3/DLSS-NR-on-AMD-Linux/releases)** — choose a release and get `dlssnr-linux-portable.tar.gz` and its `.sha256` file from **Assets**.

[Release notes](CHANGELOG.md) · [All releases](https://github.com/bulacha3/DLSS-NR-on-AMD-Linux/releases)

## Install

The game must already work in **DirectX 12 through Proton**. Close it, then:

```sh
sha256sum -c dlssnr-linux-portable.tar.gz.sha256
tar -xzf dlssnr-linux-portable.tar.gz
cd dlssnr-linux-portable
./install.sh
```

1. Choose **Steam or another launcher**, select the game, then confirm the **same Proton runner** and upscaler route already configured for it.
2. Supply your own **`nvngx_dlssnr.dll` 310.8.0.0** when asked. The installer checks HIP and prepares model data automatically; updates reuse existing models.
3. For Steam, follow the menu to keep your current Launch Options, then copy the complete printed line. Other launchers receive a command prefix. OptiScaler must already be configured if that route is selected.
4. Enable the profile's upscaler in the game. **End** opens DLSS-NR; **Insert** opens OptiScaler.

Install separately for each game. [Full guide](docs/INSTALL.md).

## Game profiles

| Game | Upscaler route | Guide |
| --- | --- | --- |
| Cyberpunk 2077 | Native FSR | [Setup](docs/games/cyberpunk-2077.md) |
| 007 First Light | DLSS input → OptiScaler → FSR | [Setup](docs/games/007-first-light.md) |
| Atomic Heart | DLSS input → OptiScaler → FSR | [Setup](docs/games/atomic-heart.md) |

See the release notes for compatibility and performance results.

## Requirements

- Linux x86_64, Python 3.11+, gcc/g++, a compatible AMD GPU and HIP 7. Backend requirements are listed in the release notes.
- An **FSR 3 / FSR 4** path, native or through OptiScaler. FSR 1 alone is insufficient.
- Your own model data. NVIDIA files, weights and ROCm are not bundled.

This mod adds neural rendering, not path tracing. Performance varies by game and GPU.

## Update or remove

Close the game and rerun `./install.sh` from the new package. Visual settings and original-file backups are retained.

To remove it, run `./install.sh uninstall` and remove its launch options.

After a game update, check the selected upscaler and launch options. If DLSS-NR still works, no reinstall is needed. [Troubleshooting](docs/TROUBLESHOOTING.md).

## Credits

[danielblnc](https://github.com/danielblnc/DLSS-NR-on-AMD) · [guentra](https://github.com/guentra/DLSS-NR-on-AMD-Linux) · [lmxxf](https://github.com/lmxxf/dlss5-on-amd-9070xt-porting) · [vkd3d-proton](https://github.com/HansKristian-Work/vkd3d-proton) · [OptiScaler](https://github.com/optiscaler/OptiScaler) and their contributors. Linux maintenance: **bulacha3**.

Independent community project, not affiliated with NVIDIA or AMD. [Source origins and licenses](THIRD-PARTY.md) · [Build from source](sources/README.md).
