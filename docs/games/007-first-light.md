# 007 First Light

> **0.4.3 coverage:** startup, gameplay and Quality/Balanced switching checked on RX 9070 XT through Proton, using DLSS-NR Fast and FSR 4.1.1 through OptiScaler. This is a configuration-specific check, not a guarantee for every system.

Use `Retail/007FirstLight.exe` and the **OptiScaler** route in the installer.
Select **DLSS in the game** with an **FSR 3/4 backend in OptiScaler**.

If this route already works, keep its launch options. For a fresh setup, install
[OptiScaler](https://github.com/optiscaler/OptiScaler) or use a Proton runner
that provides it. The following historical example is specific to runners with OptiScaler integration;
it has not been revalidated for 0.4.3. Prefer the options already working for your game:

```text
DLSSNR_SWAPCHAIN_QUEUE=1 PROTON_USE_OPTISCALER=1 PROTON_OPTISCALER_NAME=dxgi.dll PROTON_OPTISCALER_CONFIG="Inputs.EnableFfxInputs=false;Upscalers.Dx12Upscaler=fsr31;FSR.UpscalerIndex=0;FSR.Fsr4Update=false;Menu.OverlayMenu=true;Menu.FGShortcutKey=-1;FrameGen.Enabled=false;FrameGen.FGInput=nofg;Spoofing.Dxgi=false" PROTON_FSR4_UPGRADE=0 %command%
```

Keep any additional options your game needs. Run `./install.sh`, supply these
current options when asked, and copy its complete final line into Steam. The
installer adds the DLSS-NR launcher; the profile above alone does not install NR.

Keep the OptiScaler overlay enabled. **Insert** opens OptiScaler; **End** opens
DLSS-NR by default (configurable with `OverlayKey`). The `fsr31` label does not guarantee a specific loaded FSR version.

New NR installations use compute synchronization. For an older installation
that crashes with graphics waits, follow the [compute workaround](../TROUBLESHOOTING.md#007-crashes-immediately-with-graphics-waits).

[Installation guide](../INSTALL.md) · [Troubleshooting](../TROUBLESHOOTING.md)
