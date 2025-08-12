import json
from pathlib import Path

from delivery.config import BATCH_NAME

folder = f"../files/delivery/{BATCH_NAME}"
in_file = Path("%s/raw_1.json" % folder)
out_file = Path("%s/wrapped.json" % folder)

with in_file.open("r", encoding="utf-8") as infile, \
    out_file.open("w", encoding="utf-8") as outfile:

    data = json.load(infile)

    json.dump(data, outfile, indent=4)

    