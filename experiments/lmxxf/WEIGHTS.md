# Local model preparation

The portable installer accepts a supported, user-provided NVIDIA model DLL.
It prepares both the original backend's weights and the optimized backend's
184 tensors automatically, then reuses the verified local cache for updates
and additional games. No model data or NVIDIA DLL is included or downloaded.

The CPU converter accepts only the pinned 310.8.0.0 DLL checksum. It verifies
the archive index, reconstructs the tensor layouts and checks the complete
output against the backend's pinned tensor hashes before activation. These
checks establish model-data integrity; they do not measure GPU performance.

Conversion uses an available Python 3.11+ interpreter with NumPy. If needed,
the installer downloads a checksum-pinned NumPy wheel from official PyPI
into a private virtual environment. It never installs system Python packages.

The conversion formulas follow lmxxf's MIT-licensed archive and network
layout. The recovered C32 and residual mappings are documented in
`layout-recovery.json`; the source archive index is `weight-records.json`.
See `LICENSE.upstream` for attribution.
