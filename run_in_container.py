#!/usr/bin/env python3
import json, os, shutil, subprocess, sys, xml.etree.ElementTree as ET, logging
from pathlib import Path
from typing import Iterable, Set
from logging.handlers import RotatingFileHandler
import traceback
from collections import deque

# ── environment -----------------------------------------------------------
PR_SET = {int(x) for x in os.environ["PR_LIST"].split(",")}
PART_FILE = Path(os.environ["PART_FILE"])
LOG_FILE = PART_FILE.with_suffix(".log")  # worker log
ROOT = Path("/workspace")
INPUT_PATH = ROOT / "inputs.json"
REPOS_ROOT = Path("/tmp/repos")

# ── logging: console + file ----------------------------------------------
LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
log_format = "%(asctime)s %(levelname)s │ %(message)s"
max_bytes = 10 * 1024 * 1024  # 10 MB
backup_cnt = 2  # keep at most one old file <file>.1

handler = RotatingFileHandler(
    LOG_FILE,
    mode="a",
    maxBytes=max_bytes,
    backupCount=backup_cnt,
    encoding="utf-8"
)


# make every rotated file writable from the host
def _rotator(src, dst):
    os.rename(src, dst)
    os.chmod(dst, 0o666)  # world‑writable like the main file


handler.rotator = _rotator

logging.basicConfig(
    level=logging.DEBUG,  # DEBUG lines go to the log file
    format=log_format,
    datefmt="%H:%M:%S",
    handlers=[handler]
)
log = logging.getLogger(__name__)

# make both artefacts world‑writable so the host can tail / delete them
os.chmod(LOG_FILE, 0o666)


# ── helpers ---------------------------------------------------------------
def sh(cmd: Iterable[str] | str, cwd: Path | None = None) -> subprocess.CompletedProcess:
    if isinstance(cmd, str):
        cmd = ["bash", "-lc", cmd]

    proc = subprocess.Popen(
        cmd, cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True, bufsize=1
    )

    # this deque will only ever hold the last 100 lines
    tail = deque(maxlen=1000)

    for line in proc.stdout:
        tail.append(line)  # drop oldest if >100
        log.debug("%s", line.rstrip())

    proc.wait()
    ret = proc.returncode
    if ret:
        log.error("command failed with exit code %d: %s", ret, " ".join(cmd))

    # join only those last 100 lines
    last_100 = "".join(tail)
    return subprocess.CompletedProcess(cmd, ret, stdout=last_100)


def ensure_repo(slug: str) -> Path:
    local = REPOS_ROOT / slug.replace("/", "_")
    if not local.exists():
        local.parent.mkdir(parents=True, exist_ok=True)
        log.info(f"cloning {slug}")
        sh(["git", "clone", "--quiet", f"https://github.com/{slug}.git", str(local)]).check_returncode()
    sh(["git", "config", "--add", "remote.origin.fetch",
        "+refs/pull/*/head:refs/remotes/origin/pr/*"], cwd=local).check_returncode()
    sh(["git", "fetch", "--quiet", "--all", "--tags"], cwd=local).check_returncode()
    return local


def overlay(repo: Path, head: str, tests: list[str]):
    sh(["git", "checkout", "--quiet", "--detach"], cwd=repo)
    for chunk in (tests[i:i + 50] for i in range(0, len(tests), 50)):
        sh(["git", "restore", "--source", head, "--worktree", "--staged", "--", *chunk],
           cwd=repo).check_returncode()


def clean(repo: Path, patterns):
    for pat in patterns:
        for fp in repo.glob(pat):
            try:
                fp.unlink()
            except IsADirectoryError:
                shutil.rmtree(fp, ignore_errors=True)


def parse(repo: Path, patterns):
    all_t, fail = set(), set()
    for pat in patterns:
        for fp in repo.glob(pat):
            if fp.suffix.lower() != ".xml":
                continue
            try:
                tree = ET.parse(fp)
            except ET.ParseError:
                continue
            for tc in tree.iterfind(".//testcase"):
                ident = f"{tc.get('classname', '?')}#{tc.get('name', '?').split('[', 1)[0]}"
                all_t.add(ident)
                if tc.find("failure") is not None or tc.find("error") is not None:
                    fail.add(ident)
    return all_t, fail


def run(repo: Path, sha: str, cmd: str, patterns):
    sh(["git", "reset", "--hard", "--quiet"], cwd=repo)
    sh(["git", "checkout", "--quiet", sha], cwd=repo)
    clean(repo, patterns)
    proc = sh(cmd, cwd=repo)
    _, fail = parse(repo, patterns)
    return proc.returncode, proc.stdout, fail


def run_overlay(repo: Path, base: str, head: str, cmd: str, patterns, tests):
    sh(["git", "reset", "--hard", "--quiet"], cwd=repo)
    sh(["git", "checkout", "--quiet", base], cwd=repo)
    overlay(repo, head, tests)
    clean(repo, patterns)
    proc = sh(cmd, cwd=repo)
    all_t, fail = parse(repo, patterns)
    return proc.returncode, proc.stdout, all_t, fail


def load_inputs():
    raw = json.loads(INPUT_PATH.read_text())
    if isinstance(raw, dict):
        common = raw.get("info", {})
        for pr in raw["prs"]:
            for k in ("repo", "test_command", "test_files", "Dockerfile"):
                if k in common and k not in pr:
                    pr[k] = common[k]
        return raw["prs"]
    return raw


# ── main loop -------------------------------------------------------------
def create_cmd(cmd, tests):
    integration_tests = [t for t in tests if t.endswith(".java") and "IT" in t.split("/")[-1]]
    unit_tests = [t for t in tests if t.endswith("Test.java")]
    ignored_tests = [t for t in tests if t not in integration_tests + unit_tests]

    if integration_tests:
        integration_tests = [t.split("/")[-1].replace(".java", "") for t in integration_tests]
        integration_tests = ','.join(integration_tests)
    else:
        integration_tests = "NO_INTEGRATION_TESTS"

    if unit_tests:
        unit_tests = [t.split("/")[-1].replace(".java", "") for t in unit_tests]
        unit_tests = ','.join(unit_tests)
    else:
        unit_tests = "NO_UNIT_TESTS"

    cmd = cmd.replace("<unit_tests>", unit_tests).replace("<integration_tests>", integration_tests)

    return cmd, ignored_tests


def main():
    prs = [pr for pr in load_inputs() if pr["pr_number"] in PR_SET]
    PART_FILE.parent.mkdir(parents=True, exist_ok=True)
    with PART_FILE.open("w", encoding="utf-8") as sink:
        os.chmod(PART_FILE, 0o666)  # host can delete or overwrite later
        for pr in prs:
            try:
                repo = ensure_repo(pr["repo"])
                pat = pr.get("test_files", ["**/surefire-reports/*.xml"])
                tests = pr["modified_test"]
                cmd, ignored_tests = create_cmd(pr["test_command"], tests)

                o_code, o_log, o_all, o_fail = run_overlay(
                    repo, pr["base_commit"], pr["head_commit"],
                    cmd, pat, tests
                )

                errors = {}
                result = pr | {"test_command": cmd}

                if ignored_tests:
                    result["ignored_tests"] = ignored_tests

                if o_code:
                    result["errors"] = {"overlay_run": o_log[-4000:]}
                    log.error(f"PR #{pr['pr_number']} overlay failed")
                else:
                    h_code, h_log, h_fail = run(repo, pr["head_commit"], cmd, pat)

                    if h_code:
                        errors["head_tests"] = h_log[-4000:]

                    if errors:
                        result["errors"] = errors
                        log.error(f"PR #{pr['pr_number']} errors: {', '.join(errors)}")
                    else:
                        pre = h_fail
                        ignore2pass = o_fail & pre
                        fail2pass = o_fail - pre
                        pass2pass = o_all - o_fail
                        result = result | {
                            "fail2pass": sorted(fail2pass),
                            "ignore2pass": sorted(ignore2pass),
                            "pass2pass": sorted(pass2pass),
                        }
                        log.info(f"PR #{pr['pr_number']} f2p={len(fail2pass)} "
                                 f"ig2p={len(ignore2pass)} pass={len(pass2pass)}")

            except Exception as exc:
                log.error(f"PR #{pr['pr_number']} crashed: {exc}")
                result["errors"] = {
                    "runner": {
                        "type": type(exc).__name__,
                        "message": str(exc),
                        "traceback": traceback.format_exc().splitlines()
                    }
                }

            sink.write(json.dumps(result, ensure_ascii=False) + "\n")
            sink.flush()

            # ------------- new: tell the host that this PR is done ----------------
            status = "SUCCESS" if "errors" not in result else "FAILURE"
            # One plain line; the host watches for the literal prefix "RESULT"
            print(f"RESULT {pr['pr_number']} {status}", flush=True)
            # ----------------------------------------------------------------------


if __name__ == "__main__":
    main()
