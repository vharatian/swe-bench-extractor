from pathlib import Path
import json, yaml, jsonlines
from collections import Counter
from typing import Dict, Any, Tuple, List

from delivery.config import BATCH_NAME
from utils import is_test

# ------------------------------------------------------------------ paths
final_folder    = Path("../files/finals")
delivery_folder = Path("../files/delivery")
batch_folder    = delivery_folder / BATCH_NAME
input_file      = batch_folder / "wrapped.json"
repo_cfg_file   = Path("repo_config.yaml")
out_file        = batch_folder / f"{BATCH_NAME}.json"

# ---------------------------------------------------------------- helpers

def load_yaml(path: Path) -> Dict[str, Any]:
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f) or {}

def load_wrapped(path: Path) -> List[Dict[str, Any]]:
    with path.open(encoding="utf-8") as f:
        return json.load(f).get("form", [])

def is_useful(task: Dict[str, Any]) -> bool:
    for r in task.get("formData", {}).get("ratings", []):
        if r.get("key") == "taskIsUsable":
            return r.get("human_input_value", "").lower() == "yes"
    return False

def get_description(task: Dict[str, Any]) -> str:
    for r in task.get("formData", {}).get("ratings", []):
        if r.get("key") == "taskDescription":
            return r.get("human_input_value", "").strip()
    return ""

def repo_pr_key(task: Dict[str, Any]) -> Tuple[str, int] | None:
    meta  = task.get("metadata", {})
    scope = meta.get("scope_requirements") or meta.get("merged_scope_requirements") or {}
    repo  = scope.get("Repository")
    prnum = scope.get("PR Number")
    try:
        prnum = int(prnum)
    except (TypeError, ValueError):
        return None
    return repo, prnum

def find_payloads(keys: set[Tuple[str, int]]) -> Dict[Tuple[str, int], Dict[str, Any]]:
    hits = {}
    for jf in final_folder.glob("*.jsonl"):
        with jsonlines.open(jf) as rdr:
            for pr in rdr:
                k = (pr.get("repo"), pr.get("pr_number"))
                if k in keys and k not in hits:
                    hits[k] = pr
                if len(hits) == len(keys):
                    return hits
    return hits

# ---------------------------------------------------------------- load config
repo_cfg = load_yaml(repo_cfg_file)
stats    = Counter()

# ---------------------------------------------------------------- step 1 – collect useful tasks
useful: Dict[Tuple[str, int], Dict[str, Any]] = {}
for t in load_wrapped(input_file):
    key = repo_pr_key(t)
    if not key:
        stats["missing_repo_or_pr"] += 1
        continue
    if is_useful(t):
        useful[key] = {"task": t}
        stats["useful"] += 1
    else:
        stats["unuseful"] += 1

# ---------------------------------------------------------------- step 2 – attach PR payloads
payloads = find_payloads(set(useful.keys()))
for k, rec in useful.items():
    rec["payload"] = payloads.get(k)

# ---------------------------------------------------------------- step 3 – build final objects
prepared: List[Dict[str, Any]] = []


def get_modified_files(files):
    modified_code = []
    modified_test = []
    for f in files:
        path = f["path"]
        if is_test(path):
            modified_test.append(path)
        else:
            modified_code.append(path)

    return modified_code, modified_test


for (repo, prnum), rec in useful.items():
    task = rec["task"]
    pr   = rec["payload"]
    cfg  = repo_cfg.get(repo)

    if not pr:
        stats["missing_payload"] += 1
        print(f"[ERROR] No payload for {repo}#{prnum}; skipping")
        continue
    if not cfg:
        stats["missing_cfg"] += 1
        print(f"[ERROR] No Docker config for {repo}; skipping task {repo}#{prnum}")
        continue

    docker_path = cfg["dockerfile"]
    if "/docker/" in docker_path:
        docker_path = docker_path.replace("/docker/", "/docker_files/")
    docker_path = Path(docker_path).expanduser().resolve()

    try:
        docker_text = docker_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        stats["dockerfile_not_found"] += 1
        print(f"[ERROR] Dockerfile not found at {docker_path}; skipping {repo}#{prnum}")
        continue

    if "files" in pr:
        modified_code, modified_test = get_modified_files(pr["files"])
    else:
        modified_code = pr["modified_source"]
        modified_test = pr["modified_test"]

    prepared.append({
        "task_id"          : f"{repo}#{prnum}",
        "instance_id"      : f"{repo.replace('/', '__')}-{prnum}",
        "repo"             : pr.get("repo"),
        "patch_commit"     : pr.get("head_commit"),
        "base_commit"      : pr.get("base_commit"),
        "merge_commit"     : pr.get("merge_commit"),
        "problem_statement": get_description(task),
        "language"         : "Java",
        "dockerfile"       : docker_text,           # ← full file contents
        "test_command"     : pr["test_command"],
        "fail_to_pass"     : pr.get("fail2pass", ["compile-error"]),
        "pass_to_pass"     : pr.get("pass2pass", ["all-pass"]),
        "hints"            : None,
        "modified_test"    : modified_test,
        "modified_code"    : modified_code,
        "spec_dict": {
            "install": [],
            "test_cmd": pr["test_command"],
            "docker_specs": {
                "java_version": "21"
            },
            "log_parser_name": "maven"
        }
    })
    stats["prepared"] += 1

# ---------------------------------------------------------------- step 4 – write one indented JSON array
out_file.parent.mkdir(parents=True, exist_ok=True)
with out_file.open("w", encoding="utf-8") as f:
    json.dump(prepared, f, indent=2, ensure_ascii=False)

# ---------------------------------------------------------------- summary
print("----------- summary -----------")
print(f"Prepared objects       : {stats['prepared']}")
print(f"Useful but no payload  : {stats['missing_payload']}")
print(f"Useful but no config   : {stats['missing_cfg']}")
print(f"Dockerfile not found   : {stats['dockerfile_not_found']}")
print(f"Unuseful tasks skipped : {stats['unuseful']}")
print(f"(Missing repo/PR key   : {stats['missing_repo_or_pr']})")
print(f"→ Saved to {out_file}")
