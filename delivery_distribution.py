#!/usr/bin/env python3
"""
Hard-coded repo distribution plotter for two sources:
1. batch_* sub-folders with *.jsonl files            (original source)
2. A list of CSV files located in a single folder    (new source)

Run:
    python repo_distribution_hardcoded.py
"""

from collections import Counter
from pathlib import Path
import csv
import json
import matplotlib.pyplot as plt

# ─── HARD-CODED SETTINGS ───────────────────────────────────────────────────────
ROOT_DIR  = Path("files/delivery")          # batch_* folders live here
CSV_DIR   = Path("files/tasks")             # folder that holds the CSVs
CSV_FILES = [f"batch{i}.csv" for i in range(7, 10)]
TOP_N     = None                            # e.g. 20, or None for all
OUTPUT_FILE = Path("files/delivery/repo_distribution.png")

# Starting counts for selected repositories (use *short* repo names)
INITIAL_COUNTS = {
    "curator": 2,
    "jena": 1,
    "mapstruct": 1,
    "dolphinscheduler": 1,
}
# ────────────────────────────────────────────────────────────────────────────────


def collect_from_jsonl(counts: Counter) -> None:
    """Increment counts from batch_*/*.jsonl under ROOT_DIR (mutates counts)."""
    for batch_dir in ROOT_DIR.glob("batch_*"):
        if not batch_dir.is_dir():
            continue

        jsonl_files = list(batch_dir.glob("*.jsonl"))
        if len(jsonl_files) != 1:
            print(f"[warning] {batch_dir} has {len(jsonl_files)} .jsonl files; skipping")
            continue

        jsonl_path = jsonl_files[0]
        with jsonl_path.open(encoding="utf-8") as fh:
            for line in fh:
                try:
                    repo_full = json.loads(line)["repo"]
                    repo = repo_full.split("/")[-1]
                    counts[repo] += 1
                except Exception:
                    print(f"[warning] bad line in {jsonl_path}")


def collect_from_csv(counts: Counter) -> None:
    """Increment counts from the hard-coded CSV files (mutates counts)."""
    for fname in CSV_FILES:
        csv_path = CSV_DIR / fname
        if not csv_path.is_file():
            print(f"[warning] {csv_path} not found; skipping")
            continue

        with csv_path.open(newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            if "metadata" not in reader.fieldnames:
                print(f"[warning] {csv_path} lacks 'metadata' column; skipping")
                continue

            for row in reader:
                try:
                    meta = json.loads(row["metadata"])
                    repo_full = meta["Repository"]
                    repo = repo_full.split("/")[-1]
                    counts[repo] += 1
                except Exception:
                    print(f"[warning] bad metadata row in {csv_path}")


def plot_counts(counts: Counter) -> None:
    """Draw and save the bar chart."""
    if TOP_N is not None:
        counts = Counter(dict(counts.most_common(TOP_N)))

    if not counts:
        print("No repos found—check your folders/filenames.")
        return

    repos, freqs = zip(*counts.most_common())
    plt.figure(figsize=(max(6, 0.35 * len(repos)), 4))
    plt.bar(range(len(repos)), freqs)
    plt.xticks(range(len(repos)), repos, rotation=90, ha="center")
    plt.ylabel("Occurrences")
    plt.title("Repository distribution")
    plt.tight_layout()
    plt.savefig(OUTPUT_FILE, dpi=150)
    try:
        plt.show()
    except Exception:
        pass  # headless environment


if __name__ == "__main__":
    # Seed the counter with the pre-set starting values
    repo_counts = Counter(INITIAL_COUNTS)

    # Add counts from the two data sources
    collect_from_jsonl(repo_counts)
    collect_from_csv(repo_counts)

    print("Top repositories:")
    for repo, n in repo_counts.most_common(TOP_N):
        print(f"{repo}: {n}")

    plot_counts(repo_counts)
    print(f"Chart saved to {OUTPUT_FILE.resolve()}")
