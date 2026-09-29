# Cyberpunk 2077

**0.4.3 coverage:** startup, gameplay, overlay and Quality/Balanced switching
checked on RX 9070 XT (`gfx1201`) through Proton, with DLSS-NR Fast, native
FSR 4.1.1 and frame generation. Intermittent processing spikes remain unresolved.

1. Run `./install.sh` from the portable package and select `bin/x64/Cyberpunk2077.exe`.
2. Choose the same Proton runner already configured for the game and the **native FSR** route.
3. Preserve your current Steam options, then copy the complete final line.
4. Select **FSR 3/4** in the game. **End** opens DLSS-NR unless `OverlayKey` was changed.

OptiScaler is not required for this route. Keep your preferred FSR Quality or
Balanced mode; DLSS-NR Fast/Reference is a separate setting. Path tracing remains
a game setting and is not added or required by this integration.

**Built-in benchmark:** 55.22 FPS average in Quality; 64.87 FPS in Balanced.
Both runs used 3612 x 1512, High textures, RT lighting Ultra, path tracing off
and frame generation on, without VSync or an FPS limit. These are single-run
results, not a matched version-to-version speedup or native-rendered FPS.

[Coverage and limitations](../releases/0.4.3.md#coverage-and-limitations) ·
[Installation](../INSTALL.md) · [Troubleshooting](../TROUBLESHOOTING.md)
