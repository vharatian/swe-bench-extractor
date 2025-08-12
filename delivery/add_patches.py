#!/usr/bin/env python3
"""
generate_patches_from_lists.py

For each entry in batch_1-patched.json (JSON array), use its
modified_code / modified_tests lists to generate gold_patch and test_patch
directly via `git diff` on those paths, using git restore to handle new files.

Prerequisites:
  • a prior JSON with keys:
      - task_id, repo, base_commit, patch_commit
      - modified_code: List[str]
      - modified_tests: List[str]
  • Git installed
  • Repos will be cloned as bare mirrors under ../files/repos/owner__name.git
"""

import json
import subprocess
import sys
from pathlib import Path
from typing import List, Dict

from tqdm import tqdm

from delivery.config import BATCH_NAME

# --------------- Configuration & Paths ---------------
DEL_ROOT     = Path("../files/delivery") / BATCH_NAME
REPOS_ROOT   = Path("../files/repos")
IN_FILE      = DEL_ROOT / f"{BATCH_NAME}.json"
OUT_FILE     = DEL_ROOT / f"{BATCH_NAME}-patched.json"

WORKTREE_DIR = REPOS_ROOT / "__worktrees__"

# --------------- Git Helpers ---------------
def ensure_repo(repo: str) -> Path:
    """
    Clone a bare mirror of the repository if it doesn't exist,
    returning the path to the bare repo.
    """
    owner, name = repo.split("/", 1)
    mirror = REPOS_ROOT / f"{owner}__{name}.git"
    if not mirror.exists():
        mirror.parent.mkdir(parents=True, exist_ok=True)
        print(f"Cloning {repo}…")
        subprocess.run(
            ["git", "clone", "--mirror", f"https://github.com/{repo}.git", str(mirror)],
            check=True,
        )
    return mirror

def run_git_diff(
    mirror: Path,
    base: str,
    head: str,
    paths: List[str]
) -> str:
    """
    Create (or reuse) a detached worktree at base_commit, restore only
    the given paths from head_commit using git restore, diff those paths,
    then reset.
    """
    # 1) Prepare worktree directory
    wt = WORKTREE_DIR / mirror.name
    if not wt.exists():
        wt.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["git", "--git-dir", str(mirror),
             "worktree", "add", "--detach", "--quiet", str(wt), base],
            check=True
        )

    # 2) Restore only the selected files to head (handles new files)
    subprocess.run(
        ["git", "--git-dir", str(mirror),
         "--work-tree", str(wt),
         "restore", "--source", head, "--"] + paths,
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )

    # 3) Run diff for those paths
    diff = subprocess.check_output(
        ["git", "--git-dir", str(mirror),
         "--work-tree", str(wt),
         "diff", "--no-color", "--find-renames", base, head, "--"] + paths,
        text=True
    )

    # 4) Reset worktree back to base for next entry
    subprocess.run(
        ["git", "--git-dir", str(mirror),
         "--work-tree", str(wt),
         "reset", "--hard", base],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )

    return diff

# --------------- Main ---------------
def main():
    if not IN_FILE.exists():
        sys.exit(f"[ERROR] Input file not found: {IN_FILE}")

    # Load JSON array of entries
    entries: List[Dict] = json.loads(IN_FILE.read_text(encoding="utf-8"))
    patched: List[Dict] = []

    # Ensure directories exist
    REPOS_ROOT.mkdir(parents=True, exist_ok=True)
    WORKTREE_DIR.mkdir(parents=True, exist_ok=True)

    for entry in tqdm(entries, desc="Generating patches"):
        repo        = entry["repo"]
        base_commit = entry["base_commit"]
        head_commit = entry["patch_commit"]
        code_paths  = entry.get("modified_code", [])
        test_paths  = entry.get("modified_test", [])

        mirror = ensure_repo(repo)

        # Generate gold_patch for production code changes
        gold_patch = ""
        if code_paths:
            try:
                gold_patch = run_git_diff(mirror, base_commit, head_commit, code_paths)
            except subprocess.CalledProcessError as e:
                print(f"[WARN] gold diff failed for {repo}#{entry['task_id']}: {e}")

        # Generate test_patch for test changes
        test_patch = ""
        if test_paths:
            try:
                test_patch = run_git_diff(mirror, base_commit, head_commit, test_paths)
            except subprocess.CalledProcessError as e:
                print(f"[WARN] test diff failed for {repo}#{entry['task_id']}: {e}")

        entry["gold_patch"] = gold_patch
        entry["test_patch"] = test_patch
        patched.append(entry)

    # Write out final JSON array, indented with 4 spaces
    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with OUT_FILE.open("w", encoding="utf-8") as f:
        json.dump(patched, f, indent=4, ensure_ascii=False)

    print(f"✔ Wrote {len(patched)} entries with new patches → {OUT_FILE}")

if __name__ == "__main__":
    main()
