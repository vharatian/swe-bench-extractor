import csv
import json
from pathlib import Path

outfile = Path("files/rework/rework.csv")
inFile = Path("files/rework/conversations.json")

with inFile.open("r", encoding="utf-8") as f:
    data = json.load(f)

rework = []
for d in data:
    rework += [
        {
            "task_id": d["id"],
            "trainer": d["currentUser"]["turingEmail"]
        }
    ]

fieldnames = rework[0].keys()

with outfile.open("w", newline="", encoding="utf-8") as csvfile:
    writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
    writer.writeheader()          # optional: comment out if you don’t want headers
    writer.writerows(rework)
