import json
from pathlib import Path

from numpy.ma.core import count

DELIVERIES = [f"batch_{i}" for i in [1, 3]]
DELIVERY_FOLDER = Path("files/delivery")
INPUT_FOLDER = Path("files/fixed_inputs")
OUTPUT_FOLDER = Path("files/selected_inputs")

selected_repos = {}
for delivery in DELIVERIES:
    delivery_final = DELIVERY_FOLDER / delivery / f"{delivery}-final.jsonl"
    with open(delivery_final, "r") as f:
        for line in f:
            if line.strip():
                obj = json.loads(line)
                repo = obj["repo"]
                if repo not in selected_repos:
                    selected_repos[repo] = []

                selected_repos[repo].append(obj)


count = 0
matched_prs = []
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
    matched_prs += [f"{d["repo"]}#{d["pr_number"]}" for d in selected_prs]

total_tasks = sum(len(v) for v in selected_repos.values())
print(f"✓ wrote a total of {count} objects out of {total_tasks} selected tasks")
print("selected repos:", ", ".join(selected_repos.keys()))

# print out the ids that didnt matched
unmatched_prs = []
for repo, items in selected_repos.items():
    for item in items:
        if item["task_id"] not in matched_prs:
            unmatched_prs.append(item["task_id"])


if unmatched_prs:
    print(f"✗ {len(unmatched_prs)} unmatched PRs:")
    print(", ".join(unmatched_prs))
