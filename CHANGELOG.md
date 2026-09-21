# Release notes

## 0.31.1-lmxxf

### Changes

- Add the lmxxf HIP backend while retaining the complete neural network.
- Optimize attention, remove redundant conversions and reuse GPU resources across frames.
- Reduce CPU allocation and logging overhead; record slow jobs automatically.
- Guide installation and updates through launcher, game, Proton and upscaler selection.
- Prepare model data automatically, reuse it across games and preserve launch options.

### Performance

| Game | Previous Linux release | 0.31.1-lmxxf | Average FPS change |
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
