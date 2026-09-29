#!/usr/bin/env python3
"""Guided installer entry point; model conversion dependencies are managed locally."""
import sys

if sys.version_info < (3, 10):
    sys.exit('Python 3.10 or newer is required; nothing installed. Use PYTHON=/path/to/python3.10 ./install.sh (or a newer interpreter).')
sys.dont_write_bytecode = True
from dlssnr.cli import main

if __name__ == '__main__':
    sys.exit(main())
