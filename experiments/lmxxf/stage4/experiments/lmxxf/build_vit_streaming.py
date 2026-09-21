#!/usr/bin/env python3
"""Backport exact streaming ViT attention without changing the resident ABI.

Only vit_attention_fused_body is imported. The original Linux fixes, exports,
weights, and graph integration remain in the verified baseline source. Adaptive
reuse and its additional kernel arguments are deliberately not imported.
"""
import argparse
import hashlib
from pathlib import Path

BASELINE_SHA256 = "7c4d708650a9a006b9b5999fe0d8a6c3eb1d2d1899dd011c67c2224b92020ce2"
UPSTREAM_COMMIT = "70656f8ec1cd1019ef537f17d557cc4a46365b09"
UPSTREAM_SHA256 = "af3d13cc9b7370f54763603823d1f44e6e068631ac4af06b7ba826830520a896"
SIGNATURE = "DEV void vit_attention_fused_body(const float*in,float*out,uint tokens)"


def checked_read(path: Path, expected: str) -> str:
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != expected:
        raise ValueError(f"Source hash does not match pinned input: {path.name}")
    return data.decode("utf-8")


def function_span(text: str) -> tuple[int, int]:
    if text.count(SIGNATURE) != 1:
        raise ValueError("Expected exactly one fused ViT attention body")
    start = text.index(SIGNATURE)
    brace = text.index("{", start)
    depth = 0
    for end in range(brace, len(text)):
        depth += (text[end] == "{") - (text[end] == "}")
        if depth == 0:
            return start, end + 1
    raise ValueError("Unclosed fused ViT attention body")


def generate(baseline: Path, upstream: Path, output: Path) -> None:
    old = checked_read(baseline, BASELINE_SHA256)
    latest = checked_read(upstream, UPSTREAM_SHA256)
    a, b = function_span(old)
    c, d = function_span(latest)
    body = latest[c:d]
    if "reuse_gate" in body or "p8[" in body:
        raise ValueError("Unexpected upstream streaming implementation")
    output.write_text(old[:a] + body + old[b:], encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("baseline", type=Path)
    parser.add_argument("upstream", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    generate(args.baseline, args.upstream, args.output)
