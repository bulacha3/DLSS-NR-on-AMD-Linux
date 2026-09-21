# Troubleshooting

## FSR is inactive in the DLSS-NR menu

Check the selected upscaler against the game's setup guide. For the OptiScaler
profiles, select **DLSS in the game** and **FSR as the OptiScaler backend**.
The `Inputs.EnableFfxInputs=false` option applies to these DLSS-input profiles;
do not copy it to an FSR-input setup.

## End does not open the menu

Check that Steam uses the printed launcher path. With OptiScaler, use the game's
complete launch profile, including `DLSSNR_SWAPCHAIN_QUEUE=1` and
`Menu.OverlayMenu=true`.

## 007 crashes immediately with graphics waits

Close the game and select compute synchronization:

```sh
./install.sh install --exe '/path/to/007 First Light/Retail/007FirstLight.exe' --wait-method compute
```

New installations already use compute. No extra Steam option is needed.

## Black screen or crash after enabling DLSS-NR

Close the game and set `Enabled=0` in `dlssnr_on_amd.ini` beside the executable.
Check the game's setup guide and Proton runner before enabling it again.

## After a game update

Check the game's upscaler setting and Steam launch options. If DLSS-NR still
works, no reinstall is needed. New native FSR support does not require changing
an existing OptiScaler setup.

If the installer reports `Deployed file changed`, keep its backups and report
the named file. It will not overwrite files changed by a game update.

## Installer checks

- **Invalid executable:** select the actual 64-bit game executable and quote its path.
- **Runner missing:** choose the runner configured for that game; use the manual path option if it is not listed.
- **Launch Options:** copy the field from Steam → Properties → General. Use the empty-field option only when that field is empty.
- **DLL rejected:** use `nvngx_dlssnr.dll` 310.8.0.0, not ordinary `nvngx_dlss.dll`.
- **Missing build assets:** use the portable release or [build from source](../sources/README.md).

Add `DLSSNR_DIAGNOSTICS=0` before the launcher command to disable extra bridge
tracing. Before sharing logs, remove personal paths and identifiers.
