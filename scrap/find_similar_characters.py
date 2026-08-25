#!/usr/bin/env python3
"""Find similar Chinese characters with a layered CV/semantic design.

Pipeline model:
1) CV layer
     - `--method glyph` or `--method ssim` (mutually exclusive direct method)
2) Semantic layer (optional append)
     - `--include-phonetic`
     - `--include-decomposition`
     - Can enable none, one, or both include flags
    - In `exp`, include flags still append semantic pairs regardless of CV pass
3) Experimental mode
     - `--method exp` always computes both glyph and ssim scores
    - Optional semantic booleans for experiment metadata:
         - `--use-phonetic`
         - `--use-decomposition`

Decomposition matching rule:
1) character exists in both character_info.json and dictionary.json, AND
2) for decomposition length >= 4: decompositions have equal length and differ at exactly one position, AND
3) for decomposition length == 3:
    - structure operator does not need to match
     - if both characters share the same radical at the same IDS component position,
          compare the other component with Rule 1 glyph threshold
     - if both characters share the same non-radical component at the same IDS
          component position, compare whole-character glyph similarity with Rule 2 threshold
    - separate rule: if a character's non-radical component is itself in
      character_info.json, include that (character, component) pair directly

Phonetic matching rule:
1) query phonetic == candidate character, OR
2) candidate phonetic == query character, OR
3) query and candidate share the same phonetic.

Examples:
    python3 scrap/find_similar_characters.py --method glyph --threshold 0.90 --include-phonetic
    python3 scrap/find_similar_characters.py --method ssim --threshold 0.60 --include-decomposition
    python3 scrap/find_similar_characters.py --method exp --glyph-threshold 0.60 --ssim-threshold 0.95 --use-phonetic --use-decomposition --max-stroke-gap 4

Current:
    python3 scrap/find_similar_characters.py --method exp --ssim-threshold 0.60 --glyph-threshold 0.975 --use-decomposition --max-stroke-gap 4
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
except Exception:
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
# Quick in-file defaults.
glyph_method = "cosine"
include_phonetic_default = False
include_decomposition_default = False
use_phonetic_default = False
use_decomposition_default = False
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


def build_decomposition_map(records: dict[str, dict[str, Any]], characters: list[str]) -> dict[str, str]:
    character_set = set(characters)
    out: dict[str, str] = {}
    for character, record in records.items():
        if character not in character_set:
            continue
        decomposition = record.get("decomposition")
        if isinstance(decomposition, str):
            decomposition = decomposition.strip()
            if len(decomposition) >= 3:
                out[character] = decomposition
    return out


def build_radical_map(records: dict[str, dict[str, Any]], characters: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for character in characters:
        record = records.get(character, {})
        radical = record.get("radical") if isinstance(record, dict) else ""
        out[character] = radical.strip() if isinstance(radical, str) else ""
    return out

decomposition_rule1_glyph_threshold = 0.95
decomposition_rule2_glyph_threshold = 0.915
decomposition_rule3_glyph_threshold = 0.88
decomposition_placeholder_components = {"？", "?"}


def is_valid_decomposition_component(component: str) -> bool:
    if not component or component.isspace():
        return False
    return component not in decomposition_placeholder_components


def parse_len3_decomposition(decomposition: str) -> Optional[tuple[str, str, str]]:
    if len(decomposition) != 3:
        return None
    return decomposition[0], decomposition[1], decomposition[2]


def collect_len3_decomposition_components(decomposition_map: dict[str, str]) -> set[str]:
    components: set[str] = set()
    for decomposition in decomposition_map.values():
        parsed = parse_len3_decomposition(decomposition)
        if parsed is None:
            continue
        _, left_component, right_component = parsed
        if is_valid_decomposition_component(left_component):
            components.add(left_component)
        if is_valid_decomposition_component(right_component):
            components.add(right_component)
    return components


def glyph_similarity_for_symbols(
    left: str,
    right: str,
    glyph_index_by_symbol: dict[str, int],
    glyph_similarities_by_symbol: torch.Tensor,
) -> Optional[float]:
    if left == right:
        return 1.0
    left_index = glyph_index_by_symbol.get(left)
    right_index = glyph_index_by_symbol.get(right)
    if left_index is None or right_index is None:
        return None
    return float(glyph_similarities_by_symbol[left_index, right_index].item())


def decomposition_is_single_change(left: str, right: str) -> bool:
    if len(left) != len(right):
        return False
    return sum(a != b for a, b in zip(left, right)) == 1


def match_rule3_direct_component_pair(
    query: str,
    candidate: str,
    query_left_component: str,
    query_right_component: str,
    query_radical: str,
    character_set: set[str],
    glyph_index_by_symbol: dict[str, int],
    glyph_similarities_by_symbol: torch.Tensor,
    glyph_threshold: float,
) -> tuple[bool, Optional[float], bool]:
    query_non_radical_component: Optional[str] = None
    if query_radical:
        if query_left_component == query_radical and query_right_component != query_radical:
            query_non_radical_component = query_right_component
        elif query_right_component == query_radical and query_left_component != query_radical:
            query_non_radical_component = query_left_component

    if not query_non_radical_component:
        return False, None, False
    if not is_valid_decomposition_component(query_non_radical_component):
        return False, None, False
    if query_non_radical_component not in character_set:
        return False, None, False
    if candidate != query_non_radical_component:
        return False, None, False

    pair_score = glyph_similarity_for_symbols(
        query,
        query_non_radical_component,
        glyph_index_by_symbol,
        glyph_similarities_by_symbol,
    )
    if pair_score is None or pair_score < glyph_threshold:
        return False, pair_score, False
    return True, pair_score, True


def decomposition_match_details(
    query: str,
    candidate: str,
    decomposition_map: dict[str, str],
    radical_map: dict[str, str],
    glyph_index_by_symbol: dict[str, int],
    glyph_similarities_by_symbol: torch.Tensor,
    character_set: set[str],
    rule1_glyph_threshold: float = decomposition_rule1_glyph_threshold,
    rule2_glyph_threshold: float = decomposition_rule2_glyph_threshold,
    rule3_glyph_threshold: float = decomposition_rule3_glyph_threshold,
) -> tuple[bool, Optional[float], Optional[str], bool]:
    query_decomp = decomposition_map.get(query)
    candidate_decomp = decomposition_map.get(candidate)
    if not query_decomp or not candidate_decomp:
        return False, None, None, False

    if len(query_decomp) >= 4 and len(query_decomp) == len(candidate_decomp):
        is_match = decomposition_is_single_change(query_decomp, candidate_decomp)
        return is_match, None, ("length_ge_4_single_change" if is_match else None), False

    query_len3 = parse_len3_decomposition(query_decomp)
    candidate_len3 = parse_len3_decomposition(candidate_decomp)
    if query_len3 is None or candidate_len3 is None:
        return False, None, None, False

    _, query_left_component, query_right_component = query_len3
    _, candidate_left_component, candidate_right_component = candidate_len3

    query_components = (query_left_component, query_right_component)
    candidate_components = (candidate_left_component, candidate_right_component)
    query_radical = radical_map.get(query, "")
    candidate_radical = radical_map.get(candidate, "")

    # Rule 3 (separate idea): directly pair the query character with its
    # non-radical component when that component is also a character in
    # character_info.json, and the pair passes Rule 3 glyph threshold.
    is_direct_pair, direct_pair_score, component_in_character_info = match_rule3_direct_component_pair(
        query=query,
        candidate=candidate,
        query_left_component=query_left_component,
        query_right_component=query_right_component,
        query_radical=query_radical,
        character_set=character_set,
        glyph_index_by_symbol=glyph_index_by_symbol,
        glyph_similarities_by_symbol=glyph_similarities_by_symbol,
        glyph_threshold=rule3_glyph_threshold,
    )
    if is_direct_pair:
        return True, direct_pair_score, "length_3_direct_component_pair", component_in_character_info

    # Rule 1: same radical at the same IDS component position, then compare
    # glyph similarity on the remaining component using rule1_glyph_threshold.
    if query_radical and candidate_radical and query_radical == candidate_radical:
        for position in (0, 1):
            if query_components[position] != query_radical:
                continue
            if candidate_components[position] != candidate_radical:
                continue

            other_position = 1 - position
            query_other_component = query_components[other_position]
            candidate_other_component = candidate_components[other_position]
            if not is_valid_decomposition_component(query_other_component):
                continue
            if not is_valid_decomposition_component(candidate_other_component):
                continue
            if query_other_component == candidate_other_component:
                continue

            component_score = glyph_similarity_for_symbols(
                query_other_component,
                candidate_other_component,
                glyph_index_by_symbol,
                glyph_similarities_by_symbol,
            )
            if component_score is not None and component_score >= rule1_glyph_threshold:
                return True, component_score, "length_3_rule_1_component", False

    # Rule 2: same non-radical component at the same IDS component position,
    # then compare glyph similarity on the whole character using
    # rule2_glyph_threshold.
    for position in (0, 1):
        shared_component = query_components[position]
        if not is_valid_decomposition_component(shared_component):
            continue
        if shared_component != candidate_components[position]:
            continue
        if shared_component == query_radical or shared_component == candidate_radical:
            continue

        whole_score = glyph_similarity_for_symbols(
            query,
            candidate,
            glyph_index_by_symbol,
            glyph_similarities_by_symbol,
        )
        if whole_score is not None and whole_score >= rule2_glyph_threshold:
            return True, whole_score, "length_3_rule_2_whole", False

    return False, None, None, False


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


def rank_glyph(
    query: str,
    characters: list[str],
    char_info: dict[str, dict[str, Any]],
    glyph_index_by_symbol: dict[str, int],
    glyph_similarities_by_symbol: torch.Tensor,
    stroke_counts: dict[str, int],
    threshold: float,
    max_stroke_gap: int,
    phonetic_map: dict[str, str],
    use_phonetic: bool,
) -> list[dict[str, Any]]:
    query_strokes = stroke_counts.get(query)
    if query_strokes is None:
        return []

    results: list[tuple[str, float, int, bool]] = []
    for candidate in characters:
        if candidate == query:
            continue
        score = glyph_similarity_for_symbols(
            query,
            candidate,
            glyph_index_by_symbol,
            glyph_similarities_by_symbol,
        )
        if score is None:
            continue

        candidate_strokes = stroke_counts.get(candidate)
        if candidate_strokes is None:
            continue
        stroke_gap = abs(query_strokes - candidate_strokes)
        if stroke_gap > max_stroke_gap:
            continue

        phonetic_match = use_phonetic and phonetic_match_details(query, candidate, phonetic_map)[0]
        pass_condition = score >= threshold
        if not pass_condition:
            continue

        results.append((candidate, score, stroke_gap, phonetic_match))

    results.sort(key=lambda item: (-item[1], item[0]))
    output = []
    for candidate, score, stroke_gap, phonetic_match in results:
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
        phonetic_match = use_phonetic and phonetic_match_details(query, candidate, phonetic_map)[0]

        pass_condition = score >= threshold
        if not pass_condition:
            continue

        results.append((candidate, score, stroke_gap, phonetic_match))

    results.sort(key=lambda item: (-item[1], item[0]))
    output = []
    for candidate, score, stroke_gap, phonetic_match in results:
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


def rank_exp(
    query: str,
    characters: list[str],
    char_info: dict[str, dict[str, Any]],
    ssim_index_by_character: dict[str, int],
    ssim_scores: Any,
    stroke_counts: dict[str, int],
    phonetic_map: dict[str, str],
    decomposition_map: dict[str, str],
    radical_map: dict[str, str],
    glyph_index_by_symbol: dict[str, int],
    glyph_similarities_by_symbol: torch.Tensor,
    character_set: set[str],
    glyph_threshold: Optional[float],
    ssim_threshold: Optional[float],
    max_stroke_gap: int,
    use_phonetic: bool,
    use_decomposition: bool,
) -> list[dict[str, Any]]:
    query_ssim_index = ssim_index_by_character.get(query)
    query_strokes = stroke_counts.get(query)
    if query_ssim_index is None or query_strokes is None:
        return []

    results: list[tuple[str, float, float, int, bool, bool, Optional[float], bool]] = []
    for candidate in characters:
        if candidate == query:
            continue

        candidate_ssim_index = ssim_index_by_character.get(candidate)
        candidate_strokes = stroke_counts.get(candidate)
        if candidate_ssim_index is None or candidate_strokes is None:
            continue

        stroke_gap = abs(query_strokes - candidate_strokes)
        if stroke_gap > max_stroke_gap:
            continue

        glyph_score_raw = glyph_similarity_for_symbols(
            query,
            candidate,
            glyph_index_by_symbol,
            glyph_similarities_by_symbol,
        )
        if glyph_score_raw is None:
            continue
        glyph_score = float(glyph_score_raw)
        ssim_score_value = float(ssim_scores[query_ssim_index, candidate_ssim_index])

        phonetic_relation = None
        if use_phonetic:
            phonetic_relation = phonetic_match_details(query, candidate, phonetic_map)[0]

        decomposition_relation = None
        decomposition_relation_score: Optional[float] = None
        decomposition_component_in_character_info = False
        if use_decomposition:
            decomposition_relation, decomposition_relation_score, _, decomposition_component_in_character_info = decomposition_match_details(
                query,
                candidate,
                decomposition_map,
                radical_map,
                glyph_index_by_symbol,
                glyph_similarities_by_symbol,
                character_set,
            )

        effective_glyph_threshold = 0.90 if glyph_threshold is None else glyph_threshold
        effective_ssim_threshold = 0.60 if ssim_threshold is None else ssim_threshold

        pass_condition = (ssim_score_value >= effective_ssim_threshold and ssim_score_value + glyph_score >= 1.5) or (glyph_score >= effective_glyph_threshold) or (decomposition_relation)

        if not pass_condition:
            continue

        results.append(
            (
                candidate,
                glyph_score,
                ssim_score_value,
                stroke_gap,
                use_phonetic and phonetic_relation,
                use_decomposition and decomposition_relation,
                decomposition_relation_score,
                decomposition_component_in_character_info,
            )
        )

    results.sort(key=lambda item: (-item[2], -item[1], item[0]))
    output = []
    for candidate, glyph_score, ssim_score_value, stroke_gap, phonetic_hit, decomposition_hit, decomposition_score, component_in_character_info in results:
        entry: dict[str, Any] = {
            "character": candidate,
            "pinyins": pinyins_for(char_info[candidate]),
            "glyph_score": round(glyph_score, 4),
            "ssim_score": round(ssim_score_value, 4),
            "stroke_count_difference": stroke_gap,
        }
        if phonetic_hit:
            entry["phonetic_relation"] = True
        if decomposition_hit:
            entry["decomposition_relation"] = True
            if decomposition_score is not None:
                entry["decomposition_glyph_score"] = round(decomposition_score, 4)
            if component_in_character_info:
                entry["decomposition_component_in_character_info"] = True
        output.append(entry)

    return output


def append_phonetic_entries(
    query: str,
    matches: list[dict[str, Any]],
    characters: list[str],
    char_info: dict[str, dict[str, Any]],
    phonetic_map: dict[str, str],
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
    return matches + extras


def append_decomposition_entries(
    query: str,
    matches: list[dict[str, Any]],
    characters: list[str],
    char_info: dict[str, dict[str, Any]],
    decomposition_map: dict[str, str],
    radical_map: dict[str, str],
    glyph_index_by_symbol: dict[str, int],
    glyph_similarities_by_symbol: torch.Tensor,
    character_set: set[str],
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
        is_match, decomposition_score, _, component_in_character_info = decomposition_match_details(
            query,
            candidate,
            decomposition_map,
            radical_map,
            glyph_index_by_symbol,
            glyph_similarities_by_symbol,
            character_set,
        )
        if not is_match:
            continue
        entry: dict[str, Any] = {
            "character": candidate,
            "pinyins": pinyins_for(char_info[candidate]),
            "method": decomposition_method,
        }
        if decomposition_score is not None:
            entry["decomposition_glyph_score"] = round(decomposition_score, 4)
        if component_in_character_info:
            entry["decomposition_component_in_character_info"] = True
        extras.append(entry)

    extras.sort(key=lambda item: item["character"])
    return matches + extras


def apply_symmetric_direct_component_pairs(
    character_info: dict[str, dict[str, Any]],
    decomposition_map: dict[str, str],
    radical_map: dict[str, str],
    character_set: set[str],
    glyph_index_by_symbol: dict[str, int],
    glyph_similarities_by_symbol: torch.Tensor,
    rule3_threshold: float = decomposition_rule3_glyph_threshold,
) -> int:
    added = 0

    for query in character_set:
        query_decomp = decomposition_map.get(query)
        query_len3 = parse_len3_decomposition(query_decomp or "")
        if query_len3 is None:
            continue

        _, query_left_component, query_right_component = query_len3
        query_radical = radical_map.get(query, "")

        candidate = ""
        if query_radical:
            if query_left_component == query_radical and query_right_component != query_radical:
                candidate = query_right_component
            elif query_right_component == query_radical and query_left_component != query_radical:
                candidate = query_left_component
        if not candidate:
            continue

        is_match, pair_score, _ = match_rule3_direct_component_pair(
            query=query,
            candidate=candidate,
            query_left_component=query_left_component,
            query_right_component=query_right_component,
            query_radical=query_radical,
            character_set=character_set,
            glyph_index_by_symbol=glyph_index_by_symbol,
            glyph_similarities_by_symbol=glyph_similarities_by_symbol,
            glyph_threshold=rule3_threshold,
        )
        if not is_match:
            continue

        for source, target in ((query, candidate), (candidate, query)):
            source_info = character_info.get(source)
            target_info = character_info.get(target)
            if not isinstance(source_info, dict) or not isinstance(target_info, dict):
                continue

            groups = source_info.get("similar_visual_chars")
            if not isinstance(groups, list) or not groups or not isinstance(groups[0], dict) or not isinstance(groups[0].get("characters"), list):
                source_info["similar_visual_chars"] = [{"characters": []}]
                groups = source_info["similar_visual_chars"]

            candidates = groups[0]["characters"]
            if any(isinstance(entry, dict) and entry.get("character") == target for entry in candidates):
                continue

            new_entry: dict[str, Any] = {
                "character": target,
                "pinyins": pinyins_for(target_info),
                "method": decomposition_method,
                "decomposition_component_in_character_info": True,
            }
            if pair_score is not None:
                new_entry["decomposition_glyph_score"] = round(pair_score, 4)
            candidates.append(new_entry)
            candidates.sort(key=lambda item: item.get("character", "") if isinstance(item, dict) else "")
            added += 1

    return added


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


def update_character_info(
    character_info: dict[str, dict[str, Any]],
    method: str,
    threshold: Optional[float],
    max_stroke_gap: int,
    dictionary_records: dict[str, dict[str, Any]],
    glyph_metric: str,
    glyph_font: Optional[str],
    glyph_device: str,
    ssim_cache_path: Path,
    refresh_ssim_cache: bool,
    only_character: Optional[str],
    include_phonetic: bool,
    include_decomposition: bool,
    use_phonetic: bool,
    use_decomposition: bool,
    ssim_size: int = CANVAS_SIZE,
    glyph_threshold: Optional[float] = None,
    ssim_threshold: Optional[float] = None,
) -> tuple[int, int]:
    characters = sorted(character_info)
    character_set = set(characters)
    stroke_counts = build_stroke_counts(dictionary_records)
    phonetic_map = build_phonetic_map(dictionary_records, characters)
    decomposition_map = build_decomposition_map(dictionary_records, characters)
    radical_map = build_radical_map(dictionary_records, characters)

    glyph_similarities_by_symbol: Optional[torch.Tensor] = None
    glyph_index_by_symbol: dict[str, int] = {}
    ssim_scores: Any = None
    ssim_index_by_character: dict[str, int] = {}

    need_decomposition_glyph = include_decomposition or use_decomposition
    need_glyph = method in ("glyph", "exp") or need_decomposition_glyph
    need_ssim = method in ("ssim", "exp")

    font_path = resolve_font_path(glyph_font)

    if need_glyph:
        device = resolve_torch_device(glyph_device)
        glyph_symbols = set(characters)
        if need_decomposition_glyph:
            glyph_symbols.update(collect_len3_decomposition_components(decomposition_map))
        ordered_glyph_symbols = sorted(glyph_symbols)

        log(f"Glyph setup: building embeddings for {len(ordered_glyph_symbols)} symbols on {device.type}")
        embeddings = build_embeddings(ordered_glyph_symbols, font_path, device)
        glyph_similarities_by_symbol = similarity_matrix(embeddings, glyph_metric)
        glyph_index_by_symbol = {symbol: index for index, symbol in enumerate(ordered_glyph_symbols)}
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

        if method == "glyph":
            assert glyph_similarities_by_symbol is not None
            matches = rank_glyph(
                query,
                characters,
                character_info,
                glyph_index_by_symbol,
                glyph_similarities_by_symbol,
                stroke_counts,
                float(threshold),
                max_stroke_gap,
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
                phonetic_map,
                use_phonetic,
            )
        elif method == "exp":
            assert glyph_similarities_by_symbol is not None and ssim_scores is not None
            assert glyph_similarities_by_symbol is not None
            matches = rank_exp(
                query,
                characters,
                character_info,
                ssim_index_by_character,
                ssim_scores,
                stroke_counts,
                phonetic_map,
                decomposition_map,
                radical_map,
                glyph_index_by_symbol,
                glyph_similarities_by_symbol,
                character_set,
                glyph_threshold,
                ssim_threshold,
                max_stroke_gap,
                use_phonetic,
                use_decomposition,
            )
        else:
            raise ValueError(f"Unsupported method: {method}")

        if include_phonetic:
            matches = append_phonetic_entries(
                query=query,
                matches=matches,
                characters=characters,
                char_info=character_info,
                phonetic_map=phonetic_map,
            )
        if include_decomposition:
            assert glyph_similarities_by_symbol is not None
            matches = append_decomposition_entries(
                query=query,
                matches=matches,
                characters=characters,
                char_info=character_info,
                decomposition_map=decomposition_map,
                radical_map=radical_map,
                glyph_index_by_symbol=glyph_index_by_symbol,
                glyph_similarities_by_symbol=glyph_similarities_by_symbol,
                character_set=character_set,
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

    if (include_decomposition or use_decomposition) and glyph_similarities_by_symbol is not None:
        added_symmetric = apply_symmetric_direct_component_pairs(
            character_info=character_info,
            decomposition_map=decomposition_map,
            radical_map=radical_map,
            character_set=character_set,
            glyph_index_by_symbol=glyph_index_by_symbol,
            glyph_similarities_by_symbol=glyph_similarities_by_symbol,
            rule3_threshold=decomposition_rule3_glyph_threshold,
        )
        if added_symmetric > 0:
            total_matches += added_symmetric

    return updated, total_matches


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--method",
        choices=("glyph", "ssim", "exp"),
        required=True,
        help="Similarity method to run.",
    )
    parser.add_argument("--threshold", type=float, help="Minimum score threshold for glyph/ssim methods.")
    parser.add_argument("--max-stroke-gap", type=int, default=2, help="Maximum stroke count difference (default: 2).")
    parser.add_argument("--character", help="Update one character only.")
    parser.add_argument("--dry-run", action="store_true", help="Compute results without writing character_info.json.")
    parser.add_argument(
        "--include-decomposition",
        action="store_true",
        default=include_decomposition_default,
        help="Append extra decomposition-only matches (length>=4 single-diff, length-3 hybrid glyph rules).",
    )

    parser.add_argument("--character-info", type=Path, default=DEFAULT_CHARACTER_INFO_PATH, help="Path to character_info.json.")
    parser.add_argument("--dictionary", type=Path, default=DEFAULT_DICTIONARY_PATH, help="Path to dictionary.json.")

    parser.add_argument(
        "--glyph-metric",
        choices=("cosine", "euclidean", "euclidian", "tanh"),
        default=glyph_method,
        help="Glyph metric (used by glyph/exp).",
    )
    parser.add_argument("--glyph-font", help="Font path for glyph rendering.")
    parser.add_argument("--glyph-device", choices=("auto", "cpu", "mps"), default="auto", help="Torch device for glyph embedding.")
    parser.add_argument("--ssim-size", type=int, default=64, help="Rendered glyph image size for SSIM (default: 64).")
    parser.add_argument("--ssim-cache", type=Path, default=DEFAULT_SSIM_CACHE, help="Cache file for pairwise SSIM score matrix.")
    parser.add_argument("--refresh-ssim-cache", action="store_true", help="Rebuild SSIM score cache even if one already exists.")

    parser.add_argument("--glyph-threshold", type=float, help="Exp mode: glyph threshold (0-1).")
    parser.add_argument("--ssim-threshold", type=float, help="Exp mode: SSIM threshold (0-1).")

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
        help="Exp mode: include phonetic relation metadata on candidates.",
    )
    parser.add_argument(
        "--use-decomposition",
        action="store_true",
        default=use_decomposition_default,
        help="Exp mode: include decomposition relation metadata on candidates.",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    try:
        args.glyph_metric = normalize_glyph_metric(args.glyph_metric)
    except ValueError as error:
        parser.error(str(error))

    if args.threshold is not None and not 0 <= args.threshold <= 1:
        parser.error("--threshold must be between 0 and 1.")

    if args.glyph_threshold is not None and not 0 <= args.glyph_threshold <= 1:
        parser.error("--glyph-threshold must be between 0 and 1.")
    if args.ssim_threshold is not None and not 0 <= args.ssim_threshold <= 1:
        parser.error("--ssim-threshold must be between 0 and 1.")

    if args.max_stroke_gap < 0:
        parser.error("--max-stroke-gap must be non-negative.")
    if args.ssim_size <= 0:
        parser.error("--ssim-size must be positive.")

    if args.method in ("glyph", "ssim") and args.threshold is None:
        parser.error("--threshold is required for glyph and ssim methods.")

    include_phonetic = args.include_phonetic or args.include_naive

    try:
        character_info = json.loads(args.character_info.read_text(encoding="utf-8"))
        dictionary_records = load_dictionary_records(args.dictionary)
    except (OSError, json.JSONDecodeError, ValueError) as error:
        log(f"ERROR: {error}")
        return 1

    log(
        f"Starting method={args.method}, threshold={args.threshold}, max_stroke_gap={args.max_stroke_gap}, "
        f"target={args.character or 'ALL'}, dry_run={args.dry_run}, "
        f"exp_thresholds=(glyph:{args.glyph_threshold}, ssim:{args.ssim_threshold}), "
        f"include_phonetic={include_phonetic}, include_decomposition={args.include_decomposition}, "
        f"use_phonetic={args.use_phonetic}, use_decomposition={args.use_decomposition}"
    )

    try:
        updated, total_matches = update_character_info(
            character_info=character_info,
            method=args.method,
            threshold=args.threshold,
            max_stroke_gap=args.max_stroke_gap,
            dictionary_records=dictionary_records,
            glyph_metric=args.glyph_metric,
            glyph_font=args.glyph_font,
            glyph_device=args.glyph_device,
            ssim_cache_path=args.ssim_cache,
            refresh_ssim_cache=args.refresh_ssim_cache,
            only_character=args.character,
            include_phonetic=include_phonetic,
            include_decomposition=args.include_decomposition,
            use_phonetic=args.use_phonetic,
            use_decomposition=args.use_decomposition,
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
