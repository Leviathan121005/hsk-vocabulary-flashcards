#!/usr/bin/env python3
"""Extract HSK-style vocabulary PDF into CSV.

The workflow is intentionally simple:
1) Choose an input PDF.
2) Choose an output CSV path.
3) Run the script.

Examples:
    python3 scrap/scan.py
    python3 scrap/scan.py --input scrap/hsk-5-vocabulary.pdf --output public/hsk-5-vocabulary.csv --level 5
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple


POS_TOKENS = {
    "noun",
    "verb",
    "adjective",
    "adverb",
    "pronoun",
    "preposition",
    "conjunction",
    "interjection",
    "classifier",
    "number-classifier",
    "measure-word",
    "auxiliary",
    "particle",
    "idiom",
    "phrase",
    "numeral",
    "onomatopoeia",
    "status-word",
    "localizer",
}

POS_SEPARATORS = {"、", "/", "|", "&", "and"}

ENTRY_START = re.compile(r"^\d+\s")
ENTRY_PARSE = re.compile(r"^(?P<no>\d+)\s+(?P<word>\S+)\s+(?P<pinyin>\S+)\s+(?P<rest>.+)$")


def build_header_patterns(level: int) -> Sequence[re.Pattern[str]]:
    return (
        re.compile(r"^NEW HSK VOCABULARY$", re.IGNORECASE),
        re.compile(rf"^Level\s+{level}$", re.IGNORECASE),
        re.compile(r"^ENTRIES$", re.IGNORECASE),
        re.compile(r"^\d+$"),
        re.compile(r"^NO\.\s+WORD\s+PINYIN\s+PART OF SPEECH\s+TRANSLATION$", re.IGNORECASE),
        re.compile(rf"^MandarinBean\.com\s+Page\s+\d+\s+Level\s+{level}$", re.IGNORECASE),
    )


def log(message: str) -> None:
    print(f"[hsk-csv] {message}")


def clean_line(line: str) -> str:
    line = line.strip()
    line = re.sub(r"\s+", " ", line)
    return line


def is_header_or_footer(line: str, header_patterns: Sequence[re.Pattern[str]]) -> bool:
    return any(pattern.match(line) for pattern in header_patterns)


def normalize_pos_rest(rest: str) -> str:
    text = re.sub(r"\s+", " ", rest).strip()
    text = text.replace("number- classifier", "number-classifier")
    text = text.replace("measure- word", "measure-word")
    return text


def parse_pos_and_translation(rest: str) -> Tuple[str, str]:
    rest = normalize_pos_rest(rest)
    tokens = rest.split(" ")

    pos_tokens: List[str] = []
    idx = 0
    while idx < len(tokens):
        token = tokens[idx]
        normalized = token.strip(",;:.()").lower()
        if normalized in POS_TOKENS or normalized in POS_SEPARATORS:
            pos_tokens.append(token)
            idx += 1
            continue
        break

    if not pos_tokens:
        # Some rows omit a POS token and provide translation directly after pinyin.
        # In that case keep POS empty and treat the whole remainder as translation.
        return "", rest

    part_of_speech = " ".join(pos_tokens).strip()
    translation = " ".join(tokens[idx:]).strip()
    return part_of_speech, translation


def extract_candidate_rows(
    pdf_path: Path,
    header_patterns: Sequence[re.Pattern[str]],
    skip_first_page: bool = True,
) -> List[str]:
    try:
        from pypdf import PdfReader
    except ModuleNotFoundError:
        log("Missing dependency: pypdf")
        log("Install it with: pip3 install --user pypdf")
        raise

    reader = PdfReader(str(pdf_path))
    total_pages = len(reader.pages)
    start_idx = 1 if skip_first_page else 0

    log(f"Loaded PDF: {pdf_path}")
    log(f"Total pages: {total_pages} (starting from page {start_idx + 1})")

    rows: List[str] = []
    current: str = ""

    for i in range(start_idx, total_pages):
        page_number = i + 1
        page_text = reader.pages[i].extract_text() or ""
        lines = [clean_line(line) for line in page_text.splitlines()]

        kept_lines = 0
        for line in lines:
            if not line or is_header_or_footer(line, header_patterns):
                continue

            kept_lines += 1
            if ENTRY_START.match(line):
                if current:
                    rows.append(current)
                current = line
            else:
                if current:
                    current = f"{current} {line}".strip()

        log(f"Page {page_number:>2}: extracted {kept_lines:>3} content lines")

    if current:
        rows.append(current)

    log(f"Stitched candidate rows: {len(rows)}")
    return rows


def parse_rows(rows: Sequence[str]) -> Tuple[List[Dict[str, str]], List[str]]:
    records: List[Dict[str, str]] = []
    failed: List[str] = []

    for row in rows:
        match = ENTRY_PARSE.match(row)
        if not match:
            failed.append(row)
            continue

        rest = match.group("rest").strip()
        pos, translation = parse_pos_and_translation(rest)

        records.append(
            {
                "no": match.group("no"),
                "word": match.group("word"),
                "pinyin": match.group("pinyin"),
                "part_of_speech": pos,
                "translation": translation,
            }
        )

    return records, failed


def validate_records(records: Sequence[Dict[str, str]], expected_count: Optional[int]) -> bool:
    ok = True
    actual_count = len(records)

    if expected_count is not None:
        if actual_count != expected_count:
            log(f"WARNING: expected {expected_count} entries, found {actual_count}")
            ok = False
        else:
            log(f"Entry count check passed: {actual_count}/{expected_count}")
    else:
        log(f"Parsed entries: {actual_count}")

    numbers = []
    for rec in records:
        try:
            numbers.append(int(rec["no"]))
        except ValueError:
            log(f"WARNING: non-numeric entry number: {rec['no']}")
            ok = False

    if numbers:
        expected_numbers = list(range(1, max(numbers) + 1))
        if numbers != expected_numbers:
            missing = sorted(set(expected_numbers) - set(numbers))
            duplicates = sorted({n for n in numbers if numbers.count(n) > 1})
            if missing:
                log(f"WARNING: missing entry numbers (first 20): {missing[:20]}")
            if duplicates:
                log(f"WARNING: duplicate entry numbers: {duplicates}")
            ok = False
        else:
            log("Number sequence check passed")

    return ok


def write_csv(records: Sequence[Dict[str, str]], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ["no", "word", "pinyin", "part_of_speech", "translation"]
    with output_path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(records)


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]

    parser = argparse.ArgumentParser(description="Extract HSK vocabulary PDF to CSV.")
    parser.add_argument("--level", type=int, default=5, help="HSK level number used for header detection.")
    parser.add_argument(
        "--input",
        default=str(repo_root / "scrap" / "hsk-5-vocabulary.pdf"),
        help="Input PDF path.",
    )
    parser.add_argument(
        "--output",
        default=str(repo_root / "public" / "hsk-5-vocabulary.csv"),
        help="Output CSV path.",
    )
    parser.add_argument(
        "--expected-count",
        type=int,
        default=1600,
        help="Expected number of entries for strict validation. Set to 0 to disable.",
    )

    args = parser.parse_args()

    pdf_path = Path(args.input)
    output_path = Path(args.output)
    expected_count = None if args.expected_count <= 0 else args.expected_count

    if not pdf_path.exists():
        log(f"ERROR: input PDF not found: {pdf_path}")
        return 1

    header_patterns = build_header_patterns(args.level)

    try:
        candidate_rows = extract_candidate_rows(pdf_path, header_patterns, skip_first_page=True)
    except ModuleNotFoundError:
        return 1

    records, failed_rows = parse_rows(candidate_rows)
    log(f"Parsed rows: {len(records)}")

    if failed_rows:
        log(f"WARNING: {len(failed_rows)} rows failed to parse")
        preview_count = min(5, len(failed_rows))
        for i in range(preview_count):
            log(f"  failed[{i + 1}]: {failed_rows[i][:180]}")

    is_valid = validate_records(records, expected_count=expected_count)

    write_csv(records, output_path)
    log(f"Wrote CSV: {output_path} ({len(records)} records)")

    if is_valid and not failed_rows:
        log("Done: extraction completed successfully")
        return 0

    log("Done with warnings: inspect output and warnings above")
    return 0


if __name__ == "__main__":
    sys.exit(main())
