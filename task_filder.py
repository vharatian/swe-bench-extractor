import json
from pathlib import Path

INPUT_PATH = Path("files/cdap_inputs.json")
RUN_PATH = Path("files/run-cdap")
OUTPUT_PATH = Path("files/cdap_inputs_filtered.json")



# I want a code that reads all the jsonl files in the RUN_PATH directory, and filter the input data based on those that throw an error. and the error contains this meesage "Could not resolve dependencies for project io.cdap.cdap:cdap-standalone:jar:6.11.0-SNAPSHOT" the input data has a pr files that has a pr numebr that the prs should be filterd based on that

def main():
    if not RUN_PATH.exists():
        raise FileNotFoundError(f"Cannot find {RUN_PATH}")

    filtered_prs = []

    with OUTPUT_PATH.open("w", encoding="utf-8") as outfile:
        for file in RUN_PATH.glob("*.jsonl"):
            with file.open("r", encoding="utf-8") as infile:
                for line in infile:
                    if not line.strip():
                        continue
                    rec = json.loads(line)
                    errors = rec.get("errors", {})
                    if not any("Could not resolve dependencies for project io.cdap.cdap:cdap-standalone:jar:6.11.0-SNAPSHOT" in str(err) for err in errors.values()):
                        filtered_prs.append(rec["pr_number"])


    with INPUT_PATH.open("r", encoding="utf-8") as infile, OUTPUT_PATH.open("w", encoding="utf-8") as outfile:
        input_data = json.load(infile)
        all_prs = [pr for pr in input_data["prs"] if pr["pr_number"] not in filtered_prs]
        all_prs = [pr for pr in all_prs if not any(f for f in pr["files"] if "cdap-standalone" in f["path"])]
        input_data["prs"] = all_prs
        json.dump(input_data, outfile, indent=4)


    print(f"Filtered PRs saved to {OUTPUT_PATH}")

if __name__ == "__main__":
    main()