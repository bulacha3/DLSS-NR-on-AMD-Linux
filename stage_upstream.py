#!/usr/bin/env python3
"""Verify the original v0.3.0 setup without executing or changing it."""
import argparse
import json
from pathlib import Path
from dlssnr.upstream import inspect_setup, read_setup


def verify(path):
    return inspect_setup(read_setup(path))[2]


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('setup', type=Path)
    args = parser.parse_args()
    try:
        print(json.dumps(verify(args.setup), indent=2))
    except (OSError, ValueError) as error:
        parser.exit(1, f'Verification failed: {error}\n')
