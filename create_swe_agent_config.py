#!/usr/bin/env python3
"""
Build every entry in tasks.jsonl, patching the repo’s own Dockerfile
with docker_snippet.append, and write the summary YAML expected by the
down-stream tooling.

All paths are hard-coded by design.
"""
import json
import os
import shutil
import subprocess
import tempfile
from itertools import islice
from pathlib import Path

import yaml   # pip install pyyaml

# ---------------------------------------------------------------------------
# hard-coded locations – adjust once here if you ever move things around
# ---------------------------------------------------------------------------
JSONL_PATH            = Path("files/delivery/batch_1/batch_1-final.jsonl")          # source list of tasks
DOCKER_SNIPPET_PATH   = Path("docker_files/Dockerfile-SWE-Agent")# reusable snippet
YAML_OUTPUT_PATH      = Path("files/swe-agent/batch_1.yaml")
DOCKER_BUILD_CTX      = Path("files/swe-agent/dockerfiles/")
LIMIT = 2
# --------------------------------------------------------------------------- #
def run(cmd, cwd=None):
    """subprocess.run with decent error reporting."""
    print(f"» {' '.join(cmd)}" + (f"  (cwd={cwd})" if cwd else ""))
    subprocess.run(cmd, cwd=cwd, check=True)


def build_image(patched_dockerfile_text: str, repo: str, commit: str, tag: str):
    """
    Build *tag* from *patched_dockerfile_text* in an ephemeral directory,
    passing the REPO and COMMIT build args.
    """
    with tempfile.TemporaryDirectory(dir=DOCKER_BUILD_CTX) as tmpdir:
        tmpdir_path = Path(tmpdir)
        dockerfile_path = tmpdir_path / "Dockerfile"
        dockerfile_path.write_text(patched_dockerfile_text, encoding="utf-8")

        run([
            "docker", "build",
            "--build-arg", f"REPO={repo}",
            "--build-arg", f"COMMIT={commit}",
            "-t", tag,
            "."  # context = tmpdir
        ], cwd=tmpdir)


def main() -> None:
    DOCKER_BUILD_CTX.mkdir(exist_ok=True)
    snippet = DOCKER_SNIPPET_PATH.read_text(encoding="utf-8")

    yaml_entries = []

    with JSONL_PATH.open("r", encoding="utf-8") as fh:
        for raw_line in islice(fh, LIMIT):
            task = json.loads(raw_line)
            instance_id   = task["instance_id"]
            repo          = task["repo"]
            base_commit   = task["base_commit"]
            problem_text  = task["problem_statement"]
            dockerfile_src = task["dockerfile"]  # already a string!

            patched_dockerfile = f"{dockerfile_src}\n\n{snippet}"
            image_tag = f"{instance_id}:latest".lower()

            print(f"\n### Building {image_tag} ###")
            build_image(
                patched_dockerfile_text=patched_dockerfile,
                repo=repo,
                commit=base_commit,
                tag=image_tag
            )

            yaml_entries.append({
                "image_name": image_tag,
                "instance_id": instance_id,
                "problem_statement": problem_text,
            })

    YAML_OUTPUT_PATH.write_text(
        yaml.dump(yaml_entries, sort_keys=False,
        default_flow_style=False, ),
        encoding="utf-8"
    )
    print(f"\n✓ All images built – manifest written to {YAML_OUTPUT_PATH}")


if __name__ == "__main__":
    main()