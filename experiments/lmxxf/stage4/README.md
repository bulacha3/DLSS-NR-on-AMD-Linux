# lmxxf update

Update an existing DLSS-NR Linux installation with the lmxxf backend. This
package reuses the game's Proton/HIP configuration and prepared model data.
For a fresh installation, use the full portable installer.

## Install or update

Close the game, open a terminal in this extracted folder, and run:

```sh
./install.sh
```

Choose the game and paste its current Steam launch options when asked. The
installer finds prepared weights automatically and prints the complete updated
Steam command, including `%command%`. Keep the same Proton runner selected in
Steam.

To restore the previous backend:

```sh
./install.sh --restore
```

Direct commands remain available:

```sh
python3 prepare.py --game "/path/to/game"
python3 prepare.py --restore --game "/path/to/game"
```

If model data is stored elsewhere, add `--weights "/path/to/prepared-weights"`.
Linux x86_64, Python 3.11+, gcc/g++, compatible HIP and a GPU supported by the
included `gfx1201` kernels are required.

## Optional diagnostic

Slow jobs are recorded automatically in `resultado-etapa4.txt`; kernel
profiling is not needed to collect this report during ordinary gameplay.

Add `--profile` to collect a short GPU kernel profile. After enabling NR in
actual gameplay, allow about 30 seconds, then close the game. The installer
prints the report paths. Run the installer without `--profile` to disable
collection on future launches.

Credits: [Daniel](https://github.com/danielblnc/DLSS-NR-on-AMD),
[guentra](https://github.com/guentra/DLSS-NR-on-AMD-Linux) and
[lmxxf](https://github.com/lmxxf/dlss5-on-amd-9070xt-porting).
Included license notices apply. Model data is not bundled.
