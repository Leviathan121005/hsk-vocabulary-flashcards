#!/usr/bin/env python3
"""Generate sentence examples indexed by HSK words.

Run from the repository root with:
    python3 scrap/get_sentence_examples.py

The script downloads the sentence corpus, filters sentences by selected HSK
levels, then builds an index mapping each HSK word to matching sentence items.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Tuple
from urllib.error import URLError
from urllib.parse import urlparse
from urllib.request import urlopen


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE_URL = "https://github.com/Roxaleen/hsk-annotated-corpus/blob/main/export/json/sentences.json"
DEFAULT_OUTPUT_PATH = REPO_ROOT / "public" / "sentence_example.json"
DEFAULT_LEVELS = [1, 2, 3, 4, 5]


def log(message: str) -> None:
    print(f"[sentence-examples] {message}")


def normalize_text(text: str) -> str:
    return unicodedata.normalize("NFKC", text.strip())


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build HSK sentence example index.")
    parser.add_argument("--source-url", default=DEFAULT_SOURCE_URL, help="Sentence corpus URL (GitHub blob URL is supported).")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH, help="Output JSON path.")
    parser.add_argument(
        "--levels",
        type=int,
        nargs="+",
        default=DEFAULT_LEVELS,
        help="HSK sentence levels to include (default: 1 2 3 4 5).",
    )
    parser.add_argument(
        "--max-sentences",
        type=int,
        default=5,
        help="Maximum number of sentence examples to keep per word (default: 5).",
    )
    return parser.parse_args()


def validate_levels(raw_levels: list[int]) -> list[int]:
    cleaned = sorted(set(raw_levels))
    if not cleaned:
        raise ValueError("At least one HSK level must be provided.")
    for level in cleaned:
        if level < 1 or level > 9:
            raise ValueError(f"Invalid HSK level: {level}. Expected range is 1..9.")
    return cleaned


def validate_max_sentences(max_sentences: int) -> int:
    if max_sentences < 1:
        raise ValueError("--max-sentences must be at least 1.")
    return max_sentences


def to_raw_github_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.netloc != "github.com":
        return url

    parts = parsed.path.strip("/").split("/")
    if len(parts) < 5 or parts[2] != "blob":
        return url

    # Prefer the blob endpoint with ?raw=1 because Git LFS-backed files can
    # return pointer text on raw.githubusercontent.com.
    return f"https://github.com{parsed.path}?raw=1"


def download_json(url: str) -> Tuple[Any, str]:
    raw_url = to_raw_github_url(url)
    log(f"Downloading corpus from: {raw_url}")

    try:
        with urlopen(raw_url, timeout=60) as response:
            payload = response.read().decode("utf-8")
    except URLError as error:
        raise RuntimeError(f"Failed to download corpus: {error}") from error

    if payload.startswith("version https://git-lfs.github.com/spec/v1"):
        raise RuntimeError(
            "Downloaded content is a Git LFS pointer instead of JSON. "
            "Try providing a direct downloadable URL for the corpus file."
        )

    try:
        return json.loads(payload), raw_url
    except json.JSONDecodeError as error:
        raise RuntimeError(f"Failed to parse corpus JSON: {error}") from error


def parse_level(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        text = value.strip()
        if text.isdigit():
            return int(text)
    return None


def load_hsk_words(levels: list[int]) -> tuple[dict[str, dict[str, Any]], dict[str, list[str]]]:
    words_by_norm: dict[str, dict[str, Any]] = {}
    words_by_first_char: dict[str, list[str]] = {}

    for level in levels:
        csv_path = REPO_ROOT / "public" / f"hsk-{level}-vocabulary.csv"
        if not csv_path.exists():
            raise FileNotFoundError(f"Missing vocabulary CSV: {csv_path}")

        with csv_path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                word = normalize_text(row.get("word", ""))
                if not word:
                    continue
                meta = words_by_norm.setdefault(word, {"word": word, "levels": set()})
                meta["levels"].add(level)

    for word in words_by_norm:
        first_char = word[0]
        words_by_first_char.setdefault(first_char, []).append(word)

    return words_by_norm, words_by_first_char


def find_matching_words(sentence_text: str, words_by_first_char: dict[str, list[str]]) -> set[str]:
    if not sentence_text:
        return set()

    candidate_words: set[str] = set()
    for char in set(sentence_text):
        candidate_words.update(words_by_first_char.get(char, []))

    return {word for word in candidate_words if word in sentence_text}


def build_sentence_index(
    corpus: Any,
    selected_levels: list[int],
    words_by_norm: dict[str, dict[str, Any]],
    words_by_first_char: dict[str, list[str]],
    max_sentences_per_word: int,
) -> tuple[dict[str, dict[str, Any]], dict[str, int]]:
    if not isinstance(corpus, dict):
        raise RuntimeError("Corpus root must be a JSON object keyed by sentence text.")

    by_word: dict[str, dict[str, Any]] = {}
    dedupe_keys: set[tuple[str, str, str, int]] = set()

    total_sentences = 0
    level_filtered_sentences = 0
    matched_sentences = 0
    malformed_records = 0

    selected_set = set(selected_levels)

    for sentence, payload in corpus.items():
        total_sentences += 1

        if not isinstance(sentence, str) or not isinstance(payload, dict):
            malformed_records += 1
            continue

        sentence_level = parse_level(payload.get("level"))
        if sentence_level is None or sentence_level not in selected_set:
            continue
        level_filtered_sentences += 1

        normalized_sentence = normalize_text(sentence)
        if not normalized_sentence:
            continue

        matching_words = find_matching_words(normalized_sentence, words_by_first_char)
        if not matching_words:
            continue

        matched_any_for_sentence = False
        for matched_word in matching_words:
            word_meta = words_by_norm.get(matched_word)
            if not word_meta:
                continue

            word_levels = word_meta["levels"]
            if sentence_level not in word_levels:
                continue

            has_multiple_levels = len(word_levels) > 1

            dedupe_key = (
                word_meta["word"],
                sentence,
                str(payload.get("source", "")),
                sentence_level,
            )
            if dedupe_key in dedupe_keys:
                continue
            dedupe_keys.add(dedupe_key)

            entry = {
                "sentence": sentence,
                "translation": payload.get("translation", ""),
            }
            if has_multiple_levels:
                entry["disable"] = True

            word_entry = by_word.setdefault(word_meta["word"], {"levels": {}})

            level_key = str(sentence_level)
            sentence_items = word_entry["levels"].setdefault(level_key, [])

            if len(sentence_items) >= max_sentences_per_word:
                continue
            sentence_items.append(entry)
            matched_any_for_sentence = True

        if matched_any_for_sentence:
            matched_sentences += 1

    for word in by_word:
        level_entries = by_word[word]["levels"]
        for level_key in sorted(level_entries.keys(), key=lambda item: int(item)):
            level_sentences = level_entries[level_key]
            level_sentences.sort(key=lambda item: item["sentence"])

    stats = {
        "total_sentences": total_sentences,
        "level_filtered_sentences": level_filtered_sentences,
        "matched_sentences": matched_sentences,
        "malformed_records": malformed_records,
        "indexed_words": len(by_word),
        "indexed_sentence_items": sum(
            len(level_entry)
            for items in by_word.values()
            for level_entry in items.get("levels", {}).values()
        ),
        "max_sentences_per_word": max_sentences_per_word,
    }
    return by_word, stats


def write_output(
    output_path: Path,
    source_url: str,
    selected_levels: list[int],
    by_word: dict[str, dict[str, Any]],
    stats: dict[str, int],
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)

    sorted_by_word = {word: by_word[word] for word in sorted(by_word.keys())}
    payload = {
        "meta": {
            "version": 2,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "source_url": source_url,
            "selected_levels": selected_levels,
            **stats,
        },
        "by_word": sorted_by_word,
    }

    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    args = parse_args()

    try:
        selected_levels = validate_levels(args.levels)
        max_sentences_per_word = validate_max_sentences(args.max_sentences)
        corpus, raw_url = download_json(args.source_url)
        words_by_norm, words_by_first_char = load_hsk_words(selected_levels)
        by_word, stats = build_sentence_index(
            corpus,
            selected_levels,
            words_by_norm,
            words_by_first_char,
            max_sentences_per_word,
        )
        write_output(args.output, raw_url, selected_levels, by_word, stats)
    except Exception as error:
        log(f"Error: {error}")
        return 1

    log(f"Saved sentence examples to: {args.output}")
    log(
        "Summary: "
        f"sentences={stats['total_sentences']}, "
        f"filtered={stats['level_filtered_sentences']}, "
        f"matched={stats['matched_sentences']}, "
        f"indexed_words={stats['indexed_words']}, "
        f"items={stats['indexed_sentence_items']}, "
        f"malformed={stats['malformed_records']}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())