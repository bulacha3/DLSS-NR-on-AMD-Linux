# DLSS-NR on AMD for Linux

Run **DLSS 5 Neural Rendering** on supported AMD GPUs in DirectX 12 games through Wine/Proton.

An experimental Linux integration of [danielblnc's DLSS-NR on AMD 0.3.0](https://github.com/danielblnc/DLSS-NR-on-AMD), based on [guentra's Linux port](https://github.com/guentra/DLSS-NR-on-AMD-Linux).

**Experimental · Upstream 0.3.0 · Linux package diagnostic.4**

## Download

Check [Releases](https://github.com/bulacha3/DLSS-NR-on-AMD-Linux/releases) for published packages. If no release is listed, open a successful [build](https://github.com/bulacha3/DLSS-NR-on-AMD-Linux/actions/workflows/build-release.yml) and download the **dlssnr-linux-portable** artifact. GitHub requires sign-in to download Actions artifacts.

Use the portable package to install. GitHub's **Source code** archives require [building the Linux components](sources/README.md) first.

## Install

1. Extract the artifact ZIP, then verify and unpack the portable archive:

   ```sh
   sha256sum -c dlssnr-linux-portable.tar.gz.sha256
   tar -xzf dlssnr-linux-portable.tar.gz
   cd dlssnr-linux-portable
   ./install.sh
   ```

2. Select the game's **actual executable** and the **same Wine/Proton runner** used by your launcher. Type `steam` to list compatible installed runners.
3. Supply your own **`nvngx_dlssnr.dll` version 310.8.0.0**, or already converted weights. The installer checks HIP and offers a local runtime download when needed.
4. Copy the launch options printed by the installer into Steam. Apply the game profile below when OptiScaler is required.
5. Enable the profile's upscaler in the game. Press **End** to open DLSS-NR; **Insert** opens OptiScaler when used.

The game must already work in **DirectX 12 through Proton**. Install separately for each game. [Full installation guide →](docs/INSTALL.md)

## Tested games

| Game | Working route | Guide |
| --- | --- | --- |
| Cyberpunk 2077 | Native FSR 4.1.1 | [Setup and status](docs/games/cyberpunk-2077.md) |
| 007 First Light | DLSS input → OptiScaler FSR 3.1 | [Setup and status](docs/games/007-first-light.md) |
| Atomic Heart | DLSS input → OptiScaler FSR 3.1 | [Setup and status](docs/games/atomic-heart.md) |

Gameplay reports and diagnostics confirm neural processing on a limited **AMD RDNA4 / Proton-CachyOS-SLR** configuration. Cyberpunk was validated with diagnostic.3; 007 and Atomic Heart with diagnostic.4. These results do not establish support for every GPU, Proton version or game.

## Requirements and limits

- A compatible AMD GPU and HIP 7 runtime. Upstream targets Radeon RX 7000 and RX 9000; Linux validation is narrower.
- An interceptable **FSR 3 / FSR 4** path. Supported DLSS, FSR 2 or XeSS inputs may work through OptiScaler. **FSR 1 alone is insufficient** for this path.
- **Pre-upscaling is enabled by default.** Linux installation enforces synchronous processing (`Async=0`). Upstream Windows FPS figures are not Linux benchmarks.
- The original upstream runtime is used unchanged. The NVIDIA DLL, converted weights, original installer and ROCm runtime are **not bundled**.
- Compatibility, visual quality and long-session stability vary. This integration does not add path tracing or provide an anti-cheat bypass.

## Update or remove

Close the game, extract the new package and run `./install.sh` again for that game. Existing visual settings and original-file backups are retained.

To remove it, run `./install.sh uninstall` and remove this integration's launch options from the launcher.

[Troubleshooting](docs/TROUBLESHOOTING.md) · [Sharing diagnostics safely](docs/PRIVACY.md) · [Build from source](sources/README.md)

## Credits

- [danielblnc](https://github.com/danielblnc/DLSS-NR-on-AMD) — DLSS-NR on AMD.
- [guentra](https://github.com/guentra/DLSS-NR-on-AMD-Linux) — original Linux integration.
- [vkd3d-proton](https://github.com/HansKristian-Work/vkd3d-proton), [OptiScaler](https://github.com/optiscaler/OptiScaler) and their contributors.
- Linux integration maintenance: **bulacha3**.

Independent community project, not affiliated with NVIDIA or AMD. See [source origins and licenses](THIRD-PARTY.md).
