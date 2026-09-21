# lmxxf integration

Use the [project installation guide](../../docs/INSTALL.md) and root `./install.sh`.
The packaged backend is in [stage4](stage4). Other sources in this directory
support weight preparation, kernel generation and development checks.
Upstream revisions and redistribution notices are recorded in the source
manifests and license files. Model weights must be prepared locally.

## Execution path

The game keeps its existing Wine/Proton graphics integration. The PE HIP
trampoline forwards calls to native Linux HIP; the resident lmxxf backend
executes GPU kernels directly through that same native runtime.

After boundary validation, the bridge replaces the original neural launches
with one lmxxf execution. The original integration still supplies game hooks,
image import/export, exposure handling and optional temporal reprojection.
Removing these stages would require equivalent replacements.

The adapter retains original allocations and host launch interception for
preflight and fallback. A dedicated adapter could reduce that memory and host
work, but its performance benefit has not been measured. Synchronization also
protects producer/consumer ordering and cannot simply be removed.

Upstream performance comparisons must match processing dimensions, enabled
blocks, temporal reuse and frame generation. This candidate preserves the full
network and does not enable adaptive temporal reuse. Game-provided frame
generation settings are preserved; the backend does not add frame generation.
