#!/usr/bin/env python3
"""Embed bs1770gain.exe in Sara package."""

from __future__ import annotations

import shutil
from pathlib import Path

bundle_root = Path(__file__).resolve().parents[2] / "bundle" / "SARA" / "audio" / "vendor" / "windows" / "bs1770gain"
source_root = Path(__file__).resolve().parents[1] / "src" / "sara" / "audio" / "vendor" / "windows" / "bs1770gain"

if bundle_root.exists():
    shutil.rmtree(bundle_root)
bundle_root.mkdir(parents=True, exist_ok=True)
for entry in source_root.iterdir():
    dst = bundle_root / entry.name
    if entry.is_dir():
        shutil.copytree(entry, dst)
    else:
        shutil.copy2(entry, dst)
print(f"Copied bs1770gain assets to {bundle_root}")
