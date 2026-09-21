#!/usr/bin/env python3
"""Batch prepared-weight preflight and nine full-graph smoke runs into one report.

The raw-DLL converter is NOT complete. Read WEIGHTS.md before requesting GPU work.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
import lab
import weight_assets
from run_gpu_test import clean_environment, find_comgr, redact, run_logged, select_gpu, runtime


def select_environment(env, log):
    data = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share") / "dlssnr-linux"
    candidates = []
    manifest = data / "runtime-manifest.json"
    if manifest.is_file():
        saved = json.loads(manifest.read_text()).get("library")
        if isinstance(saved, str) and Path(saved).is_absolute() and Path(saved).is_file():
            candidates.append(Path(saved).resolve())
    candidates += runtime.discover_runtimes(managed_root=data / "rocm-venv")
    for library in dict.fromkeys(candidates):
        try:
            probe = subprocess.run([sys.executable, "-I", str(Path(runtime.__file__)), "--probe", str(library)],
                                   env=env, capture_output=True, text=True, timeout=30)
            marker = "DLSSNR_PROBE_JSON="
            if probe.returncode or marker not in probe.stdout:
                continue
            info = json.loads(probe.stdout.rsplit(marker, 1)[1].splitlines()[0])
            if info.get("runtime_version", 0) // 10000000 != 7:
                continue
            gpu = select_gpu(info.get("devices", []))
            comgr = find_comgr(library, info, data)
            env.update(DLSSNR_RESEARCH_HIP_LIBRARY=str(library), HIP_VISIBLE_DEVICES=str(gpu["index"]),
                       DLSSNR_RESEARCH_COMGR_LIBRARY=str(comgr))
            log(f"GPU: {gpu['name']} | architecture: {gpu['arch']} | HIP: {info['runtime_version']}")
            return
        except (ValueError, RuntimeError, OSError, subprocess.TimeoutExpired):
            continue
    raise RuntimeError("HIP 7 and COMGR 3 for gfx1201 were not found.")


def cached_modules_valid(output, source):
    try:
        saved = json.loads((output / "kernels/modules.json").read_text())
        if saved["upstream_commit"] != lab.LOCK["commit"] or saved["target"] != "gfx1201":
            return False
        by_name = {m["name"]: m for m in saved["modules"]}
        for module in lab.parse_recipe(source):
            name = module["name"]
            if lab.code_object_record(output / "kernels" / (name + ".hsaco")) != by_name.get(name):
                return False
        return True
    except (OSError, ValueError, KeyError, TypeError):
        return False


def verify_suite(text):
    complete = re.findall(r"^COMPLETE case=(\S+) seed=(\d+) blocks=71 min=\S+ max=\S+ wall_seconds=\S+$", text, re.M)
    expected = [(name, "0") for name in ("gradient", "replay", "history", "history-replay",
                                         "history-reset", "alternate", "alternate-replay")]
    expected += [("gradient", "123"), ("replay", "123")]
    if complete != expected or text.count("RESULT runs=9 blocks_per_run=71 repeats_exact=yes finite=yes external_parity=not_tested") != 1:
        raise RuntimeError("The suite did not confirm all nine cases.")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assets", type=Path, default=ROOT / "build/lmxxf/prepared-weights")
    parser.add_argument("--source", type=Path, default=lab.DEFAULT_SOURCE)
    parser.add_argument("--check-only", action="store_true", help="CPU asset preflight only; no HIP/download/build")
    args = parser.parse_args(argv)
    report = ROOT / "build/lmxxf/network-test-result.txt"
    report.parent.mkdir(parents=True, exist_ok=True)
    lines = ["DLSS-NR Linux - offline network suite",
             "Synthetic input and the complete network; this does not measure game FPS."]

    def log(message):
        safe = redact(str(message))
        lines.append(safe)
        report.write_text("\n\n".join(lines) + "\n")
        print(safe, flush=True)

    try:
        log("1/4 - Checking prepared weights before GPU initialization...")
        checked = weight_assets.inspect_assets(args.assets)
        log(f"Valid files: {checked['valid_files']}/{checked['expected_files']}")
        if checked["errors"]:
            log("\n".join(checked["errors"]))
            log("BLOCKED: missing or invalid prepared weights. DLL and DLSSNRW1 files "
                "do not replace this format. See experiments/lmxxf/WEIGHTS.md. No GPU test was started.")
            return 2
        log("Structure and finite values checked; weight layout correctness remains unverified.")
        if args.check_only:
            log("PREFLIGHT COMPLETE - network execution and external parity were not tested.")
            return 0
        if sys.platform != "linux":
            raise RuntimeError("This suite requires Linux.")
        env = clean_environment(os.environ)
        select_environment(env, log)

        def run(argv, timeout=300):
            return run_logged(argv, env, log, timeout=timeout)

        log("2/4 - Checking source and building native tools...")
        source = args.source.resolve()
        output = lab.DEFAULT_OUTPUT
        run([sys.executable, HERE / "lab.py", "fetch", "--source", source], 600)
        run([sys.executable, HERE / "lab.py", "build", "--source", source], 300)
        if cached_modules_valid(output, source):
            log("Previously compiled and verified modules reused.")
        else:
            run([sys.executable, HERE / "lab.py", "kernels", "--source", source], 1200)
        # Record asset digests locally, never include paths or weight data in the shareable report.
        (report.parent / "network-assets-local.json").write_text(json.dumps(checked, indent=2) + "\n")
        log("3/4 - Running repeatability, temporal history, reset, input and seed checks...")
        log("The reference path can be slow; this suite is not a performance benchmark.")
        results = report.parent / ("network-results-" + str(time.time_ns()))
        text = run([output / "bin/network_suite", args.assets.resolve(), output / "kernels", results], 1800)
        verify_suite(text)
        log("4/4 - Checking that weights remained unchanged...")
        after = weight_assets.inspect_assets(args.assets)
        if after != checked:
            raise RuntimeError("Weights changed during the suite; result discarded.")
        log("OFFLINE RUN COMPLETE - finite outputs and exact repeats. "
            "Comparison with original NVIDIA/Windows output is pending; this does not validate image quality, "
            "long-session resource behavior or game integration.")
        return 0
    except KeyboardInterrupt:
        log("INTERRUPTED - partial report saved.")
        return 130
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as error:
        log("INCOMPLETE - " + str(error))
        return 1
    finally:
        print("\nLocal report: " + str(report), flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
