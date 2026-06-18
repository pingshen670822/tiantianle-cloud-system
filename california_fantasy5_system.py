#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Compatibility launcher.

Main program has been versioned as:
美國加州天天樂_20260618_第1版.py
"""

from pathlib import Path
import runpy
import sys


MAIN_PROGRAM = Path(__file__).resolve().with_name("美國加州天天樂_20260618_第1版.py")


if not MAIN_PROGRAM.exists():
    raise SystemExit(f"Main program not found: {MAIN_PROGRAM}")

sys.argv[0] = str(MAIN_PROGRAM)
runpy.run_path(str(MAIN_PROGRAM), run_name="__main__")
