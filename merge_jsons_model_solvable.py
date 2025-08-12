#!/usr/bin/env python3
"""
Merge exactly one level of JSON files.

Assumptions
-----------
* `PARENT_DIR/`
      ├── sub1/
      │     └── data.json
      ├── sub2/
      │     └── info.json
      └── deep/
            └── nest/
                 └── ignore_me.json   # ← will be ignored

* Every first-level sub-folder contains at least one `.json`.
* Each JSON file contains a valid JSON value (object, list, number, …).
* All those values are collected into a single Python list and written out.
"""

import json
from pathlib import Path

# -------------- edit these two paths only -------------- #
PARENT_DIR = Path(r"files/model_solvable_1")
OUTPUT_FILE = Path(r"files/delivery/batch_4/raw_1.json")
# ----------------------------------------------------- #

def main() -> None:
    merged: list = []

    for child in PARENT_DIR.iterdir():
        if not child.is_dir():
            continue  # skip files in the parent folder itself

        # grab every *.json directly inside this sub-folder
        for json_path in child.glob("*.json"):
            with json_path.open("r", encoding="utf-8") as f:
                merged.append(json.load(f))

    # dump the combined list
    OUTPUT_FILE.write_text(
        json.dumps(merged, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"👍  Merged {len(merged)} JSON file(s) into {OUTPUT_FILE}")

if __name__ == "__main__":
    main()
