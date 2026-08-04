#!/usr/bin/env python3
"""Find similar Chinese characters with CV and phonetic rules.

This script merges the previous CV and naive pipelines into one place.

Methods:
- glyph
- ssim
- fusion
- or
- intersect
- exp
- phonetic

Key booleans:
- include_phonetic: append extra phonetic-only candidates (renamed from naive)
- use_phonetic: embed "or phonetic" directly into method pass conditions
- include_decomposition: append character pairs with one difference in decomposition

Phonetic matching rule (replaces decomposition-minus-radical naive rule):
1) query phonetic == candidate character, OR
2) candidate phonetic == query character, OR
3) query and candidate share the same phonetic

Examples:
  python3 scrap/find_similar_characters.py --method glyph --threshold 0.90 --use-phonetic
  python3 scrap/find_similar_characters.py --method ssim --threshold 0.60 --include-phonetic
  python3 scrap/find_similar_characters.py --method or --glyph-threshold 0.90 --ssim-threshold 0.60 --use-phonetic
  python3 scrap/find_similar_characters.py --method fusion --threshold 1.75 --include-phonetic
  python3 scrap/find_similar_characters.py --method phonetic
  python3 scrap/find_similar_characters.py --method ssim --threshold 0.60 --include-decomposition

Current:
  python3 scrap/find_similar_characters.py --method exp --glyph-threshold 0.80 --ssim-threshold 0.60 --use-phonetic --include-decomposition
"""

from __future__ import annotations

import argparse
import csv
import json
import time
from pathlib import Path
from typing import Any, Optional

import torch
from PIL import Image, ImageDraw, ImageFont
from torchvision.models import MobileNet_V3_Small_Weights, mobilenet_v3_small

try:
    from skimage.metrics import structural_similarity as skimage_ssim
except Exception:
    skimage_ssim = None


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CHARACTER_INFO_PATH = REPO_ROOT / "public" / "character_info.json"
DEFAULT_DICTIONARY_PATH = REPO_ROOT / "scrap" / "dictionary.json"
DEFAULT_SSIM_CACHE = REPO_ROOT / "scrap" / "ssim_cache.npz"
DEFAULT_DECOMPOSITION_PAIRS_PATH = REPO_ROOT / "scrap" / "decomposition_pairs_one_character_difference.csv"

DEFAULT_FONT_CANDIDATES = (
    Path("/System/Library/Fonts/PingFang.ttc"),
    Path("/System/Library/Fonts/STHeiti Medium.ttc"),
)
CANVAS_SIZE = 64
CV_SSIM_WEIGHT = 1.5

# Quick in-file defaults.
glyph_method = "cosine"
include_phonetic_default = False
use_phonetic_default = False
decomposition_method = "decomposition"


def log(message: str) -> None:
    print(f"[find-similar-characters] {message}", flush=True)


def load_dictionary_records(path: Path) -> dict[str, dict[str, Any]]:
    raw = path.read_text(encoding="utf-8")
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        records = [json.loads(line) for line in raw.splitlines() if line.strip()]
    else:
        records = parsed.get("characters", parsed) if isinstance(parsed, dict) else parsed
        if isinstance(records, dict):
            records = list(records.values())

    if not isinstance(records, list):
        raise ValueError(f"{path} does not contain a character record list.")

    return {
        record["character"]: record
        for record in records
        if isinstance(record, dict) and isinstance(record.get("character"), str) and len(record["character"]) == 1
    }


def build_stroke_counts(records: dict[str, dict[str, Any]]) -> dict[str, int]:
    return {
        character: len(record.get("matches", []))
        for character, record in records.items()
        if isinstance(record.get("matches"), list) and len(record["matches"]) > 0
    }


def pinyins_for(info: dict[str, Any]) -> list[str]:
    pinyins = [info.get("sample_pinyin", ""), *(info.get("other_pinyins", []) or [])]
    return [pinyin for pinyin in pinyins if pinyin]


def extract_phonetic(record: dict[str, Any]) -> str:
    etymology = record.get("etymology")
    if not isinstance(etymology, dict):
        return ""
    value = etymology.get("phonetic")
    if not isinstance(value, str):
        return ""
    return value.strip()


def build_phonetic_map(records: dict[str, dict[str, Any]], characters: list[str]) -> dict[str, str]:
    return {character: extract_phonetic(records.get(character, {})) for character in characters}


def phonetic_match_details(query: str, candidate: str, phonetic_map: dict[str, str]) -> tuple[bool, bool, bool, bool]:
    """Return phonetic relation booleans.

    Returns:
      (is_match, query_phonetic_is_candidate, candidate_phonetic_is_query, shared_phonetic)
    """

    query_phonetic = phonetic_map.get(query, "")
    candidate_phonetic = phonetic_map.get(candidate, "")

    query_phonetic_is_candidate = bool(query_phonetic) and query_phonetic == candidate
    candidate_phonetic_is_query = bool(candidate_phonetic) and candidate_phonetic == query
    shared_phonetic = bool(query_phonetic) and query_phonetic == candidate_phonetic

    is_match = query_phonetic_is_candidate or candidate_phonetic_is_query or shared_phonetic
    return is_match, query_phonetic_is_candidate, candidate_phonetic_is_query, shared_phonetic


def phonetic_override_pass(
    use_phonetic: bool,
    phonetic_match: bool,
    glyph_score: float,
    ssim_score: float,
    glyph_floor: float,
    ssim_floor: float,
) -> bool:
    """Controlled phonetic override for CV methods.

    Prevents phonetic relation from bypassing both visual signals completely.
    """

    if not use_phonetic or not phonetic_match:
        return False
    return glyph_score >= glyph_floor or ssim_score >= ssim_floor


def resolve_font_path(requested_path: Optional[str]) -> Path:
    if requested_path:
        path = Path(requested_path).expanduser()
        if path.is_file():
            return path
        raise FileNotFoundError(f"Font not found: {path}")

    for path in DEFAULT_FONT_CANDIDATES:
        if path.is_file():
            return path
    raise FileNotFoundError("No supported Chinese font was found. Pass one with --glyph-font.")


def resolve_torch_device(device_name: str) -> torch.device:
    if device_name == "mps":
        return torch.device("mps")
    if device_name == "cpu":
        return torch.device("cpu")
    if torch.backends.mps.is_available():
        return torch.device("mps")
    return torch.device("cpu")


def render_character(character: str, font_path: Path) -> Image.Image:
    canvas = Image.new("L", (CANVAS_SIZE, CANVAS_SIZE), color=255)
    draw = ImageDraw.Draw(canvas)
    font = ImageFont.truetype(str(font_path), size=56)
    left, top, right, bottom = draw.textbbox((0, 0), character, font=font)
    width = right - left
    height = bottom - top
    draw.text(((CANVAS_SIZE - width) / 2 - left, (CANVAS_SIZE - height) / 2 - top), character, fill=0, font=font)
    return canvas


def render_character_array(character: str, font_path: Path, size: int = CANVAS_SIZE) -> Any:
    import numpy as np

    canvas = Image.new("L", (size, size), color=255)
    draw = ImageDraw.Draw(canvas)
    font = ImageFont.truetype(str(font_path), int(size * 0.85))
    left, top, right, bottom = draw.textbbox((0, 0), character, font=font)
    width = right - left
    height = bottom - top
    draw.text(((size - width) / 2 - left, (size - height) / 2 - top), character, fill=0, font=font)
    return np.asarray(canvas, dtype=np.uint8)


def ssim_score(image_one: Any, image_two: Any) -> float:
    import numpy as np

    if skimage_ssim is not None:
        score, _ = skimage_ssim(image_one, image_two, full=True)
        return float(score)

    diff = np.mean(np.abs(image_one.astype(np.float32) - image_two.astype(np.float32))) / 255.0
    return float(1.0 - 2.0 * diff)


def load_ssim_cache(cache_path: Path, characters: list[str], font_path: Path, ssim_size: int) -> Optional[tuple[Any, dict[str, int]]]:
    import numpy as np

    if not cache_path.exists():
        return None

    try:
        archive = np.load(cache_path, allow_pickle=False)
    except Exception:
        return None

    try:
        cached_characters = [str(item) for item in archive["characters"].tolist()]
        cached_scores = archive["scores"]
        cached_size = int(archive["ssim_size"].item())
        cached_font = str(archive["font_path"].item())
    except Exception:
        return None

    expected = list(characters)
    if cached_characters != expected:
        return None
    if cached_scores.shape != (len(expected), len(expected)):
        return None
    if cached_size != ssim_size:
        return None
    if cached_font != str(font_path):
        return None

    index_by_character = {character: index for index, character in enumerate(expected)}
    return cached_scores, index_by_character


def build_and_save_ssim_cache(cache_path: Path, characters: list[str], font_path: Path, ssim_size: int) -> tuple[Any, dict[str, int]]:
    import numpy as np

    total = len(characters)
    images = {character: render_character_array(character, font_path, size=ssim_size) for character in characters}
    scores = np.empty((total, total), dtype=np.float32)

    started = time.time()
    for left_index, left_character in enumerate(characters):
        left_image = images[left_character]
        scores[left_index, left_index] = 1.0

        for right_index in range(left_index + 1, total):
            right_character = characters[right_index]
            score = ssim_score(left_image, images[right_character])
            scores[left_index, right_index] = score
            scores[right_index, left_index] = score

        if (left_index + 1) % 25 == 0 or left_index + 1 == total:
            elapsed = time.time() - started
            rate = (left_index + 1) / elapsed if elapsed > 0 else 0.0
            eta_seconds = (total - (left_index + 1)) / rate if rate > 0 else 0.0
            log(f"SSIM cache build {left_index + 1}/{total} rows | elapsed={elapsed:.1f}s | eta={eta_seconds:.1f}s")

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        cache_path,
        scores=scores,
        characters=np.asarray(characters),
        ssim_size=np.asarray([ssim_size], dtype=np.int32),
        font_path=np.asarray([str(font_path)]),
    )
    index_by_character = {character: index for index, character in enumerate(characters)}
    return scores, index_by_character


def load_or_build_ssim_cache(
    cache_path: Path,
    refresh: bool,
    characters: list[str],
    font_path: Path,
    ssim_size: int,
) -> tuple[Any, dict[str, int]]:
    if not refresh:
        cached = load_ssim_cache(cache_path, characters, font_path, ssim_size)
        if cached is not None:
            log(f"SSIM cache: loaded {cache_path}")
            return cached

    reason = "refresh requested" if refresh else "missing or incompatible"
    log(f"SSIM cache: building ({reason})")
    matrix, index_by_character = build_and_save_ssim_cache(cache_path, characters, font_path, ssim_size)
    log(f"SSIM cache: saved {cache_path}")
    return matrix, index_by_character


def build_embeddings(characters: list[str], font_path: Path, device: torch.device) -> torch.Tensor:
    weights = MobileNet_V3_Small_Weights.DEFAULT
    preprocess = weights.transforms()
    model = mobilenet_v3_small(weights=weights).features.to(device).eval()
    images = torch.stack([preprocess(render_character(character, font_path).convert("RGB")) for character in characters])

    batches = []
    batch_size = 64
    total_batches = (len(images) + batch_size - 1) // batch_size
    with torch.inference_mode():
        for batch_index, start in enumerate(range(0, len(images), batch_size), start=1):
            features = model(images[start : start + batch_size].to(device))
            pooled = features.mean(dim=(2, 3))
            batches.append(torch.nn.functional.normalize(pooled, dim=1).cpu())
            if batch_index % 8 == 0 or batch_index == total_batches:
                log(f"Glyph embedding progress: batch {batch_index}/{total_batches}")
    return torch.cat(batches)


def similarity_matrix(embeddings: torch.Tensor, metric: str) -> torch.Tensor:
    cosine = embeddings @ embeddings.T
    if metric == "cosine":
        return cosine
    if metric == "euclidean":
        return 1 - torch.cdist(embeddings, embeddings) / 2
    if metric == "tanh":
        return (torch.tanh(2 * cosine) + 1) / 2
    raise ValueError(f"Unsupported metric: {metric}")


def normalize_glyph_metric(metric: str) -> str:
    normalized = (metric or "").strip().lower()
    if normalized == "euclidian":
        return "euclidean"
    if normalized in ("cosine", "euclidean", "tanh"):
        return normalized
    raise ValueError(f"Unsupported metric: {metric}")


def rank_phonetic(
    query: str,
    characters: list[str],
    char_info: dict[str, dict[str, Any]],
    phonetic_map: dict[str, str],
    top_k: int,
) -> list[dict[str, Any]]:
    rows: list[tuple[int, int, str]] = []

    for candidate in characters:
        if candidate == query:
            continue
        is_match, query_phonetic_is_candidate, candidate_phonetic_is_query, shared_phonetic = phonetic_match_details(
            query,
            candidate,
            phonetic_map,
        )
        if not is_match:
            continue

        # Rank by stronger relation first.
        relation_strength = int(query_phonetic_is_candidate) + int(candidate_phonetic_is_query) + int(shared_phonetic)
        rows.append((relation_strength, int(shared_phonetic), candidate))

    rows.sort(key=lambda item: (-item[0], -item[1], item[2]))

    output = []
    for _, _, candidate in rows[:top_k]:
        output.append(
            {
                "character": candidate,
                "pinyins": pinyins_for(char_info[candidate]),
                "method": "phonetic",
            }
        )
    return output


def rank_glyph(
    query: str,
    characters: list[str],
    char_info: dict[str, dict[str, Any]],
    index_by_character: dict[str, int],
    similarities: torch.Tensor,
    stroke_counts: dict[str, int],
    threshold: float,
    max_stroke_gap: int,
    top_k: int,
    phonetic_map: dict[str, str],
    use_phonetic: bool,
) -> list[dict[str, Any]]:
    query_index = index_by_character.get(query)
    query_strokes = stroke_counts.get(query)
    if query_index is None or query_strokes is None:
        return []

    row = similarities[query_index]
    results: list[tuple[str, float, int, bool]] = []
    for candidate_index, score_tensor in enumerate(row):
        if candidate_index == query_index:
            continue
        score = float(score_tensor.item())
        candidate = characters[candidate_index]

        candidate_strokes = stroke_counts.get(candidate)
        if candidate_strokes is None:
            continue
        stroke_gap = abs(query_strokes - candidate_strokes)
        if stroke_gap > max_stroke_gap:
            continue

        phonetic_match = phonetic_match_details(query, candidate, phonetic_map)[0]
        pass_condition = score >= threshold
        if use_phonetic:
            # Allow mild relaxation for phonetic relations, but avoid no-signal matches.
            phonetic_floor = max(0.0, threshold - 0.05)
            pass_condition = pass_condition or (phonetic_match and score >= phonetic_floor)
        if not pass_condition:
            continue

        results.append((candidate, score, stroke_gap, phonetic_match))

    results.sort(key=lambda item: (-item[1], item[0]))
    output = []
    for candidate, score, stroke_gap, phonetic_match in results[:top_k]:
        entry: dict[str, Any] = {
            "character": candidate,
            "pinyins": pinyins_for(char_info[candidate]),
            "score": round(score, 4),
            "glyph_score": round(score, 4),
            "stroke_count_difference": stroke_gap,
        }
        if phonetic_match:
            entry["phonetic_match"] = True
        output.append(entry)
    return output


def rank_ssim(
    query: str,
    characters: list[str],
    char_info: dict[str, dict[str, Any]],
    index_by_character: dict[str, int],
    score_matrix: Any,
    stroke_counts: dict[str, int],
    threshold: float,
    max_stroke_gap: int,
    top_k: int,
    phonetic_map: dict[str, str],
    use_phonetic: bool,
) -> list[dict[str, Any]]:
    query_index = index_by_character.get(query)
    query_strokes = stroke_counts.get(query)
    if query_index is None or query_strokes is None:
        return []

    results: list[tuple[str, float, int, bool]] = []
    for candidate in characters:
        if candidate == query:
            continue
        candidate_index = index_by_character.get(candidate)
        candidate_strokes = stroke_counts.get(candidate)
        if candidate_index is None or candidate_strokes is None:
            continue

        stroke_gap = abs(query_strokes - candidate_strokes)
        if stroke_gap > max_stroke_gap:
            continue

        score = float(score_matrix[query_index, candidate_index])
        phonetic_match = phonetic_match_details(query, candidate, phonetic_map)[0]

        pass_condition = score >= threshold
        if use_phonetic:
            # Allow mild relaxation for phonetic relations, but avoid no-signal matches.
            phonetic_floor = max(0.0, threshold - 0.05)
            pass_condition = pass_condition or (phonetic_match and score >= phonetic_floor)
        if not pass_condition:
            continue

        results.append((candidate, score, stroke_gap, phonetic_match))

    results.sort(key=lambda item: (-item[1], item[0]))
    output = []
    for candidate, score, stroke_gap, phonetic_match in results[:top_k]:
        entry: dict[str, Any] = {
            "character": candidate,
            "pinyins": pinyins_for(char_info[candidate]),
            "score": round(score, 4),
            "ssim_score": round(score, 4),
            "stroke_count_difference": stroke_gap,
        }
        if phonetic_match:
            entry["phonetic_match"] = True
        output.append(entry)
    return output


def rank_rule_mode(
    query: str,
    characters: list[str],
    char_info: dict[str, dict[str, Any]],
    glyph_index_by_character: dict[str, int],
    glyph_similarities: torch.Tensor,
    ssim_index_by_character: dict[str, int],
    ssim_scores: Any,
    stroke_counts: dict[str, int],
    phonetic_map: dict[str, str],
    mode: str,
    threshold: float,
    glyph_threshold: Optional[float],
    ssim_threshold: Optional[float],
    max_stroke_gap: int,
    top_k: int,
    use_phonetic: bool,
) -> list[dict[str, Any]]:
    query_glyph_index = glyph_index_by_character.get(query)
    query_ssim_index = ssim_index_by_character.get(query)
    query_strokes = stroke_counts.get(query)
    if query_glyph_index is None or query_ssim_index is None or query_strokes is None:
        return []

    results: list[tuple[str, float, float, float, int, bool]] = []
    for candidate in characters:
        if candidate == query:
            continue

        candidate_glyph_index = glyph_index_by_character.get(candidate)
        candidate_ssim_index = ssim_index_by_character.get(candidate)
        candidate_strokes = stroke_counts.get(candidate)
        if candidate_glyph_index is None or candidate_ssim_index is None or candidate_strokes is None:
            continue

        stroke_gap = abs(query_strokes - candidate_strokes)
        if stroke_gap > max_stroke_gap:
            continue

        glyph_score = float(glyph_similarities[query_glyph_index, candidate_glyph_index].item())
        ssim_score_value = float(ssim_scores[query_ssim_index, candidate_ssim_index])
        phonetic_match, query_phonetic_is_candidate, candidate_phonetic_is_query, shared_phonetic = phonetic_match_details(
            query,
            candidate,
            phonetic_map,
        )

        pass_condition = False
        final_score = max(glyph_score, ssim_score_value)

        if mode == "fusion":
            combined_score = glyph_score + CV_SSIM_WEIGHT * ssim_score_value
            pass_condition = combined_score >= threshold
            final_score = combined_score
        elif mode == "or":
            glyph_pass = glyph_threshold is not None and glyph_score >= glyph_threshold
            ssim_pass = ssim_threshold is not None and ssim_score_value >= ssim_threshold
            pass_condition = glyph_pass or ssim_pass
        elif mode == "intersect":
            glyph_pass = glyph_threshold is None or glyph_score >= glyph_threshold
            ssim_pass = ssim_threshold is None or ssim_score_value >= ssim_threshold
            pass_condition = glyph_pass and ssim_pass
        elif mode == "exp":
            # ----- EXPERIMENT BLOCK START -----
            # Available booleans:
            # - phonetic_match
            # - query_phonetic_is_candidate
            # - candidate_phonetic_is_query
            # - shared_phonetic
            # Available scores:
            # - glyph_score
            # - ssim_score_value
            # Recommended pattern:
            #   ssim > threshold OR (high glyph AND shared_phonetic)
            effective_glyph_threshold = 0.90 if glyph_threshold is None else glyph_threshold
            effective_ssim_threshold = 0.60 if ssim_threshold is None else ssim_threshold
            pass_condition = (ssim_score_value >= effective_ssim_threshold) or (
                glyph_score >= effective_glyph_threshold and shared_phonetic
            )
            # ----- EXPERIMENT BLOCK END -----
        else:
            raise ValueError(f"Unsupported rule mode: {mode}")

        effective_glyph_threshold = 0.90 if glyph_threshold is None else glyph_threshold
        effective_ssim_threshold = 0.60 if ssim_threshold is None else ssim_threshold
        pass_condition = pass_condition or phonetic_override_pass(
            use_phonetic=use_phonetic,
            phonetic_match=phonetic_match,
            glyph_score=glyph_score,
            ssim_score=ssim_score_value,
            glyph_floor=effective_glyph_threshold,
            ssim_floor=effective_ssim_threshold,
        )

        if not pass_condition:
            continue

        results.append((candidate, final_score, glyph_score, ssim_score_value, stroke_gap, phonetic_match))

    results.sort(key=lambda item: (-item[1], -item[2], -item[3], item[0]))
    output = []
    for candidate, final_score, glyph_score, ssim_score_value, stroke_gap, phonetic_match in results[:top_k]:
        entry: dict[str, Any] = {
            "character": candidate,
            "pinyins": pinyins_for(char_info[candidate]),
            "score": round(final_score, 4),
            "glyph_score": round(glyph_score, 4),
            "ssim_score": round(ssim_score_value, 4),
            "stroke_count_difference": stroke_gap,
        }
        if phonetic_match:
            entry["phonetic_match"] = True

        if mode == "fusion":
            entry["fusion_score"] = round(final_score, 4)
        elif mode == "or":
            entry["or_score"] = round(final_score, 4)
        elif mode == "exp":
            entry["exp_score"] = round(final_score, 4)
        output.append(entry)

    return output


def append_phonetic_entries(
    query: str,
    matches: list[dict[str, Any]],
    characters: list[str],
    char_info: dict[str, dict[str, Any]],
    phonetic_map: dict[str, str],
    top_k: int,
) -> list[dict[str, Any]]:
    existing = {
        entry.get("character")
        for entry in matches
        if isinstance(entry, dict) and isinstance(entry.get("character"), str)
    }

    extras = []
    for candidate in characters:
        if candidate == query or candidate in existing:
            continue
        if not phonetic_match_details(query, candidate, phonetic_map)[0]:
            continue
        extras.append(
            {
                "character": candidate,
                "pinyins": pinyins_for(char_info[candidate]),
                "method": "phonetic",
            }
        )

    extras.sort(key=lambda item: item["character"])
    remaining = max(0, top_k - len(matches))
    if remaining == 0:
        return matches
    return matches + extras[:remaining]


def normalize_group_method_shape(similar_visual_chars: Any) -> None:
    if not isinstance(similar_visual_chars, list):
        return

    for group in similar_visual_chars:
        if not isinstance(group, dict):
            continue
        if group.get("method") != "phonetic":
            continue

        candidates = group.get("characters")
        if not isinstance(candidates, list):
            continue

        has_phonetic_candidate = any(
            isinstance(candidate, dict) and candidate.get("method") == "phonetic"
            for candidate in candidates
        )
        if has_phonetic_candidate:
            group.pop("method", None)


def remove_self_candidates(similar_visual_chars: Any, query: str) -> None:
    if not isinstance(similar_visual_chars, list):
        return

    for group in similar_visual_chars:
        if not isinstance(group, dict):
            continue

        candidates = group.get("characters")
        if not isinstance(candidates, list):
            continue

        filtered = []
        for candidate in candidates:
            if not isinstance(candidate, dict):
                filtered.append(candidate)
                continue
            if candidate.get("character") == query:
                continue
            filtered.append(candidate)
        group["characters"] = filtered


def append_decomposition_entries(
    character_info: dict[str, dict[str, Any]],
    pairs_path: Path,
) -> tuple[int, int]:
    with pairs_path.open(encoding="utf-8", newline="") as file:
        pairs = list(csv.DictReader(file))

    if len(pairs) != 20:
        raise ValueError(f"Expected 20 decomposition pairs in {pairs_path}, found {len(pairs)}.")

    added_characters = 0
    added_matches = 0
    for pair in pairs:
        left = pair.get("character_1")
        right = pair.get("character_2")
        if not isinstance(left, str) or not isinstance(right, str):
            raise ValueError(f"Invalid decomposition pair in {pairs_path}: {pair}")

        for query, candidate in ((left, right), (right, left)):
            info = character_info.get(query)
            candidate_info = character_info.get(candidate)
            if not isinstance(info, dict) or not isinstance(candidate_info, dict):
                continue

            groups = info.setdefault("similar_visual_chars", [])
            if not isinstance(groups, list):
                raise ValueError(f"similar_visual_chars for '{query}' must be a list.")

            existing_characters = {
                entry.get("character")
                for group in groups
                if isinstance(group, dict) and isinstance(group.get("characters"), list)
                for entry in group["characters"]
                if isinstance(entry, dict) and isinstance(entry.get("character"), str)
            }
            if candidate in existing_characters:
                continue

            if not groups or not isinstance(groups[0], dict) or not isinstance(groups[0].get("characters"), list):
                groups.insert(0, {"characters": []})

            groups[0]["characters"].append(
                {
                    "character": candidate,
                    "pinyins": pinyins_for(candidate_info),
                    "method": decomposition_method,
                }
            )
            added_characters += 1
            added_matches += 1

    return added_characters, added_matches


def update_character_info(
    character_info: dict[str, dict[str, Any]],
    method: str,
    threshold: Optional[float],
    max_stroke_gap: int,
    top_k: int,
    dictionary_records: dict[str, dict[str, Any]],
    glyph_metric: str,
    glyph_font: Optional[str],
    glyph_device: str,
    ssim_cache_path: Path,
    refresh_ssim_cache: bool,
    only_character: Optional[str],
    include_phonetic: bool,
    use_phonetic: bool,
    ssim_size: int = CANVAS_SIZE,
    glyph_threshold: Optional[float] = None,
    ssim_threshold: Optional[float] = None,
) -> tuple[int, int]:
    characters = sorted(character_info)
    stroke_counts = build_stroke_counts(dictionary_records)
    phonetic_map = build_phonetic_map(dictionary_records, characters)

    glyph_similarities: Optional[torch.Tensor] = None
    glyph_index_by_character: dict[str, int] = {}
    ssim_scores: Any = None
    ssim_index_by_character: dict[str, int] = {}

    need_glyph = method in ("glyph", "fusion", "or", "intersect", "exp")
    need_ssim = method in ("ssim", "fusion", "or", "intersect", "exp")

    font_path = resolve_font_path(glyph_font)

    if need_glyph:
        device = resolve_torch_device(glyph_device)
        log(f"Glyph setup: building embeddings for {len(characters)} characters on {device.type}")
        embeddings = build_embeddings(characters, font_path, device)
        glyph_similarities = similarity_matrix(embeddings, glyph_metric)
        glyph_index_by_character = {character: index for index, character in enumerate(characters)}
        log("Glyph setup: similarity matrix ready")

    if need_ssim:
        log(f"SSIM setup: preparing cached score matrix for {len(characters)} characters")
        ssim_scores, ssim_index_by_character = load_or_build_ssim_cache(
            cache_path=ssim_cache_path,
            refresh=refresh_ssim_cache,
            characters=characters,
            font_path=font_path,
            ssim_size=ssim_size,
        )

    targets = [only_character] if only_character else characters
    updated = 0
    total_matches = 0
    started = time.time()
    progress_every = 25 if len(targets) > 100 else 10

    for index, query in enumerate(targets, start=1):
        info = character_info.get(query)
        if not isinstance(info, dict):
            continue

        normalize_group_method_shape(info.get("similar_visual_chars"))
        remove_self_candidates(info.get("similar_visual_chars"), query)

        if method == "phonetic":
            matches = rank_phonetic(query, characters, character_info, phonetic_map, top_k)
        elif method == "glyph":
            assert glyph_similarities is not None
            matches = rank_glyph(
                query,
                characters,
                character_info,
                glyph_index_by_character,
                glyph_similarities,
                stroke_counts,
                float(threshold),
                max_stroke_gap,
                top_k,
                phonetic_map,
                use_phonetic,
            )
        elif method == "ssim":
            assert ssim_scores is not None
            matches = rank_ssim(
                query,
                characters,
                character_info,
                ssim_index_by_character,
                ssim_scores,
                stroke_counts,
                float(threshold),
                max_stroke_gap,
                top_k,
                phonetic_map,
                use_phonetic,
            )
        elif method in ("fusion", "or", "intersect", "exp"):
            assert glyph_similarities is not None and ssim_scores is not None
            matches = rank_rule_mode(
                query,
                characters,
                character_info,
                glyph_index_by_character,
                glyph_similarities,
                ssim_index_by_character,
                ssim_scores,
                stroke_counts,
                phonetic_map,
                method,
                float(threshold) if threshold is not None else 0.0,
                glyph_threshold,
                ssim_threshold,
                max_stroke_gap,
                top_k,
                use_phonetic,
            )
        else:
            raise ValueError(f"Unsupported method: {method}")

        if include_phonetic and method != "phonetic":
            matches = append_phonetic_entries(
                query=query,
                matches=matches,
                characters=characters,
                char_info=character_info,
                phonetic_map=phonetic_map,
                top_k=top_k,
            )

        character_info[query]["similar_visual_chars"] = [{"characters": matches}] if matches else []
        updated += 1
        total_matches += len(matches)

        if index % progress_every == 0 or index == len(targets):
            elapsed = time.time() - started
            rate = index / elapsed if elapsed > 0 else 0.0
            eta_seconds = (len(targets) - index) / rate if rate > 0 else 0.0
            log(
                f"Progress {index}/{len(targets)} | updated={updated} | "
                f"matches={total_matches} | elapsed={elapsed:.1f}s | eta={eta_seconds:.1f}s"
            )

    return updated, total_matches


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--method",
        choices=("glyph", "ssim", "fusion", "or", "intersect", "exp", "phonetic"),
        required=True,
        help="Similarity method to run.",
    )
    parser.add_argument("--threshold", type=float, help="Minimum score threshold for glyph/ssim/fusion methods.")
    parser.add_argument("--max-stroke-gap", type=int, default=2, help="Maximum stroke count difference (default: 2).")
    parser.add_argument("--top-k", type=int, default=20, help="Number of results to keep per character (default: 20).")
    parser.add_argument("--character", help="Update one character only.")
    parser.add_argument("--dry-run", action="store_true", help="Compute results without writing character_info.json.")
    parser.add_argument(
        "--include-decomposition",
        action="store_true",
        help="Append character pairs with one decomposition difference.",
    )

    parser.add_argument("--character-info", type=Path, default=DEFAULT_CHARACTER_INFO_PATH, help="Path to character_info.json.")
    parser.add_argument("--dictionary", type=Path, default=DEFAULT_DICTIONARY_PATH, help="Path to dictionary.json.")

    parser.add_argument(
        "--glyph-metric",
        choices=("cosine", "euclidean", "euclidian", "tanh"),
        default=glyph_method,
        help="Glyph metric (used by glyph/fusion/or/intersect/exp).",
    )
    parser.add_argument("--glyph-font", help="Font path for glyph rendering.")
    parser.add_argument("--glyph-device", choices=("auto", "cpu", "mps"), default="auto", help="Torch device for glyph embedding.")
    parser.add_argument("--ssim-size", type=int, default=64, help="Rendered glyph image size for SSIM (default: 64).")
    parser.add_argument("--ssim-cache", type=Path, default=DEFAULT_SSIM_CACHE, help="Cache file for pairwise SSIM score matrix.")
    parser.add_argument("--refresh-ssim-cache", action="store_true", help="Rebuild SSIM score cache even if one already exists.")

    parser.add_argument("--glyph-threshold", type=float, help="OR/Intersect mode: glyph threshold (0-1).")
    parser.add_argument("--ssim-threshold", type=float, help="OR/Intersect mode: SSIM threshold (0-1).")

    parser.add_argument(
        "--include-phonetic",
        action="store_true",
        default=include_phonetic_default,
        help="Append extra phonetic-only matches (renamed from include-naive).",
    )
    parser.add_argument(
        "--include-naive",
        action="store_true",
        help="Deprecated alias for --include-phonetic.",
    )
    parser.add_argument(
        "--use-phonetic",
        action="store_true",
        default=use_phonetic_default,
        help="Embed 'or phonetic' directly in pass condition for CV methods.",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    try:
        args.glyph_metric = normalize_glyph_metric(args.glyph_metric)
    except ValueError as error:
        parser.error(str(error))

    if args.threshold is not None:
        if args.method == "fusion":
            if not -2.5 <= args.threshold <= 2.5:
                parser.error("--threshold must be between -2.5 and 2.5 for fusion method (glyph_score + 1.5*ssim_score).")
        elif not 0 <= args.threshold <= 1:
            parser.error("--threshold must be between 0 and 1.")

    if args.glyph_threshold is not None and not 0 <= args.glyph_threshold <= 1:
        parser.error("--glyph-threshold must be between 0 and 1.")
    if args.ssim_threshold is not None and not 0 <= args.ssim_threshold <= 1:
        parser.error("--ssim-threshold must be between 0 and 1.")

    if args.max_stroke_gap < 0:
        parser.error("--max-stroke-gap must be non-negative.")
    if args.top_k <= 0:
        parser.error("--top-k must be positive.")
    if args.ssim_size <= 0:
        parser.error("--ssim-size must be positive.")

    if args.method in ("glyph", "ssim", "fusion") and args.threshold is None:
        parser.error("--threshold is required for glyph, ssim, and fusion methods.")

    if args.method in ("or", "intersect"):
        if args.glyph_threshold is None and args.ssim_threshold is None:
            parser.error(f"{args.method} requires at least one of --glyph-threshold or --ssim-threshold.")

    if args.method == "exp":
        if args.glyph_threshold is None and args.ssim_threshold is None:
            parser.error("exp requires at least one of --glyph-threshold or --ssim-threshold.")

    include_phonetic = args.include_phonetic or args.include_naive

    try:
        character_info = json.loads(args.character_info.read_text(encoding="utf-8"))
        dictionary_records = load_dictionary_records(args.dictionary)
    except (OSError, json.JSONDecodeError, ValueError) as error:
        log(f"ERROR: {error}")
        return 1

    log(
        f"Starting method={args.method}, threshold={args.threshold}, max_stroke_gap={args.max_stroke_gap}, "
        f"top_k={args.top_k}, target={args.character or 'ALL'}, dry_run={args.dry_run}, "
        f"rule_thresholds=(glyph:{args.glyph_threshold}, ssim:{args.ssim_threshold}), "
        f"include_phonetic={include_phonetic}, include_decomposition={args.include_decomposition}, "
        f"use_phonetic={args.use_phonetic}"
    )

    try:
        updated, total_matches = update_character_info(
            character_info=character_info,
            method=args.method,
            threshold=args.threshold,
            max_stroke_gap=args.max_stroke_gap,
            top_k=args.top_k,
            dictionary_records=dictionary_records,
            glyph_metric=args.glyph_metric,
            glyph_font=args.glyph_font,
            glyph_device=args.glyph_device,
            ssim_cache_path=args.ssim_cache,
            refresh_ssim_cache=args.refresh_ssim_cache,
            only_character=args.character,
            include_phonetic=include_phonetic,
            use_phonetic=args.use_phonetic,
            ssim_size=args.ssim_size,
            glyph_threshold=args.glyph_threshold,
            ssim_threshold=args.ssim_threshold,
        )
    except Exception as error:
        log(f"ERROR: {error}")
        return 1

    if args.include_decomposition:
        try:
            decomposition_updated, decomposition_matches = append_decomposition_entries(
                character_info,
                DEFAULT_DECOMPOSITION_PAIRS_PATH,
            )
        except (OSError, ValueError) as error:
            log(f"ERROR: {error}")
            return 1
        updated += decomposition_updated
        total_matches += decomposition_matches
        log(
            f"Added {decomposition_matches} decomposition matches across "
            f"{decomposition_updated} character lists."
        )

    if not args.dry_run:
        args.character_info.write_text(json.dumps(character_info, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    action = "Would update" if args.dry_run else "Updated"
    log(f"{action} {updated} entries, {total_matches} directed matches.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
