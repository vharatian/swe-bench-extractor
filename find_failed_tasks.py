#!/usr/bin/env python3
"""
Scan nested report.json files to collect unresolved instance_ids,
then filter a hardcoded JSONL file to keep only those unresolved items.

- No command-line args; all paths are hardcoded below.
- Robust to "report.json" vs accidental "repot.json".
- Writes a few helpful outputs in OUT_DIR.
"""

from __future__ import annotations
from pathlib import Path
import json
from itertools import chain

# ──────────────────────────────────────────────────────────────────────────────
# Hardcoded paths — adjust these constants if your layout differs
REPORTS_ROOT = Path("files/log-backup")         # contains many subfolders, each with a report.json
JSONL_PATH   = Path("files/delivery/batch_5/batch_5-final.jsonl")  # the big JSONL to filter
OUT_DIR      = Path("files/out_unresolved")
OUT_DIR.mkdir(parents=True, exist_ok=True)

UNRESOLVED_TXT   = OUT_DIR / "unresolved_instance_ids.txt"
UNRESOLVED_JSON  = OUT_DIR / "unresolved_instance_ids.json"
FILTERED_JSONL   = OUT_DIR / "batch_5-final.filtered_unresolved.jsonl"
SUMMARY_JSON     = OUT_DIR / "per_report_unresolved_summary.json"
# ──────────────────────────────────────────────────────────────────────────────

def load_unresolved_from_report(report_path: Path) -> list[str]:
    """
    Each report.json looks like:
    {
      "apache__camel-17682": {
         "resolved": true/false,
         ...
      },
      "apache__foo-123": { ... }
    }
    Return list of keys whose 'resolved' is False (missing treated as False).
    """
    with report_path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    unresolved: list[str] = []
    if isinstance(data, dict):
        for instance_id, details in data.items():
            if not isinstance(details, dict):
                continue
            # Treat missing 'resolved' as False → unresolved
            if details.get("resolved", False) is False:
                unresolved.append(str(instance_id))
    return unresolved


def collect_all_unresolved(root: Path) -> tuple[set[str], dict[str, list[str]]]:
    """
    Walk REPORTS_ROOT for files named report.json (or repot.json),
    collect all unresolved instance_ids into a set.
    Also return a per-file summary (for debugging/auditing).
    """
    report_files = list(chain(root.rglob("report.json"), root.rglob("repot.json")))
    per_file: dict[str, list[str]] = {}
    all_unresolved: set[str] = set()

    for rp in sorted(report_files):
        try:
            items = load_unresolved_from_report(rp)
        except Exception as e:
            print(f"[WARN] Skipping {rp}: {e}")
            continue
        per_file[str(rp)] = items
        all_unresolved.update(items)

    return all_unresolved, per_file


def filter_jsonl_by_instance_ids(src_jsonl: Path, keep_ids: set[str], dst_jsonl: Path) -> int:
    """
    Read JSONL lines; keep only those whose 'instance_id' is in keep_ids.
    Return count of kept lines.
    """
    kept = 0
    with src_jsonl.open("r", encoding="utf-8") as fin, dst_jsonl.open("w", encoding="utf-8") as fout:
        for line in fin:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                # Non-JSON line; skip silently
                continue
            instance_id = obj.get("instance_id")
            if instance_id in keep_ids:
                fout.write(json.dumps(obj, ensure_ascii=False) + "\n")
                kept += 1
    return kept


def main() -> None:
    # 1) Gather all unresolved instance_ids from nested reports
    all_unresolved, per_file = collect_all_unresolved(REPORTS_ROOT)

    # 2) Persist unresolved sets for visibility/debugging
    UNRESOLVED_TXT.write_text("\n".join(sorted(all_unresolved)), encoding="utf-8")
    UNRESOLVED_JSON.write_text(json.dumps(sorted(all_unresolved), ensure_ascii=False, indent=2), encoding="utf-8")
    SUMMARY_JSON.write_text(json.dumps(per_file, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[INFO] Found {len(all_unresolved)} unresolved instance_id(s).")
    print(f"[INFO] Wrote list to: {UNRESOLVED_TXT}")
    print(f"[INFO] JSON list saved to: {UNRESOLVED_JSON}")
    print(f"[INFO] Per-report summary saved to: {SUMMARY_JSON}")

    # 3) Filter the hardcoded JSONL by the unresolved instance_ids
    kept = filter_jsonl_by_instance_ids(JSONL_PATH, all_unresolved, FILTERED_JSONL)
    print(f"[INFO] Filtered JSONL written: {FILTERED_JSONL} (kept {kept} lines)")


if __name__ == "__main__":
    main()