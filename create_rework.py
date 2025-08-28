from pathlib import Path
import json
import csv
import logging

# --- Paths (hardcoded as requested) ---
outfile = Path("files/rework/rework-description.csv")
inFileFolder = Path("files/delivery")

# --- Setup ---
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
outfile.parent.mkdir(parents=True, exist_ok=True)

rows = []
batch_dirs = [p for p in inFileFolder.iterdir() if p.is_dir() and p.name.startswith("batch")]
batch_dirs.sort(key=lambda p: p.name)

wrapped_count = 0
id_count = 0

for batch_dir in batch_dirs:
    # Find wrapped.json anywhere under the batch folder (works even if nested)
    wrapped_files = list(batch_dir.rglob("wrapped.json"))
    if not wrapped_files:
        logging.warning(f"No wrapped.json found in {batch_dir}")
        continue

    for wrapped in wrapped_files:
        wrapped_count += 1
        try:
            with wrapped.open("r", encoding="utf-8") as fh:
                data = json.load(fh)
        except Exception as e:
            logging.error(f"Failed to read {wrapped}: {e}")
            continue

        form = data.get("form", [])
        if not isinstance(form, list):
            logging.warning(f"'sft' is missing or not a list in {wrapped}")
            continue

        for obj in form:
            if isinstance(obj, dict) and "taskId" in obj:
                metadata = obj["metadata"]["scope_requirements"]
                rows.append({
                    "task_id": obj["taskId"],
                    "task_link": f"https://labeling-z.turing.com/conversations/{obj["taskId"]}/view",
                    "repo": metadata["Repository"],
                    "pr_link": metadata["PR Link"],
                })
                id_count += 1
            else:
                logging.warning(f"Item without 'id' in {wrapped}: {obj!r}")

# Write CSV
with outfile.open("w", newline="", encoding="utf-8") as csvfile:
    writer = csv.DictWriter(csvfile, fieldnames=["task_id", "task_link", "repo", "pr_link"])
    writer.writeheader()
    writer.writerows(rows)

logging.info(f"Scanned {len(batch_dirs)} batch folders")
logging.info(f"Found {wrapped_count} wrapped.json files")
logging.info(f"Wrote {id_count} ids to {outfile}")
