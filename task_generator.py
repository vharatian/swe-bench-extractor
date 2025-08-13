#!/usr/bin/env python3
"""
Collect all JSONL files that match  final*.jsonl  in a chosen directory,
filter each record, and write the consolidated results to

    files/tasks/batch2.jsonl
    files/tasks/batch2.csv
"""

import csv
import json
from itertools import count
from pathlib import Path

# ── configuration ─────────────────────────────────────────────────────────────
INPUT_DIR    = Path("files/run-debezium")   # folder to scan
PATTERN      = "final*.jsonl"                      # filename pattern
OUT_DIR      = Path("files/tasks")                 # where results go
OUTPUT_CSV   = OUT_DIR / "batch7.csv"
MAX_NUMBER   = 30
# ──────────────────────────────────────────────────────────────────────────────


def is_empty(value) -> bool:
    return value is None or (isinstance(value, (list, dict)) and len(value) == 0)


def qualify(rec: dict) -> bool:
    no_errors = "errors" not in rec or is_empty(rec["errors"])
    has_f2p   = isinstance(rec.get("fail2pass"), list) and rec["fail2pass"]
    return no_errors and has_f2p


def build_metadata(rec: dict) -> dict:
    repo = rec.get("repo") or rec.get("Repository")
    pr   = rec.get("pr_number") or rec.get("PR Number")
    link = rec.get("pr_link") or rec.get("PR Link") \
           or (f"https://github.com/{repo}/pull/{pr}" if repo and pr else None)
    return {"Repository": repo, "PR Number": pr, "PR Link": link}


def main() -> None:
    # Find source files
    input_files = sorted(INPUT_DIR.glob(PATTERN))
    if not input_files:
        raise FileNotFoundError(f"No files matching {PATTERN!r} in {INPUT_DIR.resolve()}")

    # Prepare output directory & files
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_CSV.write_text("")

    # Open output writers once
    count = 0
    with OUTPUT_CSV.open("w", encoding="utf-8", newline="") as csvfile:

        csv_writer = csv.DictWriter(csvfile, fieldnames=["metadata"])
        csv_writer.writeheader()

        # Walk through every matching input file
        for infile in input_files:
            with infile.open("r", encoding="utf-8") as fin:
                for line in fin:
                    if not line.strip():
                        continue
                    rec = json.loads(line)
                    if not qualify(rec):
                        continue

                    meta = build_metadata(rec)
                    
                    csv_writer.writerow({"metadata": json.dumps(meta, ensure_ascii=False)})
                    count += 1

                    if count > MAX_NUMBER:
                        break

if __name__ == "__main__":
    main()
