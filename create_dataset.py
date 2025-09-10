#!/usr/bin/env python3
"""
Collect small, recent test-related PRs for the repos in data/final_repos.txt
and save one JSON file per repo in data/prs/.

A qualifying PR must:
  • be MERGED within the last 365 days
  • touch ≤ 5 files in total
  • touch ≥ 1 path that contains 'test'
  • touch ≥ 1 path that ends with '.java' and DOES NOT contain 'test'

For every PR we store:
  • pr_number, repo
  • base_commit (baseRefOid)
  • head_commit (headRefOid)
  • merge_commit (mergeCommit.oid)
  • files → list[{path, patch}]

Requirements
------------
Python ≥ 3.8
pip install requests tqdm python-dateutil dotenv
export GITHUB_TOKEN=<PAT with repo-read scope>
"""
from __future__ import annotations
import json
import os
import sys
import time

import requests
from pathlib import Path
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, List
from dateutil.parser import isoparse
import dotenv

dotenv.load_dotenv()

# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #
TOKEN = os.getenv("GITHUB_TOKEN")
if not TOKEN:
    sys.exit("❌  Please export GITHUB_TOKEN with a Personal-Access-Token.")

HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "Accept":        "application/vnd.github+json"
}
GRAPHQL_URL = "https://api.github.com/graphql"

REPOS_FILE = Path("files/final_repos.txt")
OUTPUT_DIR = Path("files/prs")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# YEAR_AGO = datetime.now(timezone.utc) - timedelta(days=566)
CUTOFF_DATE = datetime(2024, 1, 1, tzinfo=timezone.utc)

# --------------------------------------------------------------------------- #
# GraphQL helpers
# --------------------------------------------------------------------------- #
# ─── progress bars ────────────────────────────────────────────────────────────
from tqdm import tqdm
repo_bar = tqdm(desc="Repositories", unit="repo")
api_bar  = tqdm(desc="HTTP requests", unit="req", position=1, leave=False)

# ─── GraphQL helper ───────────────────────────────────────────────────────────
def gql(query: str, variables: Dict[str, Any], *, max_attempts: int = 3) -> Dict[str, Any]:
    """POST a GraphQL query with up to `max_attempts` attempts total."""
    last_err = None
    for attempt in range(1, max_attempts + 1):
        try:
            api_bar.update(1)  # ← tick before each POST/attempt
            r = requests.post(
                GRAPHQL_URL,
                headers=HEADERS,
                json={"query": query, "variables": variables},
                timeout=30,  # good practice
            )
            if r.status_code != 200:
                raise RuntimeError(f"HTTP {r.status_code}: {r.text[:200]}…")

            body = r.json()
            if body.get("errors"):
                # If you *don't* want to retry on GraphQL errors, raise a subclass and handle it below.
                raise RuntimeError(f"GraphQL errors: {body['errors']}")

            return body["data"]

        except Exception as exc:
            print(f"⚠️  Error in attempt {attempt} for {variables['owner']}/{variables['name']}: {exc}")
            if attempt == max_attempts:
                raise exc # out of attempts; bubble up the last error

            time.sleep(1)

PRS_QUERY = """
query ($owner:String!,$name:String!,$cursor:String) {
  repository(owner:$owner, name:$name) {
    pullRequests(first:100, after:$cursor, states:[MERGED],
                 orderBy:{field:CREATED_AT, direction:DESC}) {
      pageInfo { hasNextPage endCursor }
      nodes {
        number
        mergedAt
        createdAt
        updatedAt        
        baseRefOid
        headRefOid
        mergeCommit { oid }
        files(first:1) {                       # only need the count here
          totalCount
        }
      }
    }
  }
}
"""

# ─────────────────────────────────────────────────────────────────────────────
# 2. Helper: fetch file list + patches via REST v3
# ─────────────────────────────────────────────────────────────────────────────
REST_API = "https://api.github.com"

def rest_pull_files(owner: str, repo: str, pr_number: int):
    api_bar.update(1)                     # ← tick for each GET
    url = f"{REST_API}/repos/{owner}/{repo}/pulls/{pr_number}/files?per_page=100"
    r = requests.get(url, headers=HEADERS, timeout=30)
    if r.headers.get("X-RateLimit-Remaining") == "0":
        raise RuntimeError(f"Request rate limit exceeded")

    if r.status_code != 200:
        print("⚠️  Error fetching files for PR", pr_number, "in", f"{owner}/{repo}")
        return None
    return r.json()         # each element has filename, patch, etc.

# ─────────────────────────────────────────────────────────────────────────────
# 3. Filtering + data collection
# ─────────────────────────────────────────────────────────────────────────────

def is_test(path: str) -> bool:
    p = path.lower()
    return "test/" in p or "tests/" in p or p.endswith("test.java") or p.endswith("it.java")

def pr_matches_and_collect(owner: str, repo: str, pr: dict) -> dict | None:
    """
    Return a complete PR record (incl. per-file patch) OR None if it doesn’t
    satisfy the rules.
    """
    if not pr["createdAt"] or isoparse(pr["createdAt"]) < CUTOFF_DATE:
        return None
    # if pr["files"]["totalCount"] > 5:
    #     return None

    # one REST call because we may need the patches anyway
    files = rest_pull_files(owner, repo, pr["number"])
    if not files:
        return None

    paths = []
    for f in files:
        paths.append(f["filename"])
        if f["status"] == "renamed" and "previous_filename" in f:
            paths.append(f["previous_filename"])

    modified_test = [p for p in paths if is_test(p)]
    modified_source = [p for p in paths if not is_test(p)]
    modified_java = [p for p in modified_source if p.endswith(".java")]


    if not any(modified_test) or not any(modified_java):
        return None

    results = {
        "pr_number": pr["number"],
        "repo": f"{owner}/{repo}",
        "merged_at": pr["mergedAt"],
        "created_at": pr["createdAt"],
        "updated_at": pr["updatedAt"],
        "base_commit": pr["baseRefOid"],
        "head_commit": pr["headRefOid"],
        "merge_commit": pr["mergeCommit"]["oid"] if pr["mergeCommit"] else None,
        "modified_test": modified_test,
        "modified_source": modified_source
    }
    # 2️⃣  build the 'files' array for the final JSON
    # files_json: list[dict] = []
    # for f in files:
    #     files_json.append({"path": f["filename"], "patch": f.get("patch") or ""})
    #     if f["status"] == "renamed" and "previous_filename" in f:
    #         files_json.append(
    #             {"path": f["previous_filename"], "patch": f.get("patch") or ""}
    #         )
    #
    # results["files"] = files_json

    # build the final record
    return results

# ─────────────────────────────────────────────────────────────────────────────
# 4. Main loop (inside collect_prs)
# ─────────────────────────────────────────────────────────────────────────────
def collect_prs(owner: str, name: str) -> list[dict]:
    prs: list[dict] = []
    cursor = None
    while True:
        try:
            data = gql(PRS_QUERY, {"owner": owner, "name": name, "cursor": cursor})
            page = data["repository"]["pullRequests"]

            for node in page["nodes"]:
                rec = pr_matches_and_collect(owner, name, node)
                if rec:
                    prs.append(rec)
                # early stop as soon as we fall out of the 1-year window
                elif node["createdAt"] and isoparse(node["createdAt"]) < CUTOFF_DATE:
                    return prs

            if not page["pageInfo"]["hasNextPage"]:
                return prs
            cursor = page["pageInfo"]["endCursor"]
        except Exception as e:
            print(f"⚠️  Error processing {owner}/{name}: {e}")
            return prs


# --------------------------------------------------------------------------- #
# Run
# --------------------------------------------------------------------------- #
repos = [l.strip() for l in REPOS_FILE.read_text().splitlines() if l.strip()]
repo_bar = tqdm(repos, desc="Repositories", unit="repo")
for repo in repo_bar:
    owner, name = repo.split("/", 1)
    pr_list = collect_prs(owner, name)

    if pr_list and len(pr_list) > 0:
        outfile = OUTPUT_DIR / f"{owner}_{name}.json"
        with outfile.open("w", encoding="utf-8") as f:
            json.dump(pr_list, f, indent=2)
        tqdm.write(f"✅  {repo}: {len(pr_list)} PRs → {outfile}")
    else:
        tqdm.write(f"➖  {repo}: no qualifying PRs")
