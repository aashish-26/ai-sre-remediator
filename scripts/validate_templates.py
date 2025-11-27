#!/usr/bin/env python3
"""Validate YAML files under `templates/` and exit non-zero on errors.

Run from project root: `python scripts/validate_templates.py`
"""
import sys
from pathlib import Path
import yaml

errors = 0
for p in Path("templates").glob("*.yaml"):
    try:
        yaml.safe_load(p.read_text(encoding="utf-8") or "{}")
        print("OK:", p)
    except Exception as e:
        print("ERROR:", p, "->", e)
        errors += 1

sys.exit(errors)
