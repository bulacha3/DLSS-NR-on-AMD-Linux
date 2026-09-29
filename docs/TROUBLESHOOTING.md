# Troubleshooting

## FSR is inactive in the DLSS-NR menu

Check the game's upscaler against its setup guide. For the OptiScaler profiles,
select **DLSS in the game** and **FSR as the OptiScaler backend**. Options intended
for DLSS-input profiles should not be copied blindly into native FSR setups.

## End does not open the menu

Check `OverlayKey` in `dlssnr_on_amd.ini`; End is only the default. Confirm that
Steam or your launcher uses the complete command printed for this game. With
OptiScaler, keep its required overlay/queue options from the game's setup guide.

## Black screen or crash after enabling DLSS-NR

Close the game and set `Enabled=0` in `dlssnr_on_amd.ini` beside the executable.
Keep the logs and check the game's upscaler route and Proton runner before
reenabling it. Update with the complete portable installer, not individual DLLs.
This release retains the priority-stream startup correction, but that correction
does not explain every possible black screen.

## 007 crashes immediately with graphics waits

The retained setup guide uses compute synchronization for a known graphics-wait
startup failure. With the game closed, run from the portable package directory:

```sh
./install.sh install --exe '/path/to/007 First Light/Retail/007FirstLight.exe' --wait-method compute
```

New installations use compute by default. This historical workaround does not
constitute 0.4.3 gameplay validation for 007.

## Intermittent processing spikes

Occasional long processing jobs remain unresolved. Their presence does not
establish a single cause; this release is not advertised as stutter-free.
Include your game, GPU, runner, upscaler route and relevant logs in an issue.

## After a game update

Check the upscaler and launch options. If DLSS-NR still works, a reinstall is not
needed. If the installer reports a modified or unrecognized file, preserve its
backups and inspect the named file before proceeding.

## Installer checks

- **Invalid executable:** select the actual 64-bit game executable.
- **Runner missing:** select the runner configured for this game or enter its path manually.
- **Launch options:** paste Steam's complete field; use the empty choice only for an empty field.
- **Model rejected:** provide the supported neural-rendering DLL or existing DLSSNRW1 weights.
- **Missing build assets:** use the portable release or [build from source](../sources/README.md).

The runtime cache and preload-library path cannot contain whitespace or colons.
This is separate from the game path, which the installer quotes for you.
A filesystem that cannot provide the required permissions, links or shared-memory
behavior may still prevent execution; installation alone is not proof of NTFS compatibility.

## Logs and privacy

The mod writes `dlssnr_on_amd.log` beside the game executable. Bridge diagnostics
are stored in `.dlssnr-linux/logs/hip.log`; vkd3d logging depends on the generated
launcher settings. No personal logs are included in the downloadable package.
Logs generated on your computer may contain paths and hardware identifiers;
review and redact them before sharing. `DLSSNR_DIAGNOSTICS=0` disables extra bridge tracing.

[Installation](INSTALL.md) · [Current coverage](releases/0.4.3.md#coverage-and-limitations)
