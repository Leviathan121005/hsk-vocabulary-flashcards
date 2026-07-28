#!/usr/bin/env python3
"""Detect visually similar Chinese characters with four methods.

This script updates `public/character_info.json` by replacing `similar_visual_chars`
with results from exactly one method per run:
- glyph: MobileNet embedding similarity
- ssim: structural similarity over rendered glyph images
- fusion: combined score from glyph + weighted ssim
- intersect: strict agreement mode across both expert thresholds

Examples:
```bash
# Format
python3 scrap/detect_similarity.py --method <glyph|ssim|fusion|intersect> --threshold <float> --max-stroke-gap <int>

# Glyph (MobileNet)
python3 scrap/detect_similarity.py --method glyph --threshold 0.9 --max-stroke-gap 2

# SSIM
python3 scrap/detect_similarity.py --method ssim --threshold 0.6 --max-stroke-gap 3

# Fusion (combined Glyph + weighted SSIM)
python3 scrap/detect_similarity.py --method fusion --threshold 1.75 --max-stroke-gap 4

# Intersect (strict threshold agreement)
python3 scrap/detect_similarity.py --method intersect --glyph-threshold 0.90 --ssim-threshold 0.60 --max-stroke-gap 4

# Single character dry-run
python3 scrap/detect_similarity.py --method glyph --threshold 0.90 --max-stroke-gap 2 --character 好 --dry-run
```

Every method applies:

1. Score threshold filter
2. Stroke-count difference filter

Each output candidate includes:

- `score`
- `stroke_count_difference`
- Method-specific score field (`glyph_score`, `ssim_score`, `fusion_score`):

Optional method-specific settings:

- Glyph: `--glyph-metric cosine|euclidean|tanh`, `--glyph-font`, `--glyph-device`
- SSIM: `--ssim-size`, `--ssim-cache`, `--refresh-ssim-cache`
- Fusion: uses combined score and supports `--threshold` in `[-2.5, 2.5]`
- Intersect: threshold flags `--glyph-threshold` and `--ssim-threshold`
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any, Optional

import torch
from PIL import Image, ImageDraw, ImageFont
from torchvision.models import MobileNet_V3_Small_Weights, mobilenet_v3_small

try:
    from skimage.metrics import structural_similarity as skimage_ssim
except Exception:  # Optional dependency
    skimage_ssim = None


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CHARACTER_INFO_PATH = REPO_ROOT / "public" / "character_info.json"
DEFAULT_DICTIONARY_PATH = REPO_ROOT / "scrap" / "dictionary.json"
DEFAULT_SSIM_CACHE = REPO_ROOT / "scrap" / "ssim_cache.npz"

DEFAULT_FONT_CANDIDATES = (
    Path("/System/Library/Fonts/PingFang.ttc"),
    Path("/System/Library/Fonts/STHeiti Medium.ttc"),
)
CANVAS_SIZE = 64
CV_SSIM_WEIGHT = 1.5


def log(message: str) -> None:
    print(f"[detect-similarity] {message}", flush=True)


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


def pinyins_for(info: dict[str, Any]) -> list[str]:
    pinyins = [info.get("sample_pinyin", ""), *(info.get("other_pinyins", []) or [])]
    return [pinyin for pinyin in pinyins if pinyin]


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
) -> list[dict[str, Any]]:
    query_index = index_by_character.get(query)
    query_strokes = stroke_counts.get(query)
    if query_index is None or query_strokes is None:
        return []

    row = similarities[query_index]
    results: list[tuple[str, float, int]] = []
    for candidate_index, score_tensor in enumerate(row):
        if candidate_index == query_index:
            continue
        score = float(score_tensor.item())
        if score < threshold:
            continue
        candidate = characters[candidate_index]
        candidate_strokes = stroke_counts.get(candidate)
        if candidate_strokes is None:
            continue
        stroke_gap = abs(query_strokes - candidate_strokes)
        if stroke_gap > max_stroke_gap:
            continue
        results.append((candidate, score, stroke_gap))

    results.sort(key=lambda item: (-item[1], item[0]))
    return [
        {
            "character": candidate,
            "pinyins": pinyins_for(char_info[candidate]),
            "score": round(score, 4),
            "glyph_score": round(score, 4),
            "stroke_count_difference": stroke_gap,
        }
        for candidate, score, stroke_gap in results[:top_k]
    ]


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
) -> list[dict[str, Any]]:
    query_index = index_by_character.get(query)
    query_strokes = stroke_counts.get(query)
    if query_index is None or query_strokes is None:
        return []

    results: list[tuple[str, float, int]] = []
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
        if score < threshold:
            continue

        results.append((candidate, score, stroke_gap))

    results.sort(key=lambda item: (-item[1], item[0]))
    return [
        {
            "character": candidate,
            "pinyins": pinyins_for(char_info[candidate]),
            "score": round(score, 4),
            "ssim_score": round(score, 4),
            "stroke_count_difference": stroke_gap,
        }
        for candidate, score, stroke_gap in results[:top_k]
    ]


def rank_fusion(
    query: str,
    characters: list[str],
    char_info: dict[str, dict[str, Any]],
    glyph_index_by_character: dict[str, int],
    glyph_similarities: torch.Tensor,
    ssim_index_by_character: dict[str, int],
    ssim_scores: Any,
    stroke_counts: dict[str, int],
    threshold: float,
    max_stroke_gap: int,
    top_k: int,
) -> list[dict[str, Any]]:
    """Fusion mode: combined score from glyph + weighted ssim."""

    query_glyph_index = glyph_index_by_character.get(query)
    query_ssim_index = ssim_index_by_character.get(query)
    query_strokes = stroke_counts.get(query)
    if (
        query_glyph_index is None
        or query_ssim_index is None
        or query_strokes is None
    ):
        return []

    results: list[tuple[str, float, float, float, int]] = []
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
        combined_score = glyph_score + CV_SSIM_WEIGHT * ssim_score_value
        if combined_score < threshold:
            continue

        results.append((candidate, combined_score, glyph_score, ssim_score_value, stroke_gap))

    results.sort(key=lambda item: (-item[1], -item[2], -item[3], item[0]))
    return [
        {
            "character": candidate,
            "pinyins": pinyins_for(char_info[candidate]),
            "score": round(combined_score, 4),
            "fusion_score": round(combined_score, 4),
            "glyph_score": round(glyph_score, 4),
            "ssim_score": round(ssim_score_value, 4),
            "stroke_count_difference": stroke_gap,
        }
        for candidate, combined_score, glyph_score, ssim_score_value, stroke_gap in results[:top_k]
    ]


def rank_intersect(
    query: str,
    characters: list[str],
    char_info: dict[str, dict[str, Any]],
    glyph_index_by_character: dict[str, int],
    glyph_similarities: torch.Tensor,
    ssim_index_by_character: dict[str, int],
    ssim_scores: Any,
    stroke_counts: dict[str, int],
    glyph_threshold: Optional[float],
    ssim_threshold: Optional[float],
    max_stroke_gap: int,
    top_k: int,
) -> list[dict[str, Any]]:
    """Intersect mode: candidates must pass all provided expert thresholds."""

    use_glyph = glyph_threshold is not None
    use_ssim = ssim_threshold is not None
    if not (use_glyph or use_ssim):
        return []

    query_glyph_index = glyph_index_by_character.get(query) if use_glyph else None
    query_ssim_index = ssim_index_by_character.get(query) if use_ssim else None
    query_strokes = stroke_counts.get(query)
    if query_strokes is None:
        return []
    if use_glyph and query_glyph_index is None:
        return []
    if use_ssim and query_ssim_index is None:
        return []

    if use_glyph:
        row = glyph_similarities[query_glyph_index]
        candidate_indices = torch.nonzero(row >= glyph_threshold, as_tuple=False).flatten().tolist()
        candidate_characters = [characters[index] for index in candidate_indices if index != query_glyph_index]
    else:
        candidate_characters = [candidate for candidate in characters if candidate != query]

    results: list[tuple[str, float, float, float, int]] = []

    for candidate in candidate_characters:
        candidate_strokes = stroke_counts.get(candidate)
        if candidate_strokes is None:
            continue

        stroke_gap = abs(query_strokes - candidate_strokes)
        if stroke_gap > max_stroke_gap:
            continue

        glyph_score = 0.0
        ssim_score_value = 0.0

        if use_glyph:
            candidate_glyph_index = glyph_index_by_character.get(candidate)
            if candidate_glyph_index is None:
                continue
            glyph_score = float(glyph_similarities[query_glyph_index, candidate_glyph_index].item())
            if glyph_score < glyph_threshold:
                continue

        if use_ssim:
            candidate_ssim_index = ssim_index_by_character.get(candidate)
            if candidate_ssim_index is None:
                continue
            ssim_score_value = float(ssim_scores[query_ssim_index, candidate_ssim_index])
            if ssim_score_value < ssim_threshold:
                continue

        if use_glyph and use_ssim:
            final_score = (glyph_score + ssim_score_value) / 2.0
        elif use_glyph:
            final_score = glyph_score
        else:
            final_score = ssim_score_value

        results.append((candidate, final_score, glyph_score, ssim_score_value, stroke_gap))

    results.sort(key=lambda item: (-item[1], item[0]))
    return [
        {
            "character": candidate,
            "pinyins": pinyins_for(char_info[candidate]),
            "score": round(final_score, 4),
            "glyph_score": round(glyph_score, 4) if use_glyph else None,
            "ssim_score": round(ssim_score_value, 4) if use_ssim else None,
            "stroke_count_difference": stroke_gap,
        }
        for candidate, final_score, glyph_score, ssim_score_value, stroke_gap in results[:top_k]
    ]


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
    ssim_size: int = CANVAS_SIZE,
    glyph_threshold: Optional[float] = None,
    ssim_threshold: Optional[float] = None,
) -> tuple[int, int]:
    characters = sorted(character_info)
    stroke_counts = build_stroke_counts(dictionary_records)

    glyph_similarities: Optional[torch.Tensor] = None
    glyph_index_by_character: dict[str, int] = {}
    ssim_scores: Any = None
    ssim_index_by_character: dict[str, int] = {}

    need_glyph = method in ("glyph", "fusion", "intersect")
    need_ssim = method in ("ssim", "fusion", "intersect")

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
        if query not in character_info:
            continue

        if method == "glyph":
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
            )
        elif method == "fusion":
            assert glyph_similarities is not None and ssim_scores is not None
            matches = rank_fusion(
                query,
                characters,
                character_info,
                glyph_index_by_character,
                glyph_similarities,
                ssim_index_by_character,
                ssim_scores,
                stroke_counts,
                float(threshold),
                max_stroke_gap,
                top_k,
            )
        else:
            assert glyph_similarities is not None and ssim_scores is not None
            matches = rank_intersect(
                query,
                characters,
                character_info,
                glyph_index_by_character,
                glyph_similarities,
                ssim_index_by_character,
                ssim_scores,
                stroke_counts,
                glyph_threshold,
                ssim_threshold,
                max_stroke_gap,
                top_k,
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
    parser.add_argument("--method", choices=("glyph", "ssim", "fusion", "intersect"), required=True, help="Similarity method to run.")
    parser.add_argument("--threshold", type=float, help="Minimum score threshold for glyph/ssim/fusion methods.")
    parser.add_argument("--max-stroke-gap", type=int, default=2, help="Maximum stroke count difference (default: 2).")
    parser.add_argument("--top-k", type=int, default=20, help="Number of results to keep per character (default: 20).")
    parser.add_argument("--character", help="Update one character only.")
    parser.add_argument("--dry-run", action="store_true", help="Compute results without writing character_info.json.")

    parser.add_argument("--character-info", type=Path, default=DEFAULT_CHARACTER_INFO_PATH, help="Path to character_info.json.")
    parser.add_argument("--dictionary", type=Path, default=DEFAULT_DICTIONARY_PATH, help="Path to dictionary.json.")

    parser.add_argument("--glyph-metric", choices=("cosine", "euclidean", "tanh"), default="cosine", help="Glyph metric (used by glyph/fusion/intersect).")
    parser.add_argument("--glyph-font", help="Font path for glyph rendering.")
    parser.add_argument("--glyph-device", choices=("auto", "cpu", "mps"), default="auto", help="Torch device for glyph embedding.")
    parser.add_argument("--ssim-size", type=int, default=64, help="Rendered glyph image size for SSIM (default: 64).")
    parser.add_argument("--ssim-cache", type=Path, default=DEFAULT_SSIM_CACHE, help="Cache file for pairwise SSIM score matrix.")
    parser.add_argument("--refresh-ssim-cache", action="store_true", help="Rebuild SSIM score cache even if one already exists.")

    parser.add_argument("--glyph-threshold", type=float, help="Intersect mode: glyph threshold (0-1).")
    parser.add_argument("--ssim-threshold", type=float, help="Intersect mode: SSIM threshold (0-1).")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

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

    if args.method == "intersect":
        if args.glyph_threshold is None and args.ssim_threshold is None:
            parser.error("Intersect requires at least one of --glyph-threshold or --ssim-threshold.")

    try:
        character_info = json.loads(args.character_info.read_text(encoding="utf-8"))
        dictionary_records = load_dictionary_records(args.dictionary)
    except (OSError, json.JSONDecodeError, ValueError) as error:
        log(f"ERROR: {error}")
        return 1

    log(
        f"Starting method={args.method}, threshold={args.threshold}, max_stroke_gap={args.max_stroke_gap}, "
        f"top_k={args.top_k}, target={args.character or 'ALL'}, dry_run={args.dry_run}, "
        f"intersect_thresholds=(glyph:{args.glyph_threshold}, ssim:{args.ssim_threshold})"
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
            ssim_size=args.ssim_size,
            glyph_threshold=args.glyph_threshold,
            ssim_threshold=args.ssim_threshold,
        )
    except Exception as error:
        log(f"ERROR: {error}")
        return 1

    if not args.dry_run:
        args.character_info.write_text(json.dumps(character_info, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    action = "Would update" if args.dry_run else "Updated"
    log(f"{action} {updated} entries, {total_matches} directed matches.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
