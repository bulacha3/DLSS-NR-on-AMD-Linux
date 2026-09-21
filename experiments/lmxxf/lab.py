#!/usr/bin/env python3
"""Pinned, offline Linux experiment. Never installs into a game or release."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import urllib.request

HERE = Path(__file__).resolve().parent
LOCK = json.loads((HERE / "upstream.lock.json").read_text())
DEFAULT_SOURCE = HERE.parents[1] / "build/lmxxf/upstream"
DEFAULT_OUTPUT = HERE.parents[1] / "build/lmxxf/linux"

# One exported kernel from each final source in the pinned production recipe.
# Loading these entrypoints checks the Linux loader ABI, not network arithmetic.
MODULE_ENTRIES = {
    "prefix_reference.hip": "dlss5_prefix_reference",
    "multihead_reference.hip": "mh_ffn_expand",
    "deep_reference.hip": "split_mix",
    "boundary_reference.hip": "hip_input_reflect",
    "c32_wmma.hip": "c32_ffn_expand_wmma",
    "multihead_wmma.hip": "mh_ffn_expand_wmma",
    "deep_wmma.hip": "split_mix",
    "wave_pointwise.hip": "c32_attn_normalize_wave",
    "c32_tiled.hip": "c32_ffn_expand_tiled",
    "multihead_tiled.hip": "mh_ffn_expand_tiled",
    "c32_fast.hip": "c32_ffn_expand_fast",
    "c32_fast_attention.hip": "c32_fast_qkv",
    "boundary_fast.hip": "c32_finish_fast",
    "c32_fused_attention_packed.hip": "c32_fast_attention_fused",
    "c32_fused_ffn_attention.hip": "c32_fast_ffn_attention_fused",
    "prefix_fast.hip": "dlss5_prefix_fast_features",
    "multihead_fast.hip": "mh_ffn_expand_fast",
    "multihead_fast_padded.hip": "mh_ffn_expand_fast",
    "multihead_fused_attention.hip": "mh_attention_fused",
    "deep_fast.hip": "vit_expand",
}


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def checked_relative(name: str) -> Path:
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts or "\\" in name:
        raise ValueError(f"Invalid source path: {name}")
    return Path(*path.parts)


def verify(source: Path) -> None:
    for name, expected in LOCK["files"].items():
        path = source / checked_relative(name)
        if not path.is_file():
            raise ValueError(f"Missing pinned source: {name}")
        data = path.read_bytes()
        if len(data) != expected["size"] or digest(data) != expected["sha256"]:
            raise ValueError(f"Source does not match pinned commit: {name}")


def fetch(source: Path) -> None:
    base = f"https://raw.githubusercontent.com/{LOCK['repository']}/{LOCK['commit']}/"
    for name, expected in LOCK["files"].items():
        target = source / checked_relative(name)
        if target.exists():
            if digest(target.read_bytes()) != expected["sha256"]:
                raise ValueError(f"Existing source differs; choose a fresh directory: {name}")
            continue
        request = urllib.request.Request(base + name, headers={"User-Agent": "dlssnr-linux-research"})
        with urllib.request.urlopen(request, timeout=45) as response:
            data = response.read(expected["size"] + 1)
        if len(data) != expected["size"] or digest(data) != expected["sha256"]:
            raise ValueError(f"Download failed source verification: {name}")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    verify(source)
    print(f"Verified {len(LOCK['files'])} source files at {LOCK['commit']}")


def parse_recipe(source: Path) -> list[dict]:
    # Parse data rows from the verified recipe; never execute PowerShell.
    text = (source / "hip/build-modules.ps1").read_text()
    pattern = (r"@\{\s*name\s*=\s*'([^']+)';\s*defines\s*=\s*@\(([^)]*)\);"
               r"\s*sources\s*=\s*@\(([^)]*)\)\s*\}")
    modules = []
    for name, definitions, sources in re.findall(pattern, text):
        defines = ["HIP_ISA_HALF 1"]
        if name.endswith("-packed"):
            defines.append("HIP_PREPACKED_WEIGHTS 1")
        defines += re.findall(r"'([^']+)'", definitions)
        parts = re.findall(r"'([^']+)'", sources)
        if not re.fullmatch(r"[A-Za-z0-9_-]+", name) or not parts:
            raise ValueError("Invalid module recipe")
        if any("hip/" + part not in LOCK["files"] for part in parts):
            raise ValueError("Recipe references an unpinned source")
        entry = MODULE_ENTRIES[parts[-1]]
        modules.append({"name": name, "defines": defines, "sources": parts, "probe_entry": entry})
    if len(modules) != 24 or len({m["name"] for m in modules}) != 24:
        raise ValueError("Expected exactly 24 distinct production modules")
    return modules


def command(args: list[str], **kwargs) -> None:
    subprocess.run(args, check=True, **kwargs)


def owned_output(output: Path) -> None:
    marker = output / ".lmxxf-research-build"
    if output.exists() and any(output.iterdir()) and not marker.is_file():
        raise ValueError("Output directory is not an experiment build; choose an empty directory")
    output.mkdir(parents=True, exist_ok=True)
    marker.write_text(LOCK["commit"] + "\n")


def build(source: Path, output: Path, cxx: str) -> None:
    if sys.platform != "linux":
        raise ValueError("This experiment builds native Linux tools")
    verify(source)
    if source == output or source in output.parents or output in source.parents:
        raise ValueError("Source and output must be separate directories")
    compiler = shutil.which(cxx)
    patch = shutil.which("patch")
    if not compiler or not patch:
        raise ValueError("Install a C++17 compiler (g++) and GNU patch")
    owned_output(output)
    prepared = output / "src"
    binaries = output / "bin"
    binaries.mkdir(exist_ok=True)
    # Re-copy only the pinned text sources. Never copy an arbitrary source tree.
    for name in LOCK["files"]:
        target = prepared / checked_relative(name)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source / name, target)
    command([patch, "--batch", "--fuzz=0", "-p1", "-i", str(HERE / "linux-port.patch")], cwd=prepared)
    common = [compiler, "-std=c++17", "-O2", "-fno-fast-math", "-ffp-contract=off",
              "-I", str(prepared / "Development/HIP")]
    targets = {
        "compile_hip": prepared / "hip/rtc_compile.cpp",
        "reference_network": prepared / "Development/HIP/reference_network.cpp",
        "test_packed_weights": prepared / "Development/HIP/test_packed_weights.cpp",
        "test_fp8_conversion": prepared / "Development/HIP/test_fp8_conversion.cpp",
        "wmma_validate": prepared / "Development/HIP/wmma_validate.cpp",
        "hip_probe": HERE / "hip_probe.cpp",
        "module_probe": HERE / "module_probe.cpp",
        "network_suite": HERE / "network_suite.cpp",
    }
    for name, src in targets.items():
        print(f"Building native Linux {name}", flush=True)
        command(common + [str(src), "-ldl", "-o", str(binaries / name)])
    command([str(binaries / "test_packed_weights")])
    command([str(binaries / "network_suite"), "--self-test"])
    record = {"upstream_commit": LOCK["commit"], "compiler": compiler,
              "patch_sha256": digest((HERE / "linux-port.patch").read_bytes()),
              "lock_sha256": digest((HERE / "upstream.lock.json").read_bytes()),
              "validation": "host build and CPU weight packing only; GPU not tested"}
    (output / "host-build.json").write_text(json.dumps(record, indent=2) + "\n")
    print("Native host tools built. No GPU inference or game integration has been validated.")


def kernels(source: Path, output: Path, generate_only: bool) -> None:
    verify(source)
    if not (output / ".lmxxf-research-build").is_file():
        raise ValueError("Build the host tools first")
    if os.environ.get("RTC_EXTRA_OPTS"):
        raise ValueError("Unset RTC_EXTRA_OPTS to preserve the upstream compiler recipe")
    compiler = output / "bin/compile_hip"
    dest = output / "kernels"
    dest.mkdir(exist_ok=True)
    recipe = parse_recipe(source)
    generated = []
    for module in recipe:
        text = "".join("#define " + d + "\n" for d in module["defines"])
        if "multihead_fast_padded.hip" in module["sources"]:
            # COMGR's header-free Linux input does not declare size_t. Derive
            # its target-native type without SDK headers or changing offsets.
            text += "using size_t = decltype(sizeof(0));\n"
        if "deep_fast.hip" in module["sources"]:
            # Upstream calls this non-dependent name from a template before its
            # definition. Declare the existing device function; keep its body.
            text += "__attribute__((device)) __attribute__((always_inline)) unsigned char byte_F(float);\n"
        for part in module["sources"]:
            text += (source / "hip" / part).read_text() + "\n"
        path = dest / (module["name"] + ".generated.hip")
        path.write_text(text)
        generated.append({**module, "source_sha256": digest(path.read_bytes())})
    # These standalone probes need only synthetic inputs, never model weights.
    probes = {}
    for name, filename in (("fp8_probe", "fp8_conversion_probe.hip"), ("wmma_probe", "wmma_probe.hip")):
        probe = dest / (name + ".generated.hip")
        probe.write_bytes((source / "Development/HIP" / filename).read_bytes())
        probes[name] = digest(probe.read_bytes())
    record = {"upstream_commit": LOCK["commit"], "target": LOCK["target"],
              "status": "source generated; not compiled or GPU validated", "modules": generated,
              "probe_source_sha256": probes}
    (dest / "recipe.json").write_text(json.dumps(record, indent=2) + "\n")
    if generate_only:
        print("Generated sources for 24 production modules and FP8/WMMA probes. No GPU code compiled.")
        return
    manifest = []
    for name in [m["name"] for m in recipe] + list(probes):
        hsaco = dest / (name + ".hsaco")
        command([str(compiler), str(hsaco), str(dest / (name + ".generated.hip")), "comgr"], timeout=300)
        manifest.append(code_object_record(hsaco))
    result = {"upstream_commit": LOCK["commit"], "target": LOCK["target"],
              "status": "compiled; not GPU validated", "modules": manifest}
    (dest / "modules.json").write_text(json.dumps(result, indent=2) + "\n")
    print("Compiled 24 production modules and FP8/WMMA probes. GPU comparisons are still required.")


def code_object_record(path: Path) -> dict:
    data = path.read_bytes()
    if len(data) < 64 or data[:6] != b"\x7fELF\x02\x01" or int.from_bytes(data[18:20], "little") != 224:
        raise ValueError(f"Compiler did not emit an ELF64 AMDGPU object: {path.name}")
    return {"name": path.stem, "sha256": digest(data), "size": len(data)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    for name in ("fetch", "verify", "build", "kernels"):
        cmd = sub.add_parser(name)
        cmd.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
        if name in ("build", "kernels"):
            cmd.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
        if name == "build":
            cmd.add_argument("--cxx", default="g++")
        if name == "kernels":
            cmd.add_argument("--generate-only", action="store_true")
    args = parser.parse_args()
    source = args.source.resolve()
    try:
        if args.action == "fetch":
            fetch(source)
        elif args.action == "verify":
            verify(source)
            print(f"Verified {len(LOCK['files'])} pinned sources")
        elif args.action == "build":
            build(source, args.output.resolve(), args.cxx)
        else:
            kernels(source, args.output.resolve(), args.generate_only)
    except (OSError, ValueError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        print(f"Research build: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
