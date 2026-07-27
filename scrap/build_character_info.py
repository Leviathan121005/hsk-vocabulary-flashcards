#!/usr/bin/env python3
"""Build character metadata from the bundled HSK 1-5 vocabulary CSV files.

Run from the repository root with:
    python3 scrap/build_character_info.py
"""

from __future__ import annotations

import argparse
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
IDS_OPERATOR_ARITY = {
    "⿰": 2,
    "⿱": 2,
    "⿲": 3,
    "⿳": 3,
    "⿴": 2,
    "⿵": 2,
    "⿶": 2,
    "⿷": 2,
    "⿸": 2,
    "⿹": 2,
    "⿺": 2,
    "⿻": 2,
}


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


def new_character_info(character: str, pinyin: str) -> Dict[str, Any]:
    return {
        "character": character,
        "sample_pinyin": pinyin,
        "other_pinyins": [],
        "similar_visual_chars": [],
        "other_usecases": [],
    }


def add_pronunciation(info: Dict[str, Any], pinyin: str) -> None:
    if pinyin and pinyin != info["sample_pinyin"] and pinyin not in info["other_pinyins"]:
        info["other_pinyins"].append(pinyin)


def add_usecase(info: Dict[str, Any], word: str, pinyin: str, meaning: str) -> None:
    usecase = {"word": word, "pinyin": pinyin, "meaning": meaning}
    if usecase not in info["other_usecases"]:
        info["other_usecases"].append(usecase)


def build_character_info(csv_files: Sequence[Path]) -> Tuple[Dict[str, Dict[str, Any]], List[str]]:
    character_info: Dict[str, Dict[str, Any]] = {}
    alignment_warnings: List[str] = []

    for csv_file in csv_files:
        if not csv_file.exists():
            raise FileNotFoundError(f"Missing vocabulary CSV: {csv_file}")

        with csv_file.open("r", encoding="utf-8", newline="") as file:
            reader = csv.DictReader(file)
            for line_number, row in enumerate(reader, start=2):
                word = (row.get("word") or "").strip()
                word_pinyin = (row.get("pinyin") or "").strip()
                meaning = (row.get("translation") or "").strip()
                characters = [character for character in word if is_hanzi(character)]
                alternate_readings = [part.strip() for part in word_pinyin.split("/") if part.strip()]
                syllables = split_pinyin(alternate_readings[0], len(characters))

                if syllables is None:
                    alignment_warnings.append(f"{csv_file.name}:{line_number} could not align '{word}' with '{word_pinyin}'.")
                    fallback = first_syllable(alternate_readings[0]) if len(characters) == 1 else ""
                    syllables = [fallback] * len(characters)

                for character, character_pinyin in zip(characters, syllables):
                    info = character_info.setdefault(character, new_character_info(character, character_pinyin))
                    add_pronunciation(info, character_pinyin)
                    if len(characters) == 1:
                        for alternate_reading in alternate_readings[1:]:
                            add_pronunciation(info, alternate_reading)
                    add_usecase(info, word, word_pinyin, meaning)

    return dict(sorted(character_info.items())), alignment_warnings


def download_dictionary() -> None:
    """Download and cache the upstream character component dictionary."""

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


def parse_ids_node(decomposition: str, start: int = 0) -> Tuple[Optional[Tuple[str, List[Any]]], int]:
    """Parse one IDS node, preserving but never comparing nested child nodes."""

    if start >= len(decomposition):
        return None, start

    symbol = decomposition[start]
    arity = IDS_OPERATOR_ARITY.get(symbol)
    if arity is None:
        return (symbol, []), start + 1

    children = []
    index = start + 1
    for _ in range(arity):
        child, index = parse_ids_node(decomposition, index)
        if child is None:
            return None, index
        children.append(child)
    return (symbol, children), index


def top_level_slots(record: Dict[str, Any]) -> Optional[Tuple[str, List[str]]]:
    """Return direct IDS operands only, keeping their structural slots intact."""

    decomposition = record.get("decomposition")
    if not isinstance(decomposition, str) or not decomposition:
        return None

    root, end = parse_ids_node(decomposition)
    if root is None or end != len(decomposition):
        return None

    operator, children = root
    if operator not in IDS_OPERATOR_ARITY:
        return None

    slots = [child[0] if not child[1] else "" for child in children]
    return operator, slots


def slot_map(records: Sequence[Dict[str, Any]], hsk_characters: set[str]) -> Dict[str, Tuple[str, List[str]]]:
    """Map HSK characters to their depth-one IDS layout and direct slot values."""

    result = {}
    for record in records:
        character = record.get("character")
        if not isinstance(character, str) or character not in hsk_characters:
            continue
        slots = top_level_slots(record)
        if slots is not None:
            result[character] = slots
    return result


def pinyin_keys(info: Dict[str, Any]) -> set[str]:
    readings = [info.get("sample_pinyin", ""), *info.get("other_pinyins", [])]
    return {pinyin_base(reading) for reading in readings if pinyin_base(reading)}


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


def character_reference(character: str, info: Dict[str, Any]) -> Dict[str, Any]:
    """Create a similarity entry with every known reading of the character."""

    pinyins = [info.get("sample_pinyin", ""), *info.get("other_pinyins", [])]
    return {"character": character, "pinyins": [pinyin for pinyin in pinyins if pinyin]}


def build_similarities(character_info: Dict[str, Dict[str, Any]], records: Sequence[Dict[str, Any]]) -> None:
    """Populate depth-one, position-aligned visual and tone-insensitive pinyin matches."""

    characters = set(character_info)
    slots_by_character = slot_map(records, characters)
    characters_by_slot: Dict[Tuple[str, int, str], set[str]] = {}
    for character, (layout, slots) in slots_by_character.items():
        for slot_index, component in enumerate(slots):
            if component:
                characters_by_slot.setdefault((layout, slot_index, component), set()).add(character)

    for character, info in character_info.items():
        visual_groups = []
        layout_and_slots = slots_by_character.get(character)
        if layout_and_slots:
            layout, slots = layout_and_slots
            for slot_index, component in enumerate(slots):
                if not component:
                    continue
                matches = sorted(characters_by_slot[(layout, slot_index, component)] - {character})
                if matches:
                    visual_groups.append(
                        {
                            "layout": layout,
                            "slot": slot_index,
                            "components": [component],
                            "characters": [character_reference(match, character_info[match]) for match in matches],
                        }
                    )
        info["similar_visual_chars"] = visual_groups

def write_character_info(character_info: Dict[str, Dict[str, Any]]) -> None:
    with OUTPUT_FILE.open("w", encoding="utf-8") as file:
        json.dump(character_info, file, ensure_ascii=False, indent=2)
        file.write("\n")


def write_pinyin_index(character_info: Dict[str, Dict[str, Any]]) -> None:
    with PINYIN_INDEX_FILE.open("w", encoding="utf-8") as file:
        json.dump(build_pinyin_index(character_info), file, ensure_ascii=False, indent=2)
        file.write("\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mode",
        choices=("basics", "similarities"),
        default="basics",
        help="Build base character data or enrich existing data with similarities (default: basics).",
    )
    parser.add_argument(
        "--refresh-dictionary",
        action="store_true",
        help="Download the component dictionary again before building similarities.",
    )
    args = parser.parse_args()

    if args.mode == "similarities":
        try:
            if args.refresh_dictionary or not DICTIONARY_FILE.exists():
                download_dictionary()
            character_info = json.loads(OUTPUT_FILE.read_text(encoding="utf-8"))
            build_similarities(character_info, load_dictionary_records(DICTIONARY_FILE))
            write_character_info(character_info)
        except (OSError, ValueError, json.JSONDecodeError) as error:
            log(f"ERROR: {error}")
            return 1
        log(f"Updated similarities for {len(character_info)} characters")
        return 0

    try:
        character_info, warnings = build_character_info(CSV_FILES)
    except (OSError, csv.Error) as error:
        log(f"ERROR: {error}")
        return 1

    write_character_info(character_info)
    write_pinyin_index(character_info)

    log(f"Wrote {len(character_info)} unique characters to {OUTPUT_FILE.relative_to(REPO_ROOT)}")
    for warning in warnings:
        log(f"WARNING: {warning}")
    log(f"Pinyin alignment warnings: {len(warnings)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())