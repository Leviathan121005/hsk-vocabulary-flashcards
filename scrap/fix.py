#!/usr/bin/env python3
"""Apply manual fixes across all HSK CSV files.

Single source of truth: scrap/fixes.json
Run: python3 scrap/fix.py
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path
from typing import Any, Dict, List


REPO_ROOT = Path(__file__).resolve().parents[1]
FIXES_FILE = REPO_ROOT / "scrap" / "fixes.json"

DATASET_TO_CSV = {
    "hsk1": REPO_ROOT / "public" / "hsk-1-vocabulary.csv",
    "hsk2": REPO_ROOT / "public" / "hsk-2-vocabulary.csv",
    "hsk3": REPO_ROOT / "public" / "hsk-3-vocabulary.csv",
    "hsk4": REPO_ROOT / "public" / "hsk-4-vocabulary.csv",
    "hsk5": REPO_ROOT / "public" / "hsk-5-vocabulary.csv",
}

CSV_FIELDNAMES = ["no", "word", "pinyin", "part_of_speech", "translation"]
ALLOWED_CHANGE_FIELDS = {"word", "pinyin", "part_of_speech", "translation", "note"}


def log(message: str) -> None:
    print(f"[hsk-fix] {message}")


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def normalize_dataset_id(dataset: str) -> str:
    compact = (dataset or "").strip().lower().replace("-", "")
    if compact in DATASET_TO_CSV:
        return compact
    raise ValueError(f"unsupported dataset '{dataset}'")


def normalize_change(change: Dict[str, Any], index: int) -> Dict[str, Any]:
    if not isinstance(change, dict):
        raise ValueError(f"changes[{index}] must be an object.")

    dataset_raw = change.get("dataset")
    if not isinstance(dataset_raw, str):
        raise ValueError(
            f"changes[{index}].dataset must be one of: {', '.join(sorted(DATASET_TO_CSV.keys()))}."
        )

    try:
        dataset = normalize_dataset_id(dataset_raw)
    except ValueError:
        raise ValueError(
            f"changes[{index}].dataset must be one of: hsk1, hsk2, hsk3, hsk4, hsk5 (or hyphen form)."
        ) from None

    if "no" not in change:
        raise ValueError(f"changes[{index}] is missing required field 'no'.")

    try:
        no = int(change["no"])
    except (TypeError, ValueError):
        raise ValueError(f"changes[{index}].no must be an integer.") from None

    normalized: Dict[str, Any] = {"dataset": dataset, "no": no}

    for key, value in change.items():
        if key in {"dataset", "no"}:
            continue

        if key not in ALLOWED_CHANGE_FIELDS:
            raise ValueError(
                f"changes[{index}] has unsupported field '{key}'. "
                "Allowed fields: dataset, no, word, pinyin, part_of_speech, translation, note."
            )

        if not isinstance(value, str):
            raise ValueError(f"changes[{index}].{key} must be a string.")

        normalized[key] = value.strip()

    has_update = any(field in normalized for field in ["word", "pinyin", "part_of_speech", "translation"])
    if not has_update:
        raise ValueError(
            f"changes[{index}] must include at least one update field: word, pinyin, part_of_speech, translation."
        )

    return normalized


def load_fixes() -> List[Dict[str, Any]]:
    if not FIXES_FILE.exists():
        raise FileNotFoundError(f"Missing fixes file: {FIXES_FILE}")

    parsed = load_json(FIXES_FILE)
    if not isinstance(parsed, dict):
        raise ValueError("fixes.json root must be an object.")

    raw_changes = parsed.get("changes", [])
    if not isinstance(raw_changes, list):
        raise ValueError("changes must be an array.")

    changes = [normalize_change(change, i + 1) for i, change in enumerate(raw_changes)]
    return changes


def read_csv_rows(path: Path) -> List[Dict[str, str]]:
    if not path.exists():
        log(f"WARNING: CSV not found, skipping: {path}")
        return []

    with path.open("r", encoding="utf-8", newline="") as file:
        reader = csv.DictReader(file)
        rows = [dict(row) for row in reader]

    return rows


def write_csv_rows(path: Path, rows: List[Dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=CSV_FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)


def apply_fixes_to_dataset(rows: List[Dict[str, str]], changes: List[Dict[str, Any]]) -> Tuple[int, List[int]]:
    if not rows or not changes:
        return 0, [change["no"] for change in changes]

    change_by_no = {change["no"]: change for change in changes}
    seen_no = set()
    updated_count = 0

    for row in rows:
        try:
            no = int((row.get("no") or "").strip())
        except ValueError:
            continue

        change = change_by_no.get(no)
        if not change:
            continue

        if "word" in change:
            row["word"] = change["word"]
        if "pinyin" in change:
            row["pinyin"] = change["pinyin"]
        if "part_of_speech" in change:
            row["part_of_speech"] = change["part_of_speech"]
        if "translation" in change:
            row["translation"] = change["translation"]

        seen_no.add(no)
        updated_count += 1

    missing = sorted(set(change_by_no.keys()) - seen_no)
    return updated_count, missing


def main() -> int:
    try:
        changes = load_fixes()
    except Exception as error:  # pylint: disable=broad-except
        log(f"ERROR: {error}")
        return 1

    changes_by_dataset: Dict[str, List[Dict[str, Any]]] = {dataset: [] for dataset in DATASET_TO_CSV}
    for change in changes:
        changes_by_dataset[change["dataset"]].append(change)

    total_updated = 0
    for dataset, csv_path in DATASET_TO_CSV.items():
        rows = read_csv_rows(csv_path)
        updated, missing = apply_fixes_to_dataset(rows, changes_by_dataset[dataset])

        if rows:
            write_csv_rows(csv_path, rows)

        total_updated += updated
        log(f"{dataset}: updated {updated} row(s)")
        if missing:
            log(f"WARNING: {dataset} missing no values: {missing[:20]}")

    log(f"Done. total updated rows={total_updated}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
