# Installation

Use **`dlssnr-linux-portable.zip`** from the release assets, not GitHub's automatic source archive.
The game must already work in DirectX 12 through Wine/Proton.
Close the game, extract into a new directory, and open a terminal in the
`dlssnr-linux-portable` directory containing `install.sh`:

```sh
./install.sh
```

The ZIP stores Unix executable permissions. If your extraction tool does not preserve them,
run `chmod u+x install.sh` once, then `./install.sh`.

Run as the game owner, without `sudo`. Do not start the installer from inside
the game directory. The installer locates or asks for the actual executable.

## The five guided steps

1. **Launcher:** choose Steam or another launcher. A non-Steam shortcut started
   through Steam uses the Steam option.
2. **Game:** select an installed Steam game or paste a folder / Windows x64
   executable path. Quoted paths and spaces are accepted. Choose the game itself,
   not a crash reporter or a separate launcher, when multiple executables appear.
3. **Wine/Proton:** choose and confirm the runner already configured for this
   game. Installed Steam runners are listed automatically; use the manual path
   option for another runner. The installer does not change the launcher's choice.
4. **Upscaling:** choose native FSR 3/4 or an existing OptiScaler setup using
   DLSS input with an FSR 3/4 backend. Stop and check the game guide when unsure.
   This choice does not install or configure OptiScaler.
5. **Launch configuration:** preserve your current launch options and copy the
   complete final command as described below. Existing models are reused; if
   needed, the installer asks for your supported NVIDIA model DLL or converted weights.

## Steam

Open **Library → right-click the game → Properties → General → Launch Options**.
In the installer, choose to keep previously saved options, paste the current
field, or confirm that the field is empty. Paste its full text, not `steam` or a
Proton name.

Replace Steam's field with the **complete final line printed by the installer**.
It contains `%command%` and preserves supplied OptiScaler/HDR options and game
arguments. Do not reuse a line from another game. Updating from an older backend
also requires the final line; retaining its old launcher may keep using the old installation.

## Other launchers

Use the printed **command prefix**. Keep the runner, Wine prefix, environment
variables and game arguments already configured in your launcher.
Do not add `%command%`; it is a Steam token.

## Model data and downloads

Provide your own supported `nvngx_dlssnr.dll` **310.8.0.0**, or an existing
`DLSSNRW1` converted weights file. Ordinary DLSS upscaling DLLs are not interchangeable
with the required model. The installer verifies the input before converting it.

Existing model data is reused. Fresh conversion uses the separately pinned
upstream 0.3.1 headless converter in a temporary directory; it is not installed
as the game's runtime. The game receives **0.4.3**. Fresh extraction has not been
revalidated end-to-end for this release; existing weights have gameplay coverage.

The original 0.4.3 setup is downloaded and checksum-verified during installation.
HIP is checked locally; a verified user-local HIP download may be offered when
needed. NVIDIA files, weights and AMD runtime/compiler libraries are not bundled.

## In the game

For native FSR, select FSR 3/4. With OptiScaler, select **DLSS input in the game**
and retain its **FSR 3/4 backend**. **End** opens DLSS-NR by default; `OverlayKey`
in `dlssnr_on_amd.ini` can change that key. **Insert** opens OptiScaler.

DLSS-NR **Fast/Reference** and FSR **Quality/Balanced** are separate settings.
Choose the FSR mode you prefer without treating it as the DLSS-NR arithmetic mode.

## Update or remove

Install separately for every game. For updates, close the game and run
`./install.sh` from the new portable package. Visual settings, model caches and
original-file backups are retained; existing `Quality` and `OverlayKey` values
are preserved. Do not delete caches or mix individual DLLs from different releases.

To remove the integration, run `./install.sh uninstall`, select the game and
remove its generated launcher command. Shared runtime/model caches are retained.
If the installer refuses a modified or unrecognized file, keep the backups and
inspect the named file rather than deleting the whole installation directory.

[Game profiles and coverage](../README.md#game-profiles-and-current-coverage) ·
[Troubleshooting](TROUBLESHOOTING.md)
