#!/usr/bin/env python3
"""
convert_patched_to_final.py
───────────────────────────
Reads  ../files/delivery/batch_1/batch_1-patched.json   (array)
writes ../files/delivery/batch_1/batch_1-final.jsonl    (one JSON obj per line)

Usage:
  python convert_patched_to_final.py
"""

from pathlib import Path
import json, jsonlines

from delivery.config import BATCH_NAME

# --------------------------------------------------- locations
BATCH_FOLDER = Path("../files/delivery") / BATCH_NAME
IN_FILE      = BATCH_FOLDER / f"{BATCH_NAME}-patched.json"
OUT_FILE     = BATCH_FOLDER / f"{BATCH_NAME}-final.jsonl"

# --------------------------------------------------- convert
if not IN_FILE.exists():
    raise SystemExit(f"[ERROR] input file {IN_FILE} not found")

objects = json.loads(IN_FILE.read_text(encoding="utf-8"))

OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
with jsonlines.open(OUT_FILE, mode="w") as writer:
    writer.write_all(objects)          # one compact line per object

print(f"✓ wrote {len(objects)} objects → {OUT_FILE}")
