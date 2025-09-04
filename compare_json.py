#!/usr/bin/env python3
"""
compare_two_jsons_hardcoded.py
- Hard-coded input files
- Compares dicts/lists/strings/integers (also handles bool/null gracefully)
- Prints human-readable differences with JSONPath-like locations

Edit LEFT_FILE and RIGHT_FILE to point at your files.
Exit code: 0 if equal, 1 otherwise.
"""
from __future__ import annotations
import json
import sys
from pathlib import Path
from typing import Any, List, Tuple
import re

# ─── Hard-coded file paths ────────────────────────────────────────────────────
LEFT_FILE  = Path("files/delivery/batch_5/batch_5-patched.json")
RIGHT_FILE = Path("files/delivery/batch_5/batch_5-patched-old.json")

Diff = Tuple[str, str, Any, Any]  # (KIND, path, left_value, right_value)
_ident_re = re.compile(r"^[A-Za-z_]\w*$")


def load_json(p: Path) -> Any:
    try:
        with p.open("r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"[ERROR] File not found: {p}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"[ERROR] Failed to read/parse {p}: {e}", file=sys.stderr)
        sys.exit(1)


def join_path(base: str, key: Any) -> str:
    if isinstance(key, int):
        return f"{base}[{key}]"
    s = str(key)
    if _ident_re.match(s):
        return f"{base}.{s}"
    s = s.replace("\\", "\\\\").replace('"', r'\"')
    return f'{base}["{s}"]'


def short(value: Any, width: int = 120) -> str:
    s = json.dumps(value, ensure_ascii=False)
    return s if len(s) <= width else s[: width - 1] + "…"


def diff_values(left: Any, right: Any, path: str, diffs: List[Diff]) -> None:
    # Strict type check (e.g., int vs str is a mismatch)
    if type(left) is not type(right):
        diffs.append(("TYPE_MISMATCH", path, type(left).__name__, type(right).__name__))
        return

    # Dicts
    if isinstance(left, dict):
        lk, rk = set(left.keys()), set(right.keys())

        for k in sorted(lk - rk):
            diffs.append(("MISSING_IN_RIGHT", join_path(path, k), left[k], None))
        for k in sorted(rk - lk):
            diffs.append(("MISSING_IN_LEFT", join_path(path, k), None, right[k]))

        for k in sorted(lk & rk):
            diff_values(left[k], right[k], join_path(path, k), diffs)
        return

    # Lists (order-sensitive, compare by index)
    if isinstance(left, list):
        min_len = min(len(left), len(right))
        for i in range(min_len):
            diff_values(left[i], right[i], join_path(path, i), diffs)
        for i in range(min_len, len(left)):
            diffs.append(("MISSING_IN_RIGHT", join_path(path, i), left[i], None))
        for i in range(min_len, len(right)):
            diffs.append(("MISSING_IN_LEFT", join_path(path, i), None, right[i]))
        return

    # Primitives (str, int, bool, None)
    if left != right:
        diffs.append(("VALUE_DIFF", path, left, right))


def print_diffs(diffs: List[Diff], left_name: str, right_name: str) -> None:
    if not diffs:
        print("✅ No differences found.")
        return
    print(f"❌ {len(diffs)} differences found:\n")
    for kind, path, lval, rval in diffs:
        print(f"[{kind}] {path}")
        if kind == "MISSING_IN_RIGHT":
            print(f"  - {left_name}: {short(lval)}")
            print(f"  + {right_name}: (missing)")
        elif kind == "MISSING_IN_LEFT":
            print(f"  - {left_name}: (missing)")
            print(f"  + {right_name}: {short(rval)}")
        elif kind == "TYPE_MISMATCH":
            print(f"  - {left_name}: {lval}")
            print(f"  + {right_name}: {rval}")
        else:  # VALUE_DIFF
            print(f"  - {left_name}: {short(lval)}")
            print(f"  + {right_name}: {short(rval)}")
        print()


def main() -> int:
    left = load_json(LEFT_FILE)
    right = load_json(RIGHT_FILE)
    diffs: List[Diff] = []
    diff_values(left, right, "$", diffs)
    diffs.sort(key=lambda d: (d[1], d[0]))  # stable, readable order
    print_diffs(diffs, LEFT_FILE.name, RIGHT_FILE.name)
    return 0 if not diffs else 1


if __name__ == "__main__":
    sys.exit(main())
