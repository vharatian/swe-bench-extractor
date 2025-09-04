#!/usr/bin/env python3
"""
generate_patches_from_lists.py  - robust + explicit error logging

- No `git restore` / no worktrees (diff commits directly).
- Fetches PR refs when needed (fork PRs).
- Filters path list to ones present in at least one side.
- Logs clear WARN/ERROR messages:
    * If a patch can't be created, prints [WARN] with reason(s).
    * If neither gold nor test patch is created for a PR, prints [ERROR] with all reasons.

Input JSON entries must include:
  - task_id, repo, base_commit, patch_commit
  - modified_code: List[str]
  - modified_tests: List[str]   (we also accept "modified_test")
"""

import json
import subprocess
import sys
from pathlib import Path
from typing import List, Dict, Optional

from tqdm import tqdm

from delivery.config import BATCH_NAME

# --------------- Configuration & Paths ---------------
DEL_ROOT     = Path("../files/delivery") / BATCH_NAME
REPOS_ROOT   = Path("../files/repos")
IN_FILE      = DEL_ROOT / f"{BATCH_NAME}.json"
OUT_FILE     = DEL_ROOT / f"{BATCH_NAME}-patched.json"

# --------------- Small utils ---------------
def _print_err(msg: str) -> None:
    print(msg, file=sys.stderr)

def _run(cmd: List[str], check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, check=check, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

# --------------- Git helpers ---------------
def ensure_repo(repo: str) -> Path:
    """
    Clone (if needed) a bare mirror of the repo and ensure it fetches PR refs.
    Returns the path to the bare mirror repo.
    """
    owner, name = repo.split("/", 1)
    mirror = REPOS_ROOT / f"{owner}__{name}.git"
    if not mirror.exists():
        mirror.parent.mkdir(parents=True, exist_ok=True)
        print(f"[INFO] Cloning mirror for {repo}…")
        _run(["git", "clone", "--mirror", f"https://github.com/{repo}.git", str(mirror)])

    # Ensure PR refs are fetched too (idempotent).
    try:
        existing = subprocess.check_output(
            ["git", "--git-dir", str(mirror), "config", "--get-all", "remote.origin.fetch"],
            text=True
        ).splitlines()
    except subprocess.CalledProcessError:
        existing = []
    if not any("refs/pull/*" in line for line in existing):
        _run(["git", "--git-dir", str(mirror),
              "config", "--add", "remote.origin.fetch", "+refs/pull/*:refs/pull/*"], check=False)

    # Keep the mirror reasonably fresh.
    _run(["git", "--git-dir", str(mirror), "fetch", "--prune", "origin"], check=False)

    return mirror

def _commit_exists(mirror: Path, rev: str) -> bool:
    return subprocess.run(
        ["git", "--git-dir", str(mirror), "cat-file", "-e", f"{rev}^{{commit}}"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    ).returncode == 0

def _blob_exists(mirror: Path, rev: str, path: str) -> bool:
    return subprocess.run(
        ["git", "--git-dir", str(mirror), "cat-file", "-e", f"{rev}:{path}"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    ).returncode == 0

def _ensure_commits_available(mirror: Path, base: str, head: str, pr_id: Optional[str], reasons: List[str]) -> None:
    """
    Best-effort: fetch origin and, if head is missing and we have a PR id,
    fetch the PR head/merge refs.
    """
    _run(["git", "--git-dir", str(mirror), "fetch", "--prune", "origin"], check=False)

    if not _commit_exists(mirror, base):
        reasons.append(f"base commit {base[:12]} missing")
        _run(["git", "--git-dir", str(mirror), "fetch", "origin", "--tags"], check=False)

    if not _commit_exists(mirror, head):
        if pr_id:
            # Try GitHub PR conventions
            _run(["git", "--git-dir", str(mirror), "fetch", "origin",
                  f"pull/{pr_id}/head:refs/pull/{pr_id}/head"], check=False)
            _run(["git", "--git-dir", str(mirror), "fetch", "origin",
                  f"pull/{pr_id}/merge:refs/pull/{pr_id}/merge"], check=False)
        if not _commit_exists(mirror, head):
            reasons.append(f"head commit {head[:12]} missing")

def _unique_preserve_order(items: List[str]) -> List[str]:
    seen = set()
    out = []
    for x in items:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out

def run_git_diff(
    mirror: Path,
    base: str,
    head: str,
    paths: List[str],
    pr_id: Optional[str] = None,
) -> (str, List[str]):
    """
    Produce a unified diff for <paths> between <base> and <head>.
    Returns (diff_text, reasons). reasons is non-empty when something prevented diffing.
    If diff_text is empty but there were valid paths and commits, that likely means "no changes".
    """
    reasons: List[str] = []
    _ensure_commits_available(mirror, base, head, pr_id, reasons)

    if not _commit_exists(mirror, base) or not _commit_exists(mirror, head):
        return ("", reasons or ["commits not available after fetch"])

    # Filter to paths present in either tree (handles add/delete/rename).
    paths = _unique_preserve_order(paths or [])
    filtered = [p for p in paths if _blob_exists(mirror, base, p) or _blob_exists(mirror, head, p)]
    if not paths:
        reasons.append("no paths provided")
        return ("", reasons)
    if not filtered:
        reasons.append("none of the provided paths exist in base or head")
        return ("", reasons)

    try:
        diff = subprocess.check_output(
            ["git", "--git-dir", str(mirror),
             "diff", "--no-color", "--find-renames", base, head, "--"] + filtered,
            text=True
        )
        return (diff, reasons)
    except subprocess.CalledProcessError as e:
        reasons.append(f"git diff failed with code {e.returncode}")
        return ("", reasons)

# --------------- Main ---------------
def main():
    if not IN_FILE.exists():
        sys.exit(f"[ERROR] Input file not found: {IN_FILE}")

    entries: List[Dict] = json.loads(IN_FILE.read_text(encoding="utf-8"))
    patched: List[Dict] = []

    REPOS_ROOT.mkdir(parents=True, exist_ok=True)

    total_errors = 0

    for entry in tqdm(entries, desc="Generating patches"):
        repo        = entry["repo"]
        base_commit = entry["base_commit"]
        head_commit = entry["patch_commit"]

        # Accept both keys; prefer the plural if present.
        code_paths  = entry.get("modified_code", []) or []
        test_paths  = entry.get("modified_tests", entry.get("modified_test", [])) or []

        # Heuristic: use task_id as PR number if it looks like one.
        pr_id = None
        tid = entry.get("task_id")
        if isinstance(tid, int) or (isinstance(tid, str) and tid.isdigit()):
            pr_id = str(tid)

        mirror = ensure_repo(repo)

        gold_patch, gold_reasons = run_git_diff(mirror, base_commit, head_commit, code_paths, pr_id=pr_id)
        test_patch, test_reasons = run_git_diff(mirror, base_commit, head_commit, test_paths, pr_id=pr_id)

        # Per-patch warnings when empty
        if not gold_patch:
            if gold_reasons:
                _print_err(f"[WARN] gold patch empty for {repo}#{entry.get('task_id')}: " +
                           "; ".join(gold_reasons))
            else:
                _print_err(f"[WARN] gold patch empty (no changes) for {repo}#{entry.get('task_id')}")

        if not test_patch:
            if test_reasons:
                _print_err(f"[WARN] test patch empty for {repo}#{entry.get('task_id')}: " +
                           "; ".join(test_reasons))
            else:
                _print_err(f"[WARN] test patch empty (no changes) for {repo}#{entry.get('task_id')}")

        # If neither patch could be produced, escalate to ERROR (per your request)
        if not gold_patch and not test_patch:
            all_reasons = list(dict.fromkeys((gold_reasons or []) + (test_reasons or [])))
            if not all_reasons:
                all_reasons = ["no diff produced for provided paths"]
            _print_err(f"[ERROR] no patches created for {repo}#{entry.get('task_id')}: " +
                       "; ".join(all_reasons))
            total_errors += 1

        entry["gold_patch"] = gold_patch
        entry["test_patch"] = test_patch
        patched.append(entry)

    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with OUT_FILE.open("w", encoding="utf-8") as f:
        json.dump(patched, f, indent=4, ensure_ascii=False)

    if total_errors > 0:
        _print_err(f"[ERROR] Finished with {total_errors} PR(s) producing no patches. Output: {OUT_FILE}")
    else:
        print(f"✔ Wrote {len(patched)} entries with new patches → {OUT_FILE}")

if __name__ == "__main__":
    main()
