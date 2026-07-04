#!/usr/bin/env python3
"""Extract HSK-style vocabulary PDF into CSV via x/y column bands.

This parser uses page coordinates as the baseline:
1) Detect table header row to infer x boundaries for each column.
2) Group words by y into visual rows.
3) Assign each word to no/word/pinyin/part_of_speech/translation by x position.
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple


PINYIN_CHAR_RE = re.compile(r"^[a-zāáǎàēéěèīíǐìōóǒòūúǔùǖǘǚǜüvńňḿê'\-/]+$", re.IGNORECASE)
PINYIN_TONE_RE = re.compile(r"[āáǎàēéěèīíǐìōóǒòūúǔùǖǘǚǜüÜńňḿêÊ]")
ENTRY_NO_RE = re.compile(r"^\d+$")
FOOTER_ANCHOR_RE = re.compile(r"^(MandarinBean\.com|Page|Level)$", re.IGNORECASE)


def log(message: str) -> None:
    print(f"[hsk-csv] {message}")


def normalize_commas(text: str) -> str:
    normalized = (text or "").replace("，", ",").replace("、", ",")
    normalized = normalized.replace("（", "(").replace("）", ")")
    normalized = re.sub(r"\(\s+", "(", normalized)
    normalized = re.sub(r"\s+\)", ")", normalized)
    normalized = re.sub(r"\s*,\s*", ", ", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized


def clean_token(text: str) -> str:
    return (text or "").strip().strip('"').strip(",;:.()[]{}（）")


def normalize_word_value(raw: str) -> str:
    compact = normalize_commas(raw).replace(" ", "")
    # OCR occasionally appends sense markers like "1/2" or stray ASCII (e.g. "劳verb") to Hanzi.
    compact = re.sub(r"[0-9]+$", "", compact)
    compact = re.sub(r"[A-Za-z]+$", "", compact)

    hanzi_only = "".join(ch for ch in compact if _is_hanzi_char(ch))
    return hanzi_only or compact


def _is_hanzi_char(ch: str) -> bool:
    code = ord(ch)
    return (
        0x3400 <= code <= 0x4DBF  # CJK Unified Ideographs Extension A
        or 0x4E00 <= code <= 0x9FFF  # CJK Unified Ideographs
        or 0xF900 <= code <= 0xFAFF  # CJK Compatibility Ideographs
        or 0x2E80 <= code <= 0x2EFF  # CJK Radicals Supplement
        or 0x2F00 <= code <= 0x2FDF  # Kangxi Radicals
        or 0x20000 <= code <= 0x2A6DF  # CJK Extension B
        or 0x2A700 <= code <= 0x2B73F  # CJK Extension C
        or 0x2B740 <= code <= 0x2B81F  # CJK Extension D
        or 0x2B820 <= code <= 0x2CEAF  # CJK Extension E/F
        or 0x2CEB0 <= code <= 0x2EBEF  # CJK Extension G/I blocks
        or 0x30000 <= code <= 0x323AF  # CJK Extension G/H
    )


def normalize_pinyin_value(raw: str) -> str:
    compact = (raw or "").replace("，", " ").replace("、", " ").replace(",", " ")
    tokens = [clean_token(token) for token in compact.split()]
    tokens = [token for token in tokens if token]
    return "".join(tokens)


def token_is_pinyin_like(token: str) -> bool:
    cleaned = clean_token(token)
    if not cleaned:
        return False
    if PINYIN_CHAR_RE.match(cleaned) is None:
        return False
    return PINYIN_TONE_RE.search(cleaned) is not None


def split_glued_pinyin_token(token: str) -> Tuple[str, str]:
    cleaned = clean_token(token)
    if not cleaned:
        return "", ""

    if token_is_pinyin_like(cleaned):
        return cleaned, ""

    for idx in range(1, len(cleaned)):
        left = cleaned[:idx]
        right = cleaned[idx:]
        if token_is_pinyin_like(left) and re.match(r"^[A-Za-z][A-Za-z\-]*$", right):
            return left, right

    return "", cleaned


def parse_rest_without_pos_dict(raw_rest: str) -> Tuple[str, str, str]:
    """Fallback split for malformed rows when column extraction misses bands.

    Returns (pinyin, part_of_speech, translation).
    """

    rest = normalize_commas(raw_rest)
    tokens = [token for token in rest.split(" ") if token]
    if not tokens:
        return "", "", ""

    pinyin_tokens: List[str] = []
    tail_tokens: List[str] = []

    i = 0
    while i < len(tokens):
        token = tokens[i]
        if tail_tokens:
            tail_tokens.append(token)
            i += 1
            continue

        direct = clean_token(token)
        if token_is_pinyin_like(direct):
            pinyin_tokens.append(token)
            i += 1
            continue

        pinyin_part, tail_part = split_glued_pinyin_token(token)
        if pinyin_part:
            pinyin_tokens.append(pinyin_part)
            if tail_part:
                tail_tokens.append(tail_part)
            i += 1
            continue

        tail_tokens.append(token)
        i += 1

    if not pinyin_tokens:
        pinyin = normalize_pinyin_value(tokens[0])
        tail = " ".join(tokens[1:]).strip()
    else:
        pinyin = normalize_pinyin_value(" ".join(pinyin_tokens))
        tail = " ".join(tail_tokens).strip()

    # Simple boundary: first ';' or leading translation starter.
    if not tail:
        return pinyin, "", ""

    tail_tokens = [token for token in tail.split(" ") if token]
    split_idx = None
    for idx, token in enumerate(tail_tokens):
        token_l = clean_token(token).lower()
        if ";" in token or token.startswith(("(", "（")):
            split_idx = idx
            break
        if token_l in {"to", "a", "an", "the", "and", "or", "with", "without", "used", "indicating", "measure", "word"}:
            split_idx = idx
            break

    if split_idx is None:
        if len(tail_tokens) == 1:
            return pinyin, normalize_commas(tail_tokens[0]), ""
        split_idx = 1

    pos = normalize_commas(" ".join(tail_tokens[:split_idx]))
    meaning = normalize_commas(" ".join(tail_tokens[split_idx:]))
    return pinyin, pos, meaning


def extract_words_with_coords(pdf_path: Path, skip_first_page: bool = True) -> Tuple[List[Dict[str, float | str]], List[Tuple[int, int]]]:
    try:
        import pdfplumber
    except ModuleNotFoundError:
        log("Missing dependency: pdfplumber")
        log("Install it with: python3 -m pip install pdfplumber")
        raise

    words: List[Dict[str, float | str]] = []
    page_ranges: List[Tuple[int, int]] = []

    with pdfplumber.open(str(pdf_path)) as pdf:
        start_idx = 1 if skip_first_page else 0
        log(f"Loaded PDF: {pdf_path}")
        log(f"Total pages: {len(pdf.pages)} (starting from page {start_idx + 1})")

        for page_index in range(start_idx, len(pdf.pages)):
            page = pdf.pages[page_index]
            page_words = page.extract_words(
                x_tolerance=1,
                y_tolerance=2,
                keep_blank_chars=False,
                use_text_flow=True,
            )
            start = len(words)
            for item in page_words:
                text = (item.get("text") or "").strip()
                if not text:
                    continue
                words.append(
                    {
                        "page": float(page_index + 1),
                        "x0": float(item["x0"]),
                        "x1": float(item["x1"]),
                        "top": float(item["top"]),
                        "text": text,
                    }
                )
            end = len(words)
            page_ranges.append((start, end))
            log(f"Page {page_index + 1:>2}: extracted {end - start:>3} word fragments")

    return words, page_ranges


def find_header_info(
    page_words: Sequence[Dict[str, float | str]],
) -> Optional[Tuple[Tuple[float, float, float, float, float], float]]:
    """Find x boundaries and top y of a true table header row."""

    # Candidate headers by normalized text token.
    candidates = []
    for w in page_words:
        t = str(w["text"]).upper()
        if t in {"NO.", "NO", "WORD", "PINYIN", "PART", "TRANSLATION"}:
            candidates.append(w)

    # group by y (~same top)
    rows: Dict[int, List[Dict[str, float | str]]] = {}
    for w in candidates:
        y_key = int(round(float(w["top"]) / 2.0))
        rows.setdefault(y_key, []).append(w)

    best = None
    best_top = None
    for group in rows.values():
        texts = {str(w["text"]).upper() for w in group}
        if (
            "WORD" in texts
            and "PINYIN" in texts
            and "TRANSLATION" in texts
            and ("NO." in texts or "NO" in texts)
            and "PART" in texts
        ):
            best = group
            best_top = min(float(w["top"]) for w in group)
            break

    if not best or best_top is None:
        return None

    by_text = {str(w["text"]).upper(): w for w in best}

    no_x = float(by_text.get("NO.", by_text.get("NO"))["x0"]) if ("NO." in by_text or "NO" in by_text) else 40.0
    word_x = float(by_text["WORD"]["x0"])
    pinyin_x = float(by_text["PINYIN"]["x0"])
    part_x = float(by_text["PART"]["x0"])
    translation_x = float(by_text["TRANSLATION"]["x0"])

    return (no_x, word_x, pinyin_x, part_x, translation_x), best_top


def find_header_bounds(page_words: Sequence[Dict[str, float | str]]) -> Optional[Tuple[float, float, float, float, float]]:
    header_info = find_header_info(page_words)
    if header_info is None:
        return None
    bounds, _top = header_info
    return bounds


def assign_column(x0: float, boundaries: Tuple[float, float, float, float, float]) -> str:
    _no_x, word_x, pinyin_x, part_x, translation_x = boundaries

    if x0 < word_x:
        return "no"
    if x0 < pinyin_x:
        return "word"
    if x0 < part_x:
        return "pinyin"
    if x0 < translation_x:
        return "part_of_speech"
    return "translation"


def recover_missing_rows_by_number_anchor(
    words: Sequence[Dict[str, float | str]],
    bounds: Tuple[float, float, float, float, float],
    existing_numbers: Sequence[int],
) -> List[Dict[str, str]]:
    if not existing_numbers:
        return []

    missing_numbers = [n for n in range(1, max(existing_numbers) + 1) if n not in set(existing_numbers)]
    if not missing_numbers:
        return []

    recovered: List[Dict[str, str]] = []

    for missing in missing_numbers:
        target = str(missing)
        anchors = [
            w
            for w in words
            if str(w["text"]) == target and assign_column(float(w["x0"]), bounds) == "no"
        ]
        if not anchors:
            continue

        anchor = anchors[0]
        page = float(anchor["page"])
        top = float(anchor["top"])

        near_words = [
            w
            for w in words
            if float(w["page"]) == page and (top - 1.0) <= float(w["top"]) <= (top + 4.5)
        ]

        cols: Dict[str, List[str]] = {"no": [], "word": [], "pinyin": [], "part_of_speech": [], "translation": []}
        for w in sorted(near_words, key=lambda item: (float(item["top"]), float(item["x0"]))):
            cols[assign_column(float(w["x0"]), bounds)].append(str(w["text"]))

        if not cols["word"]:
            # Some Hanzi glyphs drift to the next y-line; include a small continuation band.
            continuation_words = [
                w
                for w in words
                if float(w["page"]) == page and (top + 4.5) < float(w["top"]) <= (top + 8.5)
            ]
            for w in sorted(continuation_words, key=lambda item: (float(item["top"]), float(item["x0"]))):
                col = assign_column(float(w["x0"]), bounds)
                if col == "word":
                    cols[col].append(str(w["text"]))

        rec = {
            "no": target,
            "word": normalize_word_value(" ".join(cols["word"])),
            "pinyin": normalize_pinyin_value(" ".join(cols["pinyin"])),
            "part_of_speech": normalize_commas(" ".join(cols["part_of_speech"])),
            "translation": normalize_commas(" ".join(cols["translation"])),
        }

        if rec["word"] or rec["pinyin"] or rec["translation"]:
            recovered.append(rec)

    return recovered


def build_records_from_coords(
    words: Sequence[Dict[str, float | str]],
    page_ranges: Sequence[Tuple[int, int]],
) -> Tuple[List[Dict[str, str]], List[str]]:
    records: List[Dict[str, str]] = []
    failed: List[str] = []

    # Infer stable x-bands once from any page with a visible header row.
    global_bounds: Optional[Tuple[float, float, float, float, float]] = None
    for start, end in page_ranges:
        page_words = list(words[start:end])
        global_bounds = find_header_bounds(page_words)
        if global_bounds is not None:
            break

    if global_bounds is None:
        return [], ["header-not-found-any-page"]

    for page_idx, (start, end) in enumerate(page_ranges, start=1):
        page_words = list(words[start:end])
        if not page_words:
            continue

        bounds = global_bounds
        page_header_info = find_header_info(page_words)
        if page_header_info is not None:
            _page_bounds, header_top = page_header_info
            body_words = [w for w in page_words if float(w["top"]) > header_top + 10]
        else:
            # Many pages omit repeated table headers; use all words and let row-start detection prune noise.
            body_words = list(page_words)

        # Remove footer row by anchoring on known footer labels and dropping the full y-band.
        footer_tops = {
            float(w["top"]) for w in body_words if FOOTER_ANCHOR_RE.match(str(w["text"]).strip())
        }
        if footer_tops:
            body_words = [
                w
                for w in body_words
                if not any(abs(float(w["top"]) - top) <= 2.0 for top in footer_tops)
            ]

        # Group by row y (quantize to 3px buckets)
        y_rows: Dict[int, List[Dict[str, float | str]]] = {}
        for w in body_words:
            y_key = int(round(float(w["top"]) / 3.0))
            y_rows.setdefault(y_key, []).append(w)

        sorted_y = sorted(y_rows.keys())

        current: Optional[Dict[str, List[str]]] = None

        for y_key in sorted_y:
            row_words = sorted(y_rows[y_key], key=lambda w: float(w["x0"]))

            # Create temporary column chunks for this y line.
            cols: Dict[str, List[str]] = {"no": [], "word": [], "pinyin": [], "part_of_speech": [], "translation": []}
            for w in row_words:
                col = assign_column(float(w["x0"]), bounds)
                cols[col].append(str(w["text"]))

            no_text = " ".join(cols["no"]).strip()
            no_candidate = re.sub(r"\D", "", no_text)

            starts_new_record = bool(no_candidate and ENTRY_NO_RE.match(no_candidate))

            if starts_new_record:
                if current is not None:
                    records.append(
                        {
                            "no": " ".join(current["no"]).strip(),
                            "word": normalize_word_value(" ".join(current["word"])),
                            "pinyin": normalize_pinyin_value(" ".join(current["pinyin"])),
                            "part_of_speech": normalize_commas(" ".join(current["part_of_speech"])),
                            "translation": normalize_commas(" ".join(current["translation"])),
                        }
                    )

                current = {k: [] for k in cols}
                current["no"].append(no_candidate)
                for key in ("word", "pinyin", "part_of_speech", "translation"):
                    current[key].extend(cols[key])
            elif current is not None:
                # Continuation line for previous record (commonly POS/translation wraps).
                for key in ("word", "pinyin", "part_of_speech", "translation"):
                    current[key].extend(cols[key])

        if current is not None:
            records.append(
                {
                    "no": " ".join(current["no"]).strip(),
                    "word": normalize_word_value(" ".join(current["word"])),
                    "pinyin": normalize_pinyin_value(" ".join(current["pinyin"])),
                    "part_of_speech": normalize_commas(" ".join(current["part_of_speech"])),
                    "translation": normalize_commas(" ".join(current["translation"])),
                }
            )

    # Final cleanup fallback for malformed rows.
    cleaned: List[Dict[str, str]] = []
    for rec in records:
        no = re.sub(r"\D", "", rec.get("no", ""))
        if not no:
            continue

        word = rec.get("word", "").strip()
        pinyin = rec.get("pinyin", "").strip()
        pos = rec.get("part_of_speech", "").strip()
        meaning = rec.get("translation", "").strip()

        if pinyin and (not pos and not meaning):
            # Nothing after pinyin likely means content spilled out; keep as-is.
            pass

        if not pinyin and (pos or meaning):
            # Try fallback parse from merged tail.
            merged_tail = " ".join([pos, meaning]).strip()
            pinyin2, pos2, meaning2 = parse_rest_without_pos_dict(merged_tail)
            if pinyin2:
                pinyin = pinyin2
                pos = pos2
                meaning = meaning2

        cleaned.append(
            {
                "no": no,
                "word": word,
                "pinyin": pinyin,
                "part_of_speech": pos,
                "translation": meaning,
            }
        )

    # Sort by entry number and deduplicate by first occurrence.
    seen = set()
    final_records: List[Dict[str, str]] = []
    for rec in sorted(cleaned, key=lambda r: int(r["no"])):
        n = int(rec["no"])
        if n in seen:
            continue
        seen.add(n)
        final_records.append(rec)

    recovered = recover_missing_rows_by_number_anchor(
        words=words,
        bounds=global_bounds,
        existing_numbers=[int(r["no"]) for r in final_records],
    )
    if recovered:
        for rec in recovered:
            n = int(rec["no"])
            if n in seen:
                continue
            seen.add(n)
            final_records.append(rec)
        final_records.sort(key=lambda r: int(r["no"]))

    return final_records, failed


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
    parser.add_argument("--level", type=int, default=5, help="HSK level number (for logging only).")
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

    try:
        words, page_ranges = extract_words_with_coords(pdf_path, skip_first_page=True)
    except ModuleNotFoundError:
        return 1

    records, failed_rows = build_records_from_coords(words, page_ranges)
    log(f"Parsed rows: {len(records)}")

    if failed_rows:
        log(f"WARNING: {len(failed_rows)} page(s) had extraction warnings")

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
