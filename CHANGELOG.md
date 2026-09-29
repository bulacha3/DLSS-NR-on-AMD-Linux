# Release notes

## 0.5.0 — Linux / Proton

- Stage upstream 0.5.0 using pinned bytes, checksum and embedded payload bounds.
- Preserve the existing Linux bridge and optional-backend policy.
- Accept Python 3.10 for the original installer path.
- Clarify the hidden per-executable mod folder and install-versus-launch sequence.
- Report the failing stage and never offer a launch command for an invalid install.
- Check venv prerequisites before the optional HIP wheel download.
- Validate startup, gameplay and Quality/Balanced switching in Cyberpunk 2077,
  007 First Light and Atomic Heart on RX 9070 XT, with Fast arithmetic.
- Record Cyberpunk single-run benchmark changes (+1.27% Quality, +1.54% Balanced)
  and separately labeled gameplay minimum/maximum changes for the other games.
- Keep intermittent processing spikes and untested conditions explicit.


## 0.4.3

Update to the original upstream 0.4.3 runtime, retaining the Linux priority-stream
bridge and full guided installer. Includes Fast/Reference settings, configurable
overlay key and the upstream overlay/settings fixes. Updates preserve existing
models, visual choices and original-file backups.

Optional lmxxf optimizations are selected per release when they provide a verified benefit. Version 0.4.3 uses the original upstream inference backend.

Current gameplay checks cover Cyberpunk 2077, 007 First Light and Atomic Heart
on RX 9070 XT in Fast mode. Cyberpunk benchmark averages: 55.22 FPS Quality and
64.87 FPS Balanced, with frame generation enabled; see the full notes for settings.
Intermittent processing spikes remain unresolved. No Linux FPS percentage is claimed.

[Full 0.4.3 notes](docs/releases/0.4.3.md) · [Installation](docs/INSTALL.md)

## Previous releases

The following entry describes the previously published release, not 0.4.3.

## 0.3.1-lmxxf

### Changes

- Add the lmxxf HIP backend while retaining the complete neural network.
- Optimize attention, remove redundant conversions and reuse GPU resources across frames.
- Reduce CPU allocation and logging overhead; record slow jobs automatically.
- Guide installation and updates through launcher, game, Proton and upscaler selection.
- Prepare model data automatically, reuse it across games and preserve launch options.

### Performance

| Game | Previous Linux release | 0.3.1-lmxxf | Average FPS change |
| --- | ---: | ---: | ---: |
| Cyberpunk 2077 | 41.16 FPS | 46.61 FPS | +13.2% |

Built-in benchmark versus `v0.3.1-linux.1`, with Balanced FSR, RT Ultra and
frame generation enabled in both runs. This is a single comparison, not a
guarantee for other games or configurations.

### Compatibility

This release has been checked in Cyberpunk 2077. The 007 First Light
and Atomic Heart setup profiles are retained from earlier validation; no new
performance result is claimed for them.

The optimized backend currently targets `gfx1201`. Other GPUs supported by the
installer retain the original backend. Python 3.11+, gcc/g++ and HIP 7 are required.
NVIDIA model data is not included. This remains experimental software.

### Install or update

Close the game, extract the portable package and run `./install.sh`. Follow the
guided steps and copy the final launch instructions. Existing model data,
visual settings and original-file backups are retained.

[Installation guide](docs/INSTALL.md) · [Earlier releases](https://github.com/bulacha3/DLSS-NR-on-AMD-Linux/releases)
