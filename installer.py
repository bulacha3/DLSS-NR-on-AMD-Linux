#!/usr/bin/env python3
"""Guided installer entry point; model conversion dependencies are managed locally."""
import sys

if sys.version_info < (3, 11):
    sys.exit('Python 3.11 or newer is required. Run with a supported Python interpreter.')
sys.dont_write_bytecode = True
from dlssnr.cli import main

if __name__ == '__main__':
    sys.exit(main())
