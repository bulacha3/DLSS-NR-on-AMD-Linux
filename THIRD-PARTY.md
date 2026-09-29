# Third-party components and provenance

- **Linux port and bridge:** [guentra/DLSS-NR-on-AMD-Linux](https://github.com/guentra/DLSS-NR-on-AMD-Linux).
  Original native/trampoline sources and notices are retained, with the source
  archive identified in `PROVENANCE.json`. No new license grant for that author's
  code is asserted here.
- **vkd3d-proton:** [HansKristian-Work/vkd3d-proton](https://github.com/HansKristian-Work/vkd3d-proton),
  pinned in `PROVENANCE.json`. Its license, copying terms, authors, dependency
  notices, complete local patch and submodule pins accompany the build.
- **DLSS-NR on AMD:** [danielblnc/DLSS-NR-on-AMD](https://github.com/danielblnc/DLSS-NR-on-AMD).
  The 0.4.3 runtime and separate 0.3.1 headless weight converter are downloaded
  and verified locally, without modifying their bytes. Neither setup nor
  embedded runtime is redistributed in this package. See upstream for its terms.
- **lmxxf:** [lmxxf/dlss5-on-amd-9070xt-porting](https://github.com/lmxxf/dlss5-on-amd-9070xt-porting).
  Credited for optional backend work used in previous releases. The original
  MIT notice is retained in `licenses/LMXXF-MIT.txt`; 0.4.3 does not bundle or
  activate the alternative inference modules. Launcher migration support is
  retained for users updating from earlier integrations.
- **NVIDIA model DLL and converted weights:** supplied by the user, never bundled.
- **AMD HIP/ROCm:** external runtime/compiler libraries, not bundled.
- **LLVM/MinGW:** separately downloaded, checksum-verified build toolchain;
  original source and third-party terms are supplied by mstorsjo/llvm-mingw.
- **NumPy:** used by legacy model-preparation helpers when applicable; not bundled.
  Separately installed wheels retain their original notices.

New standalone integration helpers and tests use `licenses/PROJECT-MIT.txt`.
That notice does not replace third-party licenses or missing grants.
Component attribution and rebuild sources remain part of the distribution;
removing personal diagnostics does not remove these notices.
