# Atomic Heart

**Gameplay validated:** diagnostic.4, upstream NR 0.3.0, OptiScaler 0.9.4-final (`7534ad0`) and an AMD RDNA4 / Proton-CachyOS-SLR configuration.

## Setup

Install for `AtomicHeart/Binaries/Win64/AtomicHeart-Win64-Shipping.exe`. Select **DLSS in the game** and **FSR 3.1 in OptiScaler**.

Replace **both** occurrences of `/path/to/Atomic Heart` with the actual game folder. Keep the quotes. This template preserves the tested settings with private paths replaced.

```text
DLSSNR_DIAGNOSTICS=1 DLSSNR_SWAPCHAIN_QUEUE=1 PROTON_USE_OPTISCALER=1 PROTON_OPTISCALER_NAME=dxgi.dll PROTON_OPTISCALER_CONFIG="Inputs.EnableFfxInputs=false;Upscalers.Dx12Upscaler=fsr31;FSR.UpscalerIndex=0;FSR.Fsr4Update=false;Menu.OverlayMenu=true;Menu.FGShortcutKey=-1;FrameGen.Enabled=false;FrameGen.FGInput=nofg;Spoofing.Dxgi=true;Log.LogToFile=true;Log.LogLevel=2;Log.SingleFile=true;Log.LogFileName=Z:/path/to/Atomic Heart/AtomicHeart/Binaries/Win64/OptiScaler.log" PROTON_FSR4_INDICATOR=0 PROTON_FSR4_UPGRADE=0 PROTON_ENABLE_WAYLAND=1 PROTON_ENABLE_HDR=1 LOW_LATENCY_LAYER=1 WINEPULSE_FAST_POLLING=1 '/path/to/Atomic Heart/AtomicHeart/Binaries/Win64/.dlssnr-linux/launch.sh' %command% -dx12
```

The Wayland, HDR, audio and latency options were present during the test; they are not established NR requirements. Retain platform settings appropriate to a working game configuration.

**End** opens NR; **Insert** opens OptiScaler. Frame generation was disabled.

## Differences from 007

Atomic Heart uses **`Spoofing.Dxgi=true`**; the tested 007 profile uses false. The resulting NVIDIA adapter label does not identify the real compute device: neural processing still runs on AMD through HIP.

Both profiles retain `DLSSNR_SWAPCHAIN_QUEUE=1`, `Inputs.EnableFfxInputs=false` and `Menu.OverlayMenu=true`. The FFX-input setting is specific to this DLSS-input route.

## Validation

Gameplay analysis confirmed FSR 3.1.4 interception, completed ordered neural jobs, positive GPU network time and no reported capture timeout. Processing continued across render-size and staging changes. No additional bridge or runtime correction was required after the 007 fixes.

Pre-upscaling ran with temporal history off in NR. Initial zero-dispatch messages ended after creation of the game's DLSS feature; startup zeroes alone do not establish a continuing failure.

Ray tracing was enabled in the game. Diagnostics exposed DXR 1.1 and acceleration-structure activity, which establish API activity rather than visual validation of each effect. The mod does not add path tracing or upgrade DXR.

Comparative image quality, controlled benchmarks and long-session stability remain unverified.

[Troubleshooting](../TROUBLESHOOTING.md) · [Sharing logs safely](../PRIVACY.md)
