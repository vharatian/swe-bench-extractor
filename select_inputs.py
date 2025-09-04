import json
from pathlib import Path

from numpy.ma.core import count

DELIVERY = Path("files/delivery/batch_5/batch_5-final.jsonl")
INPUT_FOLDER = Path("files/fixed_inputs")
OUTPUT_FOLDER = Path("files/selected_inputs")

selected_repos = {}
with open(DELIVERY, "r") as f:
    for line in f:
        if line.strip():
            obj = json.loads(line)
            repo = obj["repo"]
            if repo not in selected_repos:
                selected_repos[repo] = []

            selected_repos[repo].append(obj)


count = 0
for file in INPUT_FOLDER.glob("*.json"):
    with file.open("r", encoding="utf-8") as f:
        data = json.load(f)

    repo = data[0]["repo"]
    if repo not in selected_repos:
        continue

    selected_pr_numbers = {item["task_id"].split("#")[-1] for item in selected_repos[repo]}
    selected_prs = [d for d in data if f"{d["pr_number"]}" in selected_pr_numbers]

    with (OUTPUT_FOLDER / file.name).open("w", encoding="utf-8") as f:
        json.dump(selected_prs, f, indent=4)

    print(f"✓ wrote {len(selected_prs)} objects → {OUTPUT_FOLDER / file.name}")

    count += len(selected_prs)

print(f"✓ wrote a total of {count} objects")
