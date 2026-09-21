#!/usr/bin/env python3
"""Batch isolated gfx1201 checks into one report; never modify a game."""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))
from dlssnr import runtime
import lab as lab_helper

VISIBILITY_KEYS = ("HIP_VISIBLE_DEVICES", "ROCR_VISIBLE_DEVICES", "CUDA_VISIBLE_DEVICES", "GPU_DEVICE_ORDINAL")


def clean_environment(original: dict) -> dict:
    env = dict(original)
    for key in (*VISIBILITY_KEYS, "LD_PRELOAD", "LD_AUDIT", "LD_LIBRARY_PATH", "RTC_EXTRA_OPTS"):
        env.pop(key, None)
    return env


def select_gpu(devices: list[dict]) -> dict:
    matches = [d for d in devices if d.get("arch") == "gfx1201"]
    if not matches:
        raise RuntimeError("No compatible gfx1201 GPU was found.")
    return matches[0]


def redact(text: str) -> str:
    return text.replace(str(ROOT), "<PROJECT>").replace(str(Path.home()), "<HOME>")


def find_comgr(library: Path, metadata: dict, data: Path) -> Path:
    roots = [library.parent, library.parent.parent]
    roots += [Path(p) for p in metadata.get("dependency_dirs", [])]
    roots += runtime.discover_roots(managed_root=data / "rocm-venv")
    folders = []
    for root in roots:
        folders += [root, root / "lib", root / "lib64", root / "llvm/lib", root / "_rocm_sdk_core/lib"]
        folders += list(root.glob("lib/python*/site-packages/_rocm_sdk_core/lib"))
    for folder in dict.fromkeys(folders):
        for path in sorted(folder.glob("libamd_comgr.so.3*")):
            if re.fullmatch(r"libamd_comgr\.so\.3(?:\.[\w.-]+)?", path.name) and path.is_file():
                return path.resolve()
    raise RuntimeError("HIP was found, but the libamd_comgr.so.3 compiler was not found.")


def run_logged(argv, env, log, *, timeout=120, result_check=None):
    def emit(value):
        if isinstance(value, bytes):
            value = value.decode("utf-8", errors="replace")
        if value and value.strip():
            log(value.strip())

    try:
        result = subprocess.run([str(a) for a in argv], cwd=ROOT, env=env,
                                capture_output=True, text=True, errors="replace", timeout=timeout)
    except subprocess.TimeoutExpired as error:
        emit(error.stdout)
        emit(error.stderr)
        raise RuntimeError(f"Step exceeded the {timeout}-second limit; sequence stopped.") from error
    emit(result.stdout)
    emit(result.stderr)
    if result_check is not None:
        return result_check(result.stdout, result.returncode)
    if result.returncode:
        raise RuntimeError(f"Step exited with code {result.returncode}; sequence stopped.")
    return result.stdout


def validate_wmma_result(text: str, returncode: int = 0) -> str:
    if returncode not in (0, 3):
        raise RuntimeError(f"Matrix check failed with code {returncode}; sequence stopped.")
    matches = re.findall(r"^RESULT cases=(\d+) failures=(\d+) fp8_f16_bitdiff=(\d+) "
                         r"signed_zero_diff=(\d+) half_diff=(\d+) max_cpu_abs_error=(\S+) "
                         r"max_fp8_f16_abs_diff=(\S+)[ \t]*$", text, re.MULTILINE)
    if len(matches) != 1:
        raise RuntimeError("Matrix check did not produce one complete summary.")
    cases, failures, bitdiff, zero_diff, half_diff = map(int, matches[0][:5])
    cpu_error, path_difference = map(float, matches[0][5:])
    if cases != 79 or failures or any(not math.isfinite(x) or x < 0 for x in (cpu_error, path_difference)):
        raise RuntimeError("Matrix check failed exact cases, numerical bounds or rounding checks.")
    if returncode == 0 and bitdiff == half_diff == 0 and path_difference == 0:
        return "fp8_f16_parity"
    # Pinned upstream Development/HIP/wmma_probe.md documents exit 3
    # with these aggregate FP8-vs-F16 differences.
    # The upstream CPU error bounds and exact cases remain unchanged. Matching
    # these counts does NOT establish elementwise Windows/HLSL or network parity.
    if returncode == 3 and (bitdiff, zero_diff, half_diff, path_difference) == (2054, 0, 2, 4.0):
        return "documented_operand_difference"
    raise RuntimeError("Matrix difference is not characterized by the pinned reference; sequence stopped.")


def main() -> int:
    report = ROOT / "build/lmxxf/gpu-test-result.txt"
    report.parent.mkdir(parents=True, exist_ok=True)
    lines = ["DLSS-NR Linux - isolated FP8 / WMMA / module checks",
             "This does not measure FPS or validate the complete network or game integration."]
    env = clean_environment(os.environ)

    def log(text):
        safe = redact(str(text))
        lines.append(safe)
        # Keep a usable single report even if a later step fails or is interrupted.
        report.write_text("\n\n".join(lines) + "\n")
        print(safe, flush=True)

    def run(argv, *, timeout=120, result_check=None):
        return run_logged(argv, env, log, timeout=timeout, result_check=result_check)

    try:
        if sys.platform != "linux":
            raise RuntimeError("This check requires Linux.")
        missing = [tool for tool in ("g++", "patch") if not shutil.which(tool)]
        if missing:
            raise RuntimeError("Missing tool: " + ", ".join(missing) + ". No package was installed.")
        log("1/6 - Finding the installed HIP runtime and compatible device...")
        data = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share") / "dlssnr-linux"
        candidates = []
        manifest = data / "runtime-manifest.json"
        if manifest.is_file():
            saved = json.loads(manifest.read_text()).get("library")
            if isinstance(saved, str) and Path(saved).is_absolute() and Path(saved).is_file():
                candidates.append(Path(saved).resolve())
        candidates += runtime.discover_runtimes(managed_root=data / "rocm-venv")
        selected = None
        for library in dict.fromkeys(candidates):
            # Enumerate without inherited visibility filters, then use the same
            # HIP index in the child test. Never emit PCI IDs or the raw metadata.
            try:
                result = subprocess.run([sys.executable, "-I", str(Path(runtime.__file__)), "--probe", str(library)],
                                        env=env, capture_output=True, text=True, timeout=30)
                marker = "DLSSNR_PROBE_JSON="
                if marker not in result.stdout:
                    log(f"HIP candidate did not respond correctly (code {result.returncode}).")
                    continue
                info = json.loads(result.stdout.rsplit(marker, 1)[1].splitlines()[0])
                if result.returncode or "error" in info:
                    log(info.get("error", "HIP query failed."))
                    continue
                if info.get("runtime_version", 0) // 10000000 != 7:
                    continue
                gpu = select_gpu(info.get("devices", []))
                comgr = find_comgr(library, info, data)
                selected = (library, info, gpu, comgr)
                break
            except (ValueError, RuntimeError, subprocess.TimeoutExpired) as error:
                log(error)
        if selected is None:
            raise RuntimeError("Could not prepare HIP 7 and COMGR 3 for gfx1201 using the installed libraries.")
        library, info, gpu, comgr = selected
        env["DLSSNR_RESEARCH_HIP_LIBRARY"] = str(library)
        env["DLSSNR_RESEARCH_COMGR_LIBRARY"] = str(comgr)
        env["HIP_VISIBLE_DEVICES"] = str(gpu["index"])
        log(f"GPU: {gpu['name']} | architecture: {gpu['arch']} | HIP: {info['runtime_version']}")
        lab = HERE / "lab.py"
        output = ROOT / "build/lmxxf/linux"
        log("2/6 - Fetching and verifying source...")
        run([sys.executable, lab, "fetch"], timeout=600)
        log("3/6 - Building local tools and checking CPU packing...")
        run([sys.executable, lab, "build"], timeout=300)
        run([sys.executable, lab, "kernels", "--generate-only"])
        log("4/6 - Running FP8 conversion and FP8/FP16 matrix checks...")
        kernels = output / "kernels"
        def compile_module(name):
            module = kernels / (name + ".hsaco")
            run([output / "bin/compile_hip", module, kernels / (name + ".generated.hip"), "comgr"], timeout=300)
            return lab_helper.code_object_record(module)

        compile_module("fp8_probe")
        run([output / "bin/hip_probe"], timeout=30)
        text = run([output / "bin/test_fp8_conversion", kernels / "fp8_probe.hsaco"], timeout=60)
        if not re.search(r"finite_inputs=[1-9][0-9]* bitdiff=0\b", text):
            raise RuntimeError("The expected FP8 comparison was not confirmed.")
        compile_module("wmma_probe")
        validation = output / "validation"
        validation.mkdir(exist_ok=True)
        wmma_status = run([output / "bin/wmma_validate", kernels / "wmma_probe.hsaco", validation / "wmma"],
                          timeout=60, result_check=validate_wmma_result)
        if wmma_status == "documented_operand_difference":
            log("WMMA: numerical bounds and exact cases passed. FP8/FP16 differences "
                "match the pinned upstream totals: 2054 FP32, 2 FP16, maximum difference 4. "
                "This is not bitwise Windows/HLSL parity. Continuing module checks.")
        else:
            log("WMMA: numerical bounds, exact cases and FP8/FP16 parity passed.")

        log("5/6 - Compiling production modules...")
        recipe = json.loads((kernels / "recipe.json").read_text())
        modules = recipe["modules"]
        if len(modules) != 24 or len({m["name"] for m in modules}) != 24:
            raise RuntimeError("The recipe does not contain the expected modules.")
        manifest = {"upstream_commit": lab_helper.LOCK["commit"], "target": "gfx1201",
                    "wmma_status": wmma_status,
                    "status": "incomplete; production kernels not executed", "modules": []}
        manifest_path = kernels / "modules.json"
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
        for index, module in enumerate(modules, 1):
            log(f"Module {index}/24: {module['name']}")
            manifest["modules"].append(compile_module(module["name"]))
            manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")

        log("6/6 - Checking module loading, entry points and unloading...")
        argv = [output / "bin/module_probe"]
        for module in modules:
            argv.extend([kernels / (module["name"] + ".hsaco"), module["probe_entry"]])
        text = run(argv, timeout=180)
        if not re.search(r"^RESULT modules=24 entries=24\b", text, re.MULTILINE):
            raise RuntimeError("Module loading was not confirmed.")
        manifest["status"] = "compiled and load/unload checked; production kernels not executed"
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
        log("RESULT: SUITE COMPLETE - FP8 conversion, WMMA numerical bounds "
            "and module loading checked. WMMA: " + wmma_status + ". "
            "The complete network, Windows/HLSL parity, game integration and performance remain unverified.")
        code = 0
    except KeyboardInterrupt:
        log("RESULTADO: INTERRUPTED - partial report saved.")
        code = 130
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as error:
        log("RESULTADO: TESTE INCOMPLETE - " + str(error))
        code = 1
    report.write_text("\n\n".join(lines) + "\n")
    print(f"\nLocal report: {report}", flush=True)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
