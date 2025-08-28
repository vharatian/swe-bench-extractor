from pathlib import Path

input_folder = Path("files/run-camel-new")
output_file = Path("files/finals/final-camel.jsonl")

def merge_jsonl_files(input_folder: Path, output_file: Path) -> None:
    with output_file.open("w", encoding="utf-8") as outfile:
        for jsonl_file in input_folder.glob("*.jsonl"):
            with jsonl_file.open("r", encoding="utf-8") as infile:
                for line in infile:
                    if line.strip():  # Skip empty lines
                        outfile.write(line)



if __name__ == "__main__":
    merge_jsonl_files(input_folder, output_file)
    print(f"Merged JSONL files into {output_file.resolve()}")