#!/usr/bin/env python3
"""Generate the pinned MH attention module with contiguous V fragments.

The V tile uses the existing per-head allocation. Arithmetic, weights, kernel
arguments, workgroup sizes, and the existing workgroup barriers are unchanged.
"""
import argparse
import hashlib
from pathlib import Path

UPSTREAM_COMMIT = "90abf6a2d3e3b08136ab56de0c658d830b327865"
UPSTREAM_SHA256 = "f119879e6b81a0f8705723b9bc15e6a306f88573caacef6502ecdb60218cbe58"
UPSTREAM_BYTES = 42561


def generate(source: Path, output: Path) -> None:
    data = source.read_bytes()
    if len(data) != UPSTREAM_BYTES or hashlib.sha256(data).hexdigest() != UPSTREAM_SHA256:
        raise ValueError("MH attention source does not match the pinned upstream commit")
    # Preserve the original Linux recipe and select only the existing V layout.
    # Define ablation explicitly because its default is nested under !HIP_MH_VT
    # in the pinned upstream source.
    defines = (
        "#define HIP_ISA_HALF 1\n"
        "#define HIP_MH_RTZ_ISA 1\n"
        "#define HIP_MH_ABLATE 0\n"
        "#define HIP_MH_VT 1\n"
    )
    output.write_bytes(defines.encode("ascii") + data + b"\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    generate(args.source, args.output)
