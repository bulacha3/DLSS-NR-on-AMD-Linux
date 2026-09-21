#!/usr/bin/env python3
"""Combine exact streaming attention and fixed model-dimension specialization.

Specialized helpers keep the baseline arithmetic bodies byte-for-byte. Public
kernel arguments and generic shape fallbacks remain available. Only channel
counts become constants; image geometry and token counts stay dynamic.
"""
import argparse
from pathlib import Path
import tempfile

from build_vit_streaming import generate as generate_streaming

SPECS = {
    "vit_expand_blocked_fp8_frag_bytein": {
        "end": "\n",
        "arguments": "in,w,out,tokens,inputs,outputs",
        "pairs": ((1024, 4096),),
    },
    "vit_project_frag": {
        "end": "\nWAVE void vit_qkv_project_normalize_fused_f16compact_fp8_frag(",
        "arguments": "in,w,skip,out,tokens,inputs,outputs",
        "pairs": ((1024, 1024),),
    },
    "decoder_project2x_h16w": {
        "end": "\ntemplate<bool ByteInput=false>\nDEV f8 dot16(",
        "arguments": "in,w,skip,out,iw,ih,ow,oh,inputs,outputs",
        "pairs": ((1024, 512), (512, 256), (256, 128), (128, 64), (64, 32)),
    },
}


def source_function(source: str, name: str, prefix: str = "WAVE void ") -> str:
    signature = prefix + name + "("
    if source.count(signature) != 1:
        raise ValueError(f"Expected one baseline kernel: {name}")
    start = source.index(signature)
    end = source.index(SPECS[name]["end"], start)
    return source[start:end]


def specialize(source: str) -> str:
    for name, spec in SPECS.items():
        function = source_function(source, name)
        brace = function.index("{")
        signature, body = function[:brace], function[brace:]
        helper = "lmxxf_fixed_" + name
        implementation = signature.replace("WAVE void " + name, "DEV void " + helper, 1) + body
        original_arguments = spec["arguments"]
        prefix = original_arguments.rsplit(",", 2)[0]
        branches = []
        for inputs, outputs in spec["pairs"]:
            branches.append(f"if(inputs=={inputs}&&outputs=={outputs})"
                            f"{helper}({prefix},{inputs},{outputs});")
        wrapper = signature + "{" + "else ".join(branches)
        wrapper += f"else {helper}({original_arguments});" + "}"
        source = source.replace(function, implementation + "\n" + wrapper, 1)
    return source


def generate(baseline: Path, upstream: Path, output: Path) -> None:
    with tempfile.TemporaryDirectory() as directory:
        streaming = Path(directory) / "streaming.hip"
        generate_streaming(baseline, upstream, streaming)
        output.write_text(specialize(streaming.read_text()), encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("baseline", type=Path)
    parser.add_argument("upstream", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    generate(args.baseline, args.upstream, args.output)
