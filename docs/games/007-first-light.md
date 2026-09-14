# 007 First Light

**Gameplay validated:** diagnostic.4, upstream NR 0.3.0, OptiScaler 0.9.4-final (`7534ad0`) and an AMD RDNA4 / Proton-CachyOS-SLR configuration.

## Setup

Install for `Retail/007FirstLight.exe`. Select **DLSS in the game**; OptiScaler supplies **FSR 3.1**. The embedded FSR option is not this validated route.

Replace **both** occurrences of `/path/to/007 First Light` below with the actual game folder. Keep the quotes. This template preserves the tested settings with private paths replaced.

```text
DLSSNR_SWAPCHAIN_QUEUE=1 PROTON_USE_OPTISCALER=1 PROTON_OPTISCALER_NAME=dxgi.dll PROTON_OPTISCALER_CONFIG="Inputs.EnableFfxInputs=false;Upscalers.Dx12Upscaler=fsr31;FSR.UpscalerIndex=0;FSR.Fsr4Update=false;Menu.OverlayMenu=true;Menu.FGShortcutKey=-1;FrameGen.Enabled=false;FrameGen.FGInput=nofg;Spoofing.Dxgi=false;Log.LogToFile=true;Log.LogLevel=2;Log.SingleFile=true;Log.LogFileName=Z:/path/to/007 First Light/Retail/OptiScaler.log" PROTON_FSR4_INDICATOR=0 PROTON_FSR4_UPGRADE=0 PROTON_ENABLE_WAYLAND=1 PROTON_ENABLE_HDR=1 LOW_LATENCY_LAYER=1 WINEPULSE_FAST_POLLING=1 '/path/to/007 First Light/Retail/.dlssnr-linux/launch.sh' %command%
```

The Wayland, HDR, audio and latency options were present during testing; they are not established NR requirements. Adapt those platform settings to a game configuration that already works.

**End** opens NR; **Insert** opens OptiScaler. Keep `Menu.OverlayMenu=true`: disabling it repeatedly crashed the tested 007 setup. Frame generation was disabled.

## Why these options matter

| Option | Purpose |
| --- | --- |
| `DLSSNR_SWAPCHAIN_QUEUE=1` | Supplies the command queue owned by the swapchain when wrapper identities differ. |
| `Inputs.EnableFfxInputs=false` | Avoids FFX input hooks bypassing NR, while retaining DLSS input. |
| `Upscalers.Dx12Upscaler=fsr31` | Selects the FSR 3.1 backend. |
| `Spoofing.Dxgi=false` | Retains the DXGI adapter identity used by this profile. Atomic Heart uses a different value. |

Disabling FFX input is not a global recommendation for games that rely on FFX inputs.

## Validation and mechanism

Gameplay analysis confirmed NR initialization, FSR 3.1.4 interception, completed ordered neural jobs, positive GPU network time and no reported capture timeout. This is not a controlled performance or image-quality benchmark.

NR records the swapchain's IUnknown identity and creation queue. If the presented object cannot be matched, NR requests its `ID3D12CommandQueue`. The Linux fallback previously queried only the device. Diagnostic.4 supplies only the queue owned by that swapchain when enabled, with normal COM reference counting.

OptiScaler's FFX detours can preserve original backend function pointers and bypass NR's later hooks. The DLSS-input profile avoids those detours. Subsequent gameplay confirmed both initialization and neural processing.

CPU regressions cover the actual before/after queue query, opt-in behavior, identity, references and failures. No original NR binary or shader is modified. See the [source guide](../../sources/README.md).

[Troubleshooting](../TROUBLESHOOTING.md) · [Sharing logs safely](../PRIVACY.md)
