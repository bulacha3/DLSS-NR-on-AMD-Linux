# Troubleshooting

## FSR is inactive in the NR menu

Check the game's input and backend separately. The tested 007 and Atomic Heart routes use **DLSS in the game** and **FSR 3.1 in OptiScaler**. Their embedded FSR options are not the validated route.

With these DLSS-input profiles, `Inputs.EnableFfxInputs=false` avoids a hook conflict between OptiScaler and NR. It disables FFX input interception, not the FSR 3.1 output backend. Do not use it globally for games that need an FFX input.

Startup dispatch counters can be zero before the game creates its upscaler. Check gameplay, not just a splash screen. Use the complete [007](games/007-first-light.md) or [Atomic Heart](games/atomic-heart.md) profile.

## End does not open the menu

Update that game's installation to diagnostic.4 and use its profile with `DLSSNR_SWAPCHAIN_QUEUE=1`. The option makes the swapchain's own command queue available to NR when a wrapper changes its identity.

Keep `Menu.OverlayMenu=true` in these profiles. Setting it to false repeatedly crashed the tested 007 configuration.

## Black screen or crash after enabling NR

Close the game. Set `Enabled=0` in `dlssnr_on_amd.ini` beside the executable before relaunching. Check the game's profile and selected Proton runner.

If a report is needed, reproduce once with fixed settings and retain the matching NR, HIP, vkd3d and OptiScaler logs. Review the [privacy guide](PRIVACY.md) before sharing them.

## Reduce diagnostic output

Add `DLSSNR_DIAGNOSTICS=0` before the wrapper command to disable the bridge's extra tracing. This does not disable every log written by the game, Proton, upstream runtime or OptiScaler.

The wrapper uses vkd3d's `warn` level so device-removal reasons are retained. Some logs append multiple launches: earlier failures may belong to another session.

## Installer checks

- **Invalid executable:** select the actual 64-bit executable and quote its path.
- **Runner missing:** type `steam` and select the game's configured runner. Incompatible entries include their validation errors.
- **DLL rejected:** supply `nvngx_dlssnr.dll` 310.8.0.0; ordinary `nvngx_dlss.dll` is not the NR model source.
- **Metadata-only checkout:** use the portable package or [build the components](../sources/README.md).

## What successful validation means

An open menu or installer check alone is insufficient. Gameplay analysis established FSR interception, positive GPU network time and completed ordered producer/HIP/consumer jobs. These are not controlled image-quality benchmarks or proof of universal compatibility or long-session stability.
