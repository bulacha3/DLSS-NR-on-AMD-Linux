# Installation

The game must already work in DirectX 12 through Wine/Proton. Close it, extract
the portable package into a new folder, and open a terminal beside `install.sh`:

```sh
./install.sh
```

The same guided flow handles installation and updates:

1. **Launcher:** choose Steam or another launcher. A non-Steam shortcut launched
   from Steam uses the Steam option.
2. **Game:** select an installed Steam game, or paste its folder or Windows x64
   executable path. Quoted paths and spaces are accepted. If several executables
   are listed, select the game itself.
3. **Wine/Proton:** select the runner already configured for this game. Steam
   runners are listed automatically. For another launcher, paste its runner
   folder; type `steam` here if you want to list Steam runners. Confirm the choice.
   This installer does not change your launcher's runner selection.
4. **Upscaling:** choose native FSR 3/4 or an existing OptiScaler setup using DLSS
   input and an FSR 3/4 backend. If unsure, stop and check the game's setup guide.
   OptiScaler is not installed or configured by this choice.
5. **Launch configuration:** follow the instructions for the selected launcher
   below. Existing model data is reused; a fresh installation asks for your own
   supported `nvngx_dlssnr.dll` and prepares the models automatically.

## Steam

Open **Library > right-click the game > Properties > General > Launch Options**.
In the installer, choose to keep previously saved options, paste the current
field, or explicitly confirm that the field is empty. Paste the field's full
text, not the word `steam` or a Proton name.

After installation, replace Steam's Launch Options field with the complete line
printed by the installer. It includes `%command%` and preserves the options you
supplied, including OptiScaler, HDR and game arguments.

## Other launchers

Use the printed **command prefix** in your launcher. Keep the existing runner,
Wine prefix, environment variables and game arguments. Do not add `%command%`;
that token belongs to Steam.

## In the game

For native FSR, select FSR 3/4. With OptiScaler, select DLSS input and keep its
FSR 3/4 backend enabled. **End** opens DLSS-NR; **Insert** opens OptiScaler.
Choose your preferred Quality or Balanced mode.

Install separately for each game. Updates retain visual settings and original
backups. To remove the integration, run `./install.sh uninstall` and remove its
launcher command. See the [game profiles](../README.md#game-profiles) and
[troubleshooting](TROUBLESHOOTING.md).
