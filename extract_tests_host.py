#!/usr/bin/env python3
import argparse, json, math, os, subprocess, threading, time
from datetime import datetime
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from tqdm import tqdm

ROOT       = Path(__file__).resolve().parent
FILES_DIR  = ROOT / "files"
M2_DIR     = FILES_DIR / "m2/repository"
RUN_DIR    = None
FINAL_PATH = None
GEN_DOCKER = None
PART_TPL   = "final.part{:02d}.jsonl"
TAG        = "swebench-eval:latest"

M2_DIR.mkdir(parents=True, exist_ok=True)
os.chmod(M2_DIR, 0o777)  # make it world-writable

# ───────────────────────── helpers ──────────────────────────
def create_run_dir(run_name: str):
    global RUN_DIR, FINAL_PATH, GEN_DOCKER
    stamp      = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
    RUN_DIR    = FILES_DIR / f"run-{run_name}-{stamp}"
    FINAL_PATH = RUN_DIR / "final.jsonl"
    GEN_DOCKER = RUN_DIR / "eval.Dockerfile"
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    os.chmod(RUN_DIR, 0o777)

def build_image(base_df: Path):
    GEN_DOCKER.write_text(
        base_df.read_text() +
        "\n# --- auto‑added ---\n"
        "RUN sudo apt-get update -y && sudo apt-get install -y --no-install-recommends python3-pip && pip3 install tqdm\n"
        "WORKDIR /runner\n"
        "COPY run_in_container.py /runner/run_in_container.py\n"
        "WORKDIR /workspace\n"
    )
    subprocess.run(["docker", "build", "-f", str(GEN_DOCKER), "-t", TAG, "."],
                   check=True, text=True)

def chunks(seq, n):
    sz = math.ceil(len(seq) / n)
    for i in range(0, len(seq), sz):
        yield seq[i:i + sz]

# ─────────────────────── worker launcher ───────────────────
def run_worker(idx: int,
               prs: list[int],
               run_name: str,
               overall_pbar: "tqdm",
               worker_pbar: "tqdm",
               counts: dict,
               lock: threading.Lock):

    part_path = RUN_DIR / PART_TPL.format(idx)


    user_flag = ["-u", "root"]
    # docker_env = ["-e", "DOCKER_HOST=unix:///var/run/docker.sock"]

    env  = ["-e", f"PR_LIST={','.join(map(str, prs))}",
            "-e", f"PART_FILE=/workspace/{part_path.name}"]
    vol  = ["-v", f"{RUN_DIR}:/workspace:rw"]
    m2_vol = ["-v", f"{M2_DIR}:/home/circleci/.m2/repository:rw"]
    sock_vol = ["-v", "/var/run/docker.sock:/var/run/docker.sock"]
    container_name = f"{run_name}-worker-{idx}"

    cmd = ["docker", "run", "--rm", "--privileged", "--name", container_name,
           *env, *vol, *m2_vol, *sock_vol, *user_flag, TAG,
           "python", "/runner/run_in_container.py"]

    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, bufsize=1, universal_newlines=True
    )

    for line in proc.stdout:
        line = line.strip()
        if line.startswith("RESULT"):
            _, pr_no, status = line.split(maxsplit=2)
            with lock:
                counts["done"] += 1
                if status == "SUCCESS": counts["success"] += 1
                else:                    counts["failure"] += 1

                worker_pbar.update(1)
                worker_pbar.set_postfix(last=status)

                overall_pbar.update(1)
                overall_pbar.set_postfix(
                    ok=counts["success"],
                    fail=counts["failure"]
                )

    proc.wait()
    worker_pbar.close()
    if proc.returncode:
        print(f"{container_name} exited with code {proc.returncode}")

# ─────────────────────────── main ──────────────────────────
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-w", "--workers", type=int, default=2)
    ap.add_argument("-i", "--input",  default="files/inputs.json")
    args = ap.parse_args()

    input_path = Path(args.input).resolve()
    spec       = json.loads(input_path.read_text())
    base_df    = Path(spec["info"]["Dockerfile"]).resolve()

    run_name   = input_path.stem.split("_", 1)[-1] if "_" in input_path.stem else input_path.stem
    create_run_dir(run_name)
    (RUN_DIR / "inputs.json").write_bytes(input_path.read_bytes())
    build_image(base_df)

    pr_numbers = [pr["pr_number"] for pr in spec["prs"]]
    total_prs  = len(pr_numbers)

    counts = {"done": 0, "success": 0, "failure": 0}
    lock   = threading.Lock()

    overall_pbar = tqdm(
        total=total_prs,
        position=0,
        desc="ALL PRs",
        bar_format="{l_bar}{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}] {postfix}"
    )
    overall_pbar.set_postfix(ok=0, fail=0)

    # build per‑worker progress‑bars (stacked below the overall one)
    worker_bars = []
    for pos, chunk_list in enumerate(chunks(pr_numbers, args.workers), start=1):
        worker_bars.append(
            tqdm(total=len(chunk_list),
                 position=pos,
                 desc=f"worker-{pos}",
                 bar_format="{l_bar}{bar}| {n_fmt}/{total_fmt} {postfix}")
        )

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = []
        for idx, (chunk_list, wbar) in enumerate(zip(chunks(pr_numbers, args.workers), worker_bars), start=1):
            futures.append(pool.submit(run_worker, idx, list(chunk_list),
                                       run_name, overall_pbar, wbar, counts, lock))
        for f in as_completed(futures):
            f.result()

    overall_pbar.close()

    # merge partial outputs
    with FINAL_PATH.open("w", encoding="utf-8") as out:
        for part in sorted(RUN_DIR.glob("final.part*.jsonl")):
            out.write(part.read_text())
            part.unlink()

    print(f"\n🎉  done → {FINAL_PATH}")
    print(f"✓ successes: {counts['success']}  ✗ failures: {counts['failure']}")

if __name__ == "__main__":
    main()
