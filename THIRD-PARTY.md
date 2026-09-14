# Source origins and notices

- Linux installer and bridge: guentra/DLSS-NR-on-AMD-Linux. The original native
  and trampoline sources were recovered from its published experimental
  archive, identified by SHA-256 in PROVENANCE.json. Their original notices
  are retained. This repository does not assert a new license grant for that
  author's code.
- vkd3d-proton: HansKristian-Work/vkd3d-proton at the pinned commit recorded in
  PROVENANCE.json. Its LGPL notices, copying terms, authors, dependency notices,
  complete local patch and submodule pins accompany the build.
- DLSS-NR on AMD v0.3.0: danielblnc/DLSS-NR-on-AMD. The official setup is fetched
  and verified only on the user's computer. Its setup and embedded runtime
  are used without changing their bytes and are excluded from Git and build
  artifacts. See the upstream repository for its license and original notices.
- NVIDIA DLL and converted weights: supplied by the user; never bundled.
- AMD HIP/ROCm: external runtime, not included in the portable archive.
- LLVM/MinGW: a separately downloaded, hash-verified build toolchain. Its
  source and third-party terms are provided by mstorsjo/llvm-mingw.

New standalone integration helpers and tests are covered by
licenses/PROJECT-MIT.txt. That notice does not replace the licenses or missing
grants of third-party components.
