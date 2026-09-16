# Installation

Use Linux x86_64 and Python 3.10 or later. The game must already launch in DirectX 12 through Wine/Proton. Keep its working runner and prefix. Run the installer as your normal user.

Download the portable package from the [README](../README.md). Source archives need [built components](../sources/README.md) first.

## Executable and runner

Run `./install.sh` for the wizard, or specify the executable:

```sh
./install.sh install --exe '/path/to/Game/Game.exe'
```

Quote paths containing spaces. Select the actual game executable, not a launcher:

| Game | Executable relative to the game folder |
| --- | --- |
| Cyberpunk 2077 | `bin/x64/Cyberpunk2077.exe` |
| 007 First Light | `Retail/007FirstLight.exe` |
| Atomic Heart | `AtomicHeart/Binaries/Win64/AtomicHeart-Win64-Shipping.exe` |

Enter `steam` at the runner prompt to list compatible runners, including system-installed Proton variants. Choose the one configured for this game. At confirmation, `n` selects another and `q` cancels. This does not change Steam's runner selection.

Some games embed FSR in the executable. Missing filename evidence does not identify the FSR version or establish compatibility. Check the [game profiles](../README.md#tested-games) before confirming that route.

## Runtime and weights

The installer checks HIP and can offer a local runtime download. It also downloads and verifies the original upstream 0.3.1 setup, approximately 8 MB.

Supply your own **`nvngx_dlssnr.dll` 310.8.0.0**, or converted `DLSSNRW1` weights. You can keep the DLL outside the game folder. Ordinary `nvngx_dlss.dll` is a different component.

Already downloaded the original setup?

```sh
./install.sh install --exe '/path/to/Game/Game.exe' --setup '/path/to/dlssnr_on_amd_setup.exe'
```

## Launch and configure

Paste the printed command into Steam's **Properties → General → Launch Options**, retaining relevant existing options. Keep `%command%` where shown. For other launchers, use the printed command prefix with the existing runner, prefix and arguments; `%command%` is Steam-specific.

Follow the game's profile. With OptiScaler, **DLSS input in the game** can feed an **FSR 3.1 output backend**. **End** opens NR; **Insert** opens OptiScaler.

New installations enable `PreUpscale=1`. Compute synchronization is selected automatically (`SpinDraw=0`); no extra wait-method argument is needed. Updates preserve visual settings and the saved wait method. `Async=0` and `CpuWait=0` are enforced for this Linux bridge.

For an existing experimental installation that saved graphics waits, select compute once with `./install.sh install --exe "/path/to/Game/Game.exe" --wait-method compute`. That choice stays saved for the game. Graphics is an advanced opt-in with a known startup failure in 007 First Light 1.2.0.

## Update, uninstall and diagnose

Close the game and rerun the new installer for that game. Updating one game's installation does not update another's.

Run `./install.sh uninstall` to remove the integration, then remove its launch options. Retain original-file backups if a conflict is reported.

```sh
./install.sh doctor --exe '/path/to/Game/Game.exe'
```

On-disk verification does not confirm in-game neural processing. See [troubleshooting](TROUBLESHOOTING.md) and [diagnostic privacy](PRIVACY.md).
