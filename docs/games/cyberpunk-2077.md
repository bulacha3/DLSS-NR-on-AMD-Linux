# Cyberpunk 2077

**Gameplay validated:** diagnostic.3, upstream NR 0.3.0 and native FSR 4.1.1, through Proton on an AMD RDNA4 configuration. Other configurations remain unverified.

## Setup

1. Install for `bin/x64/Cyberpunk2077.exe` inside the game folder.
2. Use the Proton runner that already launches the game successfully.
3. Paste the launch options printed by the installer into Steam.
4. Select the game's compatible FSR option and press **End** for NR.

OptiScaler was not required for this native-FSR route. Do not copy the other games' OptiScaler profiles solely because they worked there.

## Validation

Gameplay analysis confirmed completed ordered neural jobs, positive GPU network time and no reported capture timeout in the successful session. Processing continued across render-size and staging changes.

Frame generation was active. Displayed FPS is not a direct measure of independent neural jobs. No controlled performance benchmark, image-quality comparison or long-session stability claim is made.

The shared fixes preserve original startup probes, accept repeated matching mode-1 wait slices and retain the mode-2 final status dispatch after HIP completion. See the [source guide](../../sources/README.md).

## Path tracing

Path tracing is a separate game setting; NR does not add or require it. Enable or disable **Path Tracing** in **Graphics → Ray Tracing**. The **Ray Tracing: Overdrive** preset also enables it. Availability and performance depend on the game configuration.

[CD Projekt's instructions](https://www.cyberpunk.net/en/news/47875/patch-1-62-ray-tracing-overdrive-mode) · [Troubleshooting](../TROUBLESHOOTING.md)
