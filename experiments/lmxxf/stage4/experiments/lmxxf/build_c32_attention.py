#!/usr/bin/env python3
"""Generate packed C32 attention with byte-preserving in-place V transpose.

Uses the pinned upstream compiler recipe. No model weights, floating-point
operations, matrix operand order, or kernel arguments change.
"""
import argparse
import hashlib
from pathlib import Path
from build_game_prefix import SOURCE_SHA
from build_game_io import transpose_c32_v

HEADER = ('// Packed C32 attention: in-place transposed V, unchanged neural arithmetic.\n'
          '#define HIP_ISA_HALF 1\n'
          '#define HIP_PREPACKED_WEIGHTS 1\n'
          '#define HIP_C32_DIAG_WEIGHTS 1\n')


def generate_packed(source, output):
    raw = source.read_bytes()
    if hashlib.sha256(raw).hexdigest() != SOURCE_SHA:
        raise RuntimeError('Upstream C32 source hash mismatch')
    output.write_text(HEADER + transpose_c32_v(raw.decode()) + '\n')
    print('Generated', output)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    generate_packed(args.source, args.output)
