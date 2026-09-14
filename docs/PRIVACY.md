# Diagnostic privacy

The integration writes diagnostics locally; it does not automatically attach them to GitHub. Game, Proton, upstream NR and OptiScaler logs can contain paths, usernames, software versions, GPU details and timestamps.

Before sharing a report:

- Start with the game, package version, selected input/backend and observed problem.
- Review logs as text. Replace home directories, account identifiers and private installation paths with consistent placeholders.
- Check screenshots for usernames, notifications and unrelated windows.
- Share only files needed for the failure. Never include credentials, saves, the NVIDIA DLL or converted weights.

This source snapshot excludes raw gameplay logs, identifying log filenames and their SHA-256 fingerprints. Profiles retain compatibility findings without an individual machine inventory or session-specific performance measurements.

Software and package checksums are retained for integrity verification. They identify identical bytes, not hardware serial numbers, and cannot recover the file's contents.

`DLSSNR_DIAGNOSTICS=0` disables the bridge's extra tracing, not all logging by other components.

Public repositories also expose commit author metadata and may expose build logs. Editing the current files does not remove earlier commits.
