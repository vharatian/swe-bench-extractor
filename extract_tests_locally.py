#!/usr/bin/env python3
import json, shutil, subprocess, sys, xml.etree.ElementTree as ET, logging
from pathlib import Path
from typing import Iterable, Set
from tqdm import tqdm

from utils import is_test

INPUT_PATH = Path("files/inputs.json")
OUTPUT_PATH = Path("files/final.jsonl")
REPOS_ROOT = Path("files/repos")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s │ %(message)s",
    datefmt="%H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)


def sh(cmd: Iterable[str] | str, cwd: Path | None = None) -> subprocess.CompletedProcess:
    if isinstance(cmd, str):
        cmd = ["bash", "-lc", cmd]
    return subprocess.run(cmd, cwd=cwd, stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT, text=True, check=False)


def ensure_repo(slug: str) -> Path:
    local = REPOS_ROOT / slug.replace("/", "_")
    if not local.exists():
        local.parent.mkdir(parents=True, exist_ok=True)
        log.info(f"cloning {slug}")
        sh(["git", "clone", "--quiet", f"https://github.com/{slug}.git", str(local)]).check_returncode()

    sh(["git", "config", "--add", "remote.origin.fetch", "+refs/pull/*/head:refs/remotes/origin/pr/*"],
       cwd=local).check_returncode()
    sh(["git", "fetch", "--quiet", "--all", "--tags"], cwd=local).check_returncode()
    return local


def overlay_tests(repo: Path, head_sha: str, paths: list[str]) -> None:
    tests = [p for p in paths if is_test(p)]
    sh(["git", "checkout", "--quiet", "--detach"], cwd=repo).check_returncode()
    for chunk in (tests[i:i + 50] for i in range(0, len(tests), 50)):
        sh(["git", "restore", "--source", head_sha, "--worktree", "--staged", "--", *chunk],
           cwd=repo).check_returncode()

    exit(-1)


def clean_reports(repo: Path, patterns: list[str]) -> None:
    for pat in patterns:
        for fp in repo.glob(pat):
            try:
                fp.unlink()
            except IsADirectoryError:
                shutil.rmtree(fp, ignore_errors=True)


def parse_surefire(repo: Path, patterns: list[str]) -> tuple[Set[str], Set[str]]:
    all_tests, failing = set(), set()
    for pat in patterns:
        for fp in repo.glob(pat):
            if fp.suffix.lower() != ".xml": continue
            try:
                tree = ET.parse(fp)
            except ET.ParseError:
                continue
            for tc in tree.iterfind(".//testcase"):
                ident = f"{tc.get('classname', '?')}#{tc.get('name', '?').split('[', 1)[0]}"
                all_tests.add(ident)
                if tc.find("failure") is not None or tc.find("error") is not None:
                    failing.add(ident)
    return all_tests, failing


def run_commit(repo: Path, sha: str, cmd: str, patterns: list[str]) -> tuple[int, str, Set[str]]:
    sh(["git", "reset", "--hard", "--quiet"], cwd=repo).check_returncode()
    sh(["git", "checkout", "--quiet", sha], cwd=repo).check_returncode()
    clean_reports(repo, patterns)
    proc = sh(cmd, cwd=repo)
    _, failing = parse_surefire(repo, patterns)
    return proc.returncode, proc.stdout, failing


def run_overlay(repo: Path, base: str, head: str, cmd: str,
                patterns: list[str], diff_paths: list[str]) -> tuple[int, str, Set[str], Set[str]]:
    sh(["git", "reset", "--hard", "--quiet"], cwd=repo).check_returncode()
    sh(["git", "checkout", "--quiet", base], cwd=repo).check_returncode()
    overlay_tests(repo, head, diff_paths)
    clean_reports(repo, patterns)
    proc = sh(cmd, cwd=repo)
    all_tests, failing = parse_surefire(repo, patterns)
    return proc.returncode, proc.stdout, all_tests, failing


def load_prs() -> list[dict]:
    raw = json.loads(INPUT_PATH.read_text())
    if isinstance(raw, dict) and "prs" in raw:
        common = raw.get("info", {})
        for pr in raw["prs"]:
            for k in ("repo", "test_command", "test_files", "Dockerfile"):
                if k in common and k not in pr: pr[k] = common[k]
        return raw["prs"]
    if isinstance(raw, list): return raw
    sys.exit("bad inputs.json")


def main() -> None:
    if not INPUT_PATH.is_file(): sys.exit("inputs.json missing")
    prs = load_prs()
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT_PATH.open("w", encoding="utf-8") as sink:
        for pr in tqdm(prs, desc="PRs"):
            repo_dir = ensure_repo(pr["repo"])
            patterns = pr.get("test_files", ["**/surefire-reports/*.xml"])
            cmd = pr["test_command"]
            paths = [f["path"] for f in pr["files"]]

            log.info(f"PR #{pr['pr_number']} overlay run")
            o_code, o_log, o_all, o_fail = run_overlay(repo_dir, pr["base_commit"],
                                                       pr["head_commit"], cmd, patterns, paths)

            log.info(f"PR #{pr['pr_number']} base run")
            b_code, b_log, b_fail = run_commit(repo_dir, pr["base_commit"], cmd, patterns)

            log.info(f"PR #{pr['pr_number']} head run")
            h_code, h_log, h_fail = run_commit(repo_dir, pr["head_commit"], cmd, patterns)



            errors = {}
            if b_code: errors["base_tests"] = b_log[-4000:]
            if h_code: errors["head_tests"] = h_log[-4000:]
            if o_code: errors["overlay_run"] = o_log[-4000:]

            if errors:
                result = pr | {
                    "errors": errors
                }
                log.error(f"PR #{pr['pr_number']} errors: {', '.join(errors.keys())}")
            else:
                pre = b_fail | h_fail
                ignore2pass = o_fail & pre
                fail2pass = o_fail - pre
                pass2pass = o_all - o_fail

                result = pr | {
                    "fail2pass": sorted(fail2pass),
                    "ignore2pass": sorted(ignore2pass),
                    "pass2pass": sorted(pass2pass),
                }

                log.info(f"PR #{pr['pr_number']} f2p={len(fail2pass)} ig2p={len(ignore2pass)} pass={len(pass2pass)}")

            sink.write(json.dumps(result, ensure_ascii=False) + "\n")
            sink.flush()

    log.info(f"done ✓  output → {OUTPUT_PATH.resolve()}")


if __name__ == "__main__":
    main()
