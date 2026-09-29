# DLSS-NR on AMD for Linux

Experimental DLSS-NR integration for DirectX 12 games on Linux through Wine/Proton.
Based on [danielblnc's DLSS-NR on AMD](https://github.com/danielblnc/DLSS-NR-on-AMD)
and [guentra's Linux port](https://github.com/guentra/DLSS-NR-on-AMD-Linux).

## Download

Get **`dlssnr-linux-portable.zip`** and **`dlssnr-linux-portable.zip.sha256`**
from the [release assets](https://github.com/bulacha3/DLSS-NR-on-AMD-Linux/releases).
GitHub's automatic **Source code** archives are for developers, not the prebuilt installer.

[Release notes](docs/releases/0.5.0.md) · [Changelog](CHANGELOG.md)

## Install or update

The game must already work in DirectX 12 through Wine/Proton. Close it, then
verify and extract the package into a new directory:

```sh
sha256sum -c dlssnr-linux-portable.zip.sha256
unzip dlssnr-linux-portable.zip
cd dlssnr-linux-portable
./install.sh
```

Run as your normal user, **not with sudo**. The guided installer walks through
**launcher → game executable → Wine/Proton runner → upscaler route → launch options**.
Keep the runner already configured for each game. Supply your own supported
`nvngx_dlssnr.dll` (310.8.0.0) or existing converted weights when asked.

For Steam, copy the **complete final line** into **Properties → General → Launch Options**.
For another launcher, use the printed command prefix. The installer preserves
the launch arguments you supply; it does not install or configure OptiScaler.

**The installer creates the hidden `.dlssnr-linux` folder beside the selected game
executable before printing the final command.** Press **Ctrl+H** to see it. The
Steam command only launches an existing installation; it does not create one.
If installation stops, keep the terminal error and do not create the folder manually.
[Find the mod folder](docs/INSTALL.md#where-the-mod-is-installed) ·
[Missing-folder troubleshooting](docs/TROUBLESHOOTING.md#mod-folder-is-missing).

Updates retain model data, visual settings and original-file backups. Install
separately for each game; do not mix individual DLLs between releases.
[Complete step-by-step guide](docs/INSTALL.md).

## Game profiles and current coverage

| Game | Upscaler route |
| --- | --- |
| [Cyberpunk 2077](docs/games/cyberpunk-2077.md) | Native FSR |
| [007 First Light](docs/games/007-first-light.md) | DLSS input → OptiScaler → FSR |
| [Atomic Heart](docs/games/atomic-heart.md) | DLSS input → OptiScaler → FSR |

A setup guide is not a guarantee of compatibility with every release, GPU,
runner or display configuration. Check the [release coverage and limitations](docs/releases/0.5.0.md#coverage-and-limitations)
for the tested version, settings and hardware. Intermittent processing spikes
remain a known limitation.

## Settings

**End** opens DLSS-NR by default; change `OverlayKey` in `dlssnr_on_amd.ini` to
choose another key. Existing custom keys are preserved on update. **Insert**
opens OptiScaler when it is installed.

DLSS-NR **Fast/Reference** selects neural arithmetic. The game's FSR
**Quality/Balanced** setting selects upscaling quality; these are separate controls.
This mod adds neural rendering, not path tracing.

## Optional optimizations

Optional optimizations are included only when they provide a verified benefit.

## Requirements

See [distribution prerequisites](docs/INSTALL.md#distribution-prerequisites).
SteamOS on supported PC hardware and Steam Deck GPU support are separate questions.

Linux x86_64, glibc 2.34+, Python 3.10+, a compatible AMD GPU and HIP 7, and an
FSR 3/4 path (native or through OptiScaler). The installer checks an existing HIP
runtime and can prepare a verified user-local runtime when needed and authorized.
Hardware coverage is documented in the release notes.

NVIDIA files, model weights and AMD runtime/compiler libraries are not bundled.
See the release notes for model-extraction and gameplay validation coverage.

## Remove or troubleshoot

With the game closed, run `./install.sh uninstall` and remove the generated
launcher command from Steam or your launcher. Preserve backups if removal reports
an unrecognized or modified file; do not delete it blindly.

[Troubleshooting](docs/TROUBLESHOOTING.md) · [Build from source](sources/README.md)

## Credits

[danielblnc](https://github.com/danielblnc/DLSS-NR-on-AMD) ·
[guentra](https://github.com/guentra/DLSS-NR-on-AMD-Linux) ·
[lmxxf](https://github.com/lmxxf/dlss5-on-amd-9070xt-porting) ·
[vkd3d-proton](https://github.com/HansKristian-Work/vkd3d-proton) ·
[OptiScaler](https://github.com/optiscaler/OptiScaler) and their contributors.
Linux maintenance: **bulacha3**.

Independent community project, not affiliated with NVIDIA or AMD.
[Source origins and license notices](THIRD-PARTY.md).
