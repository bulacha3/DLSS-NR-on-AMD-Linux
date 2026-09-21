#!/usr/bin/env python3
"""Check source identity, old ABI, and streaming operand/order equivalence.

This is a CPU contract proof, not GPU execution or a performance benchmark.
"""
import argparse
from pathlib import Path
import sys
import tempfile

HERE = Path(__file__).resolve().parent
if not (HERE / "build_vit_streaming.py").is_file():
    sys.path.insert(0, str(HERE.parent / "experiments/lmxxf"))
from build_vit_streaming import generate, function_span


def prove_source(baseline: Path, upstream: Path) -> None:
    with tempfile.TemporaryDirectory() as temporary:
        output = Path(temporary) / "candidate.hip"
        generate(baseline, upstream, output)
        old, new = baseline.read_text(), output.read_text()
        a, b = function_span(old)
        c, d = function_span(new)
        assert old[:a] == new[:c] and old[b:] == new[d:]
        body = old[a:b]
        # Independent surgical derivation: remove only the P-cache storage and
        # move its existing PV operation directly after the corresponding xb
        # is produced. This must exactly match the imported upstream function.
        for removed in (
            " __attribute__((shared)) unsigned char p8[16*(MAXT+16)];\n",
            "  __builtin_memcpy(p8+rc()*S+key+gr()*8,&xb,8);\n",
        ):
            assert body.count(removed) == 1
            body = body.replace(removed, "", 1)
        body = body.replace(" const uint S=tokens+16;const unsigned char*in8=",
                            " const unsigned char*in8=", 1)
        body = body.replace(" f8 sum{};", " f8 sum{},acc[2]{};", 1)
        loop_start = body.index(" f8 acc[2]{};\n")
        loop_end = body.index("\n for(uint c=0;c<2;c++)for(uint e=0;e<8;e++)", loop_start)
        loop = body[loop_start:loop_end]
        inner_start = loop.index("  for(uint c=0;c<2;c++)")
        inner_end = loop.rindex("\n }")
        inner = loop[inner_start:inner_end]
        inner = inner.replace("uint key=k+gr()*8+e;", "uint vkey=key+gr()*8+e;")
        inner = inner.replace("(2*tokens+key)", "(2*tokens+vkey)")
        inner = inner.replace("(x,y,acc[c])", "(xb,y,acc[c])")
        body = body[:loop_start] + body[loop_end + 1:]
        after_sum = "  sum=__builtin_amdgcn_wmma_f32_16x16x16_f16_w32_gfx12(x,ones,sum);\n"
        assert body.count(after_sum) == 1
        body = body.replace(after_sum, after_sum + inner + "\n", 1)
        assert body == new[c:d], "import changes more than the cache lifetime and loop schedule"
        # No new export arguments, reuse gates, or unrelated Linux changes.
        assert "reuse_gate" not in new
        for tokens in (256, 400, 640):
            for suffix in ("", "_bytein", "_bytein_bout"):
                signature = (f"WAVE void vit_attention_fused_{tokens}{suffix}"
                             "(const float*in,float*out,uint tokens)")
                assert signature in new
        bad = Path(temporary) / "changed.hip"
        bad.write_text(old + "\n")
        try:
            generate(bad, upstream, output)
        except ValueError:
            pass
        else:
            raise AssertionError("unverified source accepted")


def prove_operands(tokens: int) -> int:
    # The source's QK/exp and rounding are unchanged (checked above). Distinct
    # tags represent their already-packed xb bytes, exposing wrong rows, tiles,
    # head offsets, or byte order without relying on coincidentally equal data.
    checked = 0
    stride = tokens + 16
    for head in (0, 31):
        for first in sorted({0, tokens - 16}):
            staged = {}
            for key in range(0, tokens, 16):
                for lane in range(32):
                    row, group = lane & 15, lane >> 4
                    for e in range(8):
                        index = row * stride + key + group * 8 + e
                        assert index not in staged
                        staged[index] = (head, first + row, key + group * 8 + e)
            for lane in range(32):
                row, group = lane & 15, lane >> 4
                old_sum_order, new_sum_order = [], []
                old_pv, new_pv = [[], []], [[], []]
                for key in range(0, tokens, 16):
                    old_sum_order.append(key)
                    new_sum_order.append(key)
                    xb = tuple((head, first + row, key + group * 8 + e) for e in range(8))
                    from_cache = tuple(staged[row * stride + key + group * 8 + e] for e in range(8))
                    assert xb == from_cache
                    for column in range(2):
                        old_v = tuple((2 * tokens + key + group * 8 + e) * 1024
                                      + head * 32 + column * 16 + row for e in range(8))
                        new_v = tuple((2 * tokens + key + group * 8 + e) * 1024
                                      + head * 32 + column * 16 + row for e in range(8))
                        assert max(new_v) < 3 * tokens * 1024
                        old_pv[column].append((from_cache, old_v))
                        new_pv[column].append((xb, new_v))
                        checked += 1
                assert old_sum_order == new_sum_order
                assert old_pv == new_pv
    # Only one wave accesses the two score tiles; both mappings stay within
    # the 1536-byte allocation, with the original barrier after each store.
    for tile in (0, 1):
        writes = {}
        for lane in range(32):
            row, group = lane & 15, lane >> 4
            for e in range(8):
                offset = tile * 16 * 24 + (group * 8 + e) * 24 + row
                assert offset < 2 * 16 * 24 and offset not in writes
                writes[offset] = (group * 8 + e, row)
        for lane in range(32):
            row, group = lane & 15, lane >> 4
            for e in range(8):
                offset = tile * 16 * 24 + row * 24 + group * 8 + e
                assert writes[offset] == (row, group * 8 + e)
    return checked


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("baseline", type=Path)
    parser.add_argument("upstream", type=Path)
    args = parser.parse_args()
    prove_source(args.baseline, args.upstream)
    total = sum(prove_operands(tokens) for tokens in range(16, 641, 16))
    print(f"PASS: {total} ordered PV operands; all 40 supported token counts; source/ABI preservation")
