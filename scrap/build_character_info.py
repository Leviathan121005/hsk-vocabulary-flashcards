#!/usr/bin/env python3
"""Build character metadata from bundled HSK CSV files.

Run from the repository root with:
    python3 scrap/build_character_info.py
"""

from __future__ import annotations

import csv
import json
import re
import sys
import unicodedata
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple
from urllib.error import URLError
from urllib.request import urlopen


REPO_ROOT = Path(__file__).resolve().parents[1]
CSV_FILES = [REPO_ROOT / "public" / f"hsk-{level}-vocabulary.csv" for level in range(1, 6)]
OUTPUT_FILE = REPO_ROOT / "public" / "character_info.json"
PINYIN_INDEX_FILE = REPO_ROOT / "public" / "pinyin_to_characters.json"
OTHER_USE_CASES_FILE = REPO_ROOT / "public" / "other_use_cases.json"
DICTIONARY_FILE = REPO_ROOT / "scrap" / "dictionary.json"
DICTIONARY_URLS = (
    "https://raw.githubusercontent.com/skritter/make-me-a-hanzi/master/dictionary.json",
    "https://raw.githubusercontent.com/skishore/makemeahanzi/master/dictionary.txt",
    "https://cdn.jsdelivr.net/gh/skishore/makemeahanzi@master/dictionary.txt",
)

INITIALS = (
    "zh",
    "ch",
    "sh",
    "b",
    "p",
    "m",
    "f",
    "d",
    "t",
    "n",
    "l",
    "g",
    "k",
    "h",
    "j",
    "q",
    "x",
    "r",
    "z",
    "c",
    "s",
    "y",
    "w",
)
FINALS = (
    "iang",
    "uang",
    "iong",
    "ueng",
    "uai",
    "uan",
    "ang",
    "eng",
    "ing",
    "ong",
    "iao",
    "ian",
    "uan",
    "uen",
    "uei",
    "iao",
    "iou",
    "ueng",
    "ai",
    "ei",
    "ao",
    "ou",
    "an",
    "en",
    "er",
    "ia",
    "ie",
    "iu",
    "in",
    "ua",
    "uo",
    "ui",
    "un",
    "ue",
    "ve",
    "vn",
    "a",
    "e",
    "i",
    "o",
    "u",
    "v",
)
VALID_SYLLABLES = {initial + final for initial in INITIALS for final in FINALS}
VALID_SYLLABLES.update({"a", "ai", "an", "ang", "ao", "e", "ei", "en", "eng", "er", "o", "ou", "m", "n", "ng", "hm", "r"})
PINYIN_LETTER_RE = re.compile(r"[a-züv]", re.IGNORECASE)


def log(message: str) -> None:
    print(f"[character-info] {message}")


def is_hanzi(character: str) -> bool:
    code = ord(character)
    return (
        0x3400 <= code <= 0x4DBF
        or 0x4E00 <= code <= 0x9FFF
        or 0xF900 <= code <= 0xFAFF
        or 0x2E80 <= code <= 0x2EFF
        or 0x2F00 <= code <= 0x2FDF
        or 0x20000 <= code <= 0x323AF
    )


def pinyin_base(text: str) -> str:
    decomposed = unicodedata.normalize("NFD", text.lower())
    return "".join(character for character in decomposed if unicodedata.category(character) != "Mn").replace("ü", "v")


def normalize_hanzi_text(text: str) -> str:
    """Normalize compatibility Hanzi/radical forms to standard code points."""

    return unicodedata.normalize("NFKC", text)


def is_valid_syllable(syllable: str) -> bool:
    base = pinyin_base(syllable)
    return base in VALID_SYLLABLES


def split_pinyin(pinyin: str, character_count: int) -> Optional[List[str]]:
    """Split compact pinyin into one syllable per Han character.

    HSK CSV pinyin is generally compact (for example, ``bàba``). Spaces and
    apostrophes are respected when present; otherwise valid pinyin syllables
    are tried until their count matches the source word's Han characters.
    """

    explicit = [part for part in re.split(r"[\s'’-]+", pinyin.strip()) if part]
    if len(explicit) == character_count and all(is_valid_syllable(part) for part in explicit):
        return explicit

    compact = "".join(part for part in explicit if PINYIN_LETTER_RE.search(part))
    if not compact:
        return None

    memo: Dict[Tuple[int, int], Optional[List[str]]] = {}

    def find_parts(index: int, remaining: int) -> Optional[List[str]]:
        key = (index, remaining)
        if key in memo:
            return memo[key]
        if index == len(compact):
            return [] if remaining == 0 else None
        if remaining == 0:
            return None

        # A Mandarin syllable is at most six letters after tone marks are removed.
        for end in range(min(len(compact), index + 7), index, -1):
            syllable = compact[index:end]
            if not is_valid_syllable(syllable):
                continue
            rest = find_parts(end, remaining - 1)
            if rest is not None:
                memo[key] = [syllable, *rest]
                return memo[key]

        memo[key] = None
        return None

    return find_parts(0, character_count)


def first_syllable(pinyin: str) -> str:
    """Return the first pinyin syllable for a malformed one-character row."""

    compact = "".join(part for part in re.split(r"[\s'’/-]+", pinyin) if part)
    for end in range(min(len(compact), 7), 0, -1):
        syllable = compact[:end]
        if is_valid_syllable(syllable):
            return syllable
    return pinyin.strip()


def new_character_info(character: str, pinyin: str, meaning: str = "") -> Dict[str, Any]:
    return {
        "character": character,
        "meaning": meaning,
        "sample_pinyin": pinyin,
        "other_pinyins": [],
        "similar_visual_chars": [],
    }


def add_pronunciation(info: Dict[str, Any], pinyin: str) -> None:
    if pinyin and pinyin != info["sample_pinyin"] and pinyin not in info["other_pinyins"]:
        info["other_pinyins"].append(pinyin)


def add_usecase(
    character: str,
    word: str,
    pinyin: str,
    meaning: str,
    entries: List[Dict[str, str]],
    index_by_key: Dict[Tuple[str, str, str], int],
    by_character: Dict[str, set[int]],
) -> None:
    key = (word, pinyin, meaning)
    usecase_index = index_by_key.get(key)
    if usecase_index is None:
        usecase_index = len(entries)
        entries.append({"word": word, "pinyin": pinyin, "meaning": meaning})
        index_by_key[key] = usecase_index

    by_character.setdefault(character, set()).add(usecase_index)


def lookup_character_meaning(character: str, character_meanings: Dict[str, str]) -> str:
    for variant in (character, unicodedata.normalize("NFKC", character), unicodedata.normalize("NFKD", character)):
        definition = (character_meanings.get(variant) or "").strip()
        if definition:
            return definition
    return ""


def build_character_info(
    csv_files: Sequence[Path],
    character_meanings: Dict[str, str],
) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, Any], List[str]]:
    character_info: Dict[str, Dict[str, Any]] = {}
    usecase_entries: List[Dict[str, str]] = []
    usecase_index_by_key: Dict[Tuple[str, str, str], int] = {}
    usecases_by_character: Dict[str, set[int]] = {}
    alignment_warnings: List[str] = []

    for csv_file in csv_files:
        if not csv_file.exists():
            raise FileNotFoundError(f"Missing vocabulary CSV: {csv_file}")

        with csv_file.open("r", encoding="utf-8", newline="") as file:
            reader = csv.DictReader(file)
            for line_number, row in enumerate(reader, start=2):
                word = (row.get("word") or "").strip()
                normalized_word = normalize_hanzi_text(word)
                word_pinyin = (row.get("pinyin") or "").strip()
                meaning = (row.get("translation") or "").strip()
                characters = [character for character in normalized_word if is_hanzi(character)]
                alternate_readings = [part.strip() for part in word_pinyin.split("/") if part.strip()]
                syllables = split_pinyin(alternate_readings[0], len(characters))

                if syllables is None:
                    alignment_warnings.append(f"{csv_file.name}:{line_number} could not align '{normalized_word}' with '{word_pinyin}'.")
                    fallback = first_syllable(alternate_readings[0]) if len(characters) == 1 else ""
                    syllables = [fallback] * len(characters)

                for character, character_pinyin in zip(characters, syllables):
                    character_meaning = lookup_character_meaning(character, character_meanings)
                    info = character_info.setdefault(
                        character,
                        new_character_info(character, character_pinyin, character_meaning),
                    )
                    if not info.get("meaning") and character_meaning:
                        info["meaning"] = character_meaning
                    add_pronunciation(info, character_pinyin)
                    if len(characters) == 1:
                        for alternate_reading in alternate_readings[1:]:
                            add_pronunciation(info, alternate_reading)
                    add_usecase(
                        character,
                        normalized_word,
                        word_pinyin,
                        meaning,
                        usecase_entries,
                        usecase_index_by_key,
                        usecases_by_character,
                    )

    other_use_cases = {
        "version": 1,
        "entries": usecase_entries,
        "by_character": {
            character: sorted(indices) for character, indices in sorted(usecases_by_character.items())
        },
    }
    return dict(sorted(character_info.items())), other_use_cases, alignment_warnings


def download_dictionary() -> None:
    """Download and cache the dictionary data used for meanings."""

    errors = []
    for url in DICTIONARY_URLS:
        try:
            with urlopen(url, timeout=60) as response:
                content = response.read()
            DICTIONARY_FILE.write_bytes(content)
            log(f"Downloaded dictionary from {url}")
            return
        except (OSError, URLError) as error:
            errors.append(f"{url}: {error}")

    raise OSError("Could not download dictionary. " + " | ".join(errors))


def load_dictionary_records(path: Path) -> List[Dict[str, Any]]:
    """Load either a JSON collection or Make Me a Hanzi's line-delimited JSON."""

    raw = path.read_text(encoding="utf-8")
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        records = [json.loads(line) for line in raw.splitlines() if line.strip()]
    else:
        if isinstance(parsed, dict):
            records = parsed.get("characters", parsed)
            if isinstance(records, dict):
                records = list(records.values())
        else:
            records = parsed

    if not isinstance(records, list):
        raise ValueError(f"{path} does not contain a character record list.")
    return [record for record in records if isinstance(record, dict)]


def ensure_dictionary_records() -> List[Dict[str, Any]]:
    """Return dictionary records, downloading dictionary.json when needed."""

    if DICTIONARY_FILE.exists():
        return load_dictionary_records(DICTIONARY_FILE)

    log(f"{DICTIONARY_FILE.relative_to(REPO_ROOT)} not found; attempting download...")
    download_dictionary()
    return load_dictionary_records(DICTIONARY_FILE)


def build_character_meanings(records: Sequence[Dict[str, Any]]) -> Dict[str, str]:
    meanings: Dict[str, str] = {}
    for record in records:
        character = record.get("character")
        definition = str(record.get("definition") or "").strip()
        if isinstance(character, str) and len(character) == 1 and definition:
            variants = {
                character,
                unicodedata.normalize("NFKC", character),
                unicodedata.normalize("NFKD", character),
            }
            for variant in variants:
                if variant and variant not in meanings:
                    meanings[variant] = definition
    return meanings


def build_pinyin_index(character_info: Dict[str, Dict[str, Any]]) -> Dict[str, Dict[str, List[str]]]:
    """Map tone-free pinyin to each tonal reading and its HSK characters."""

    index: Dict[str, Dict[str, set[str]]] = {}
    for character, info in character_info.items():
        readings = [info.get("sample_pinyin", ""), *info.get("other_pinyins", [])]
        for reading in readings:
            key = pinyin_base(reading)
            if key and reading:
                index.setdefault(key, {}).setdefault(reading, set()).add(character)

    return {
        key: {reading: sorted(characters) for reading, characters in sorted(readings.items())}
        for key, readings in sorted(index.items())
    }

def write_character_info(character_info: Dict[str, Dict[str, Any]]) -> None:
    with OUTPUT_FILE.open("w", encoding="utf-8") as file:
        json.dump(character_info, file, ensure_ascii=False, indent=2)
        file.write("\n")


def write_pinyin_index(character_info: Dict[str, Dict[str, Any]]) -> None:
    with PINYIN_INDEX_FILE.open("w", encoding="utf-8") as file:
        json.dump(build_pinyin_index(character_info), file, ensure_ascii=False, indent=2)
        file.write("\n")


def write_other_use_cases(other_use_cases: Dict[str, Any]) -> None:
    with OTHER_USE_CASES_FILE.open("w", encoding="utf-8") as file:
        json.dump(other_use_cases, file, ensure_ascii=False, indent=2)
        file.write("\n")


def main() -> int:
    character_meanings: Dict[str, str] = {}
    try:
        dictionary_records = ensure_dictionary_records()
        character_meanings = build_character_meanings(dictionary_records)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        log(f"WARNING: Could not prepare {DICTIONARY_FILE.relative_to(REPO_ROOT)}: {error}")
        log("Need to add methods/resources to utilize dictionary-dependent meanings; continuing with empty meanings.")

    try:
        character_info, other_use_cases, warnings = build_character_info(CSV_FILES, character_meanings)
    except (OSError, csv.Error) as error:
        log(f"ERROR: {error}")
        return 1

    write_character_info(character_info)
    write_pinyin_index(character_info)
    write_other_use_cases(other_use_cases)

    log(f"Wrote {len(character_info)} unique characters to {OUTPUT_FILE.relative_to(REPO_ROOT)}")
    log(f"Loaded meanings for {sum(1 for info in character_info.values() if info.get('meaning'))} characters")
    log(f"Wrote {len(other_use_cases['entries'])} unique use cases to {OTHER_USE_CASES_FILE.relative_to(REPO_ROOT)}")
    for warning in warnings:
        log(f"WARNING: {warning}")
    log(f"Pinyin alignment warnings: {len(warnings)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())