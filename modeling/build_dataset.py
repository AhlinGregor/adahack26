#!/usr/bin/env python3
"""Convenience wrapper: build the harmonised dataset.

    python build_dataset.py                       # full build, default output dir
    python build_dataset.py --limit 5000          # quick test
    python build_dataset.py --sources measurements,cams

Equivalent to ``python -m airdata build`` with the same arguments.
"""

from __future__ import annotations

import sys

from airdata.cli import main

if __name__ == "__main__":
    if len(sys.argv) == 1:
        sys.argv.append("build")
    raise SystemExit(main())
