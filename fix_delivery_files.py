import json
from pathlib import Path

# DELIVERIES = [f"batch_{i}" for i in range(1, 6)]
DELIVERIES = [f"batch_5"]
DELIVERY_FOLDER = Path("files/delivery")
FIXED_FOLDER = Path("files/fixed_inputs")


def fix_tasks(tasks, fixed_inputs):
    report = {"fixed": 0, "not_fixed": 0}
    for t in tasks:
        if t["task_id"] in fixed_inputs:
            t["modified_code"] = fixed_inputs[t["task_id"]]["modified_source"]
            report["fixed"] += 1
        else:
            report["not_fixed"] += 1

    return tasks, report

for delivery in DELIVERIES:
    delivery_folder = DELIVERY_FOLDER / delivery
    in_file = delivery_folder / f"{delivery}.json"
    out_file = delivery_folder / f"{delivery}-fixed.json"

    if not in_file.exists():
        print(f"[ERROR] input file {in_file} not found")
        continue

    with in_file.open("r", encoding="utf-8") as f:
        tasks = json.load(f)


    fixed_inputs = {}
    for file in (FIXED_FOLDER).glob("*.json"):
        with file.open("r", encoding="utf-8") as f:
            data = json.load(f)
            fixed_inputs.update({f"{item["repo"]}#{item["pr_number"]}": item for item in data})

    tasks, fix_report = fix_tasks(tasks, fixed_inputs)

    print(f"✓ fixed {fix_report['fixed']} tasks; {fix_report['not_fixed']} not fixed")

    out_file.parent.mkdir(parents=True, exist_ok=True)
    with out_file.open("w", encoding="utf-8") as f:
        json.dump(tasks, f, indent=4)


    print(f"✓ wrote {len(tasks)} objects → {out_file}")