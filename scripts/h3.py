"""Manifest-driven MiniMax H3 Ref2VA production harness.

The CLI deliberately keeps the model graph and its successful parameters intact.
It only fills manifest-derived values, validates the workflow contract, tracks
queue state, and keeps synthetic frames in a human-review workflow.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import shutil
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from h3_prompt import compile_prompt, reference_lookup, selected_references


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = ROOT / "workflows" / "h3_ref2va_template_api.json"
CONTRACT_PATH = ROOT / "workflows" / "h3_ref2va_contract.json"
MODEL_CONFIG_PATH = ROOT / "configs" / "extra_model_paths.yaml"
RUNS_DIR = ROOT / "runs"
OUTPUT_DIR = ROOT / "output"
VIDEO_SUFFIXES = {".mp4", ".mov", ".mkv", ".webm", ".avi"}

# These are the active, non-bypassed H3 settings from the reference workflow.
# They are part of the canonical path now; a shot-level runtime block only
# overrides them for a deliberate experiment or a model-specific exception.
DEFAULT_RUNTIME: dict[str, Any] = {
    "ref_image_size": "match",
    "sampler": "euler",
    "scheduler": "simple",
    "model_shift": {"enabled": True, "shift_video": 12.0, "shift_audio": 3.0},
    "attention": {"backend": "kitchen", "sage_attention": "auto", "allow_compile": False},
    # Cache nodes are retained as an explicit experiment because the reference
    # workflow bypasses them and cache thresholds can trade quality for speed.
    "cache": {"enabled": False},
    # TeaCache is the current production default after the keep E2E ablation.
    # Exact regression remains explicit so it cannot be confused with the
    # approximate production path.
    "approximation": {"method": "teacache"},
}


class HarnessError(RuntimeError):
    pass


def load_document(path: Path) -> dict[str, Any]:
    """Load YAML with PyYAML when available, with a small YAML-subset fallback."""
    text = path.read_text(encoding="utf-8")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    try:
        import yaml  # type: ignore

        loaded = yaml.safe_load(text)
        if not isinstance(loaded, dict):
            raise HarnessError(f"manifest must contain an object: {path}")
        return loaded
    except (ImportError, AttributeError):
        loaded = _fallback_yaml(text)
        if not isinstance(loaded, dict):
            raise HarnessError(f"manifest must contain an object: {path}")
        return loaded


def _scalar(value: str) -> Any:
    value = value.strip()
    if not value:
        return None
    if value in {"true", "True"}:
        return True
    if value in {"false", "False"}:
        return False
    if value in {"null", "Null", "~"}:
        return None
    if value.startswith(("[", "{")):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            pass
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    try:
        return float(value) if "." in value else int(value)
    except ValueError:
        return value


def _fallback_yaml(text: str) -> Any:
    lines = []
    for raw in text.splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        lines.append((indent, raw.strip()))

    def block(index: int, indent: int) -> tuple[Any, int]:
        if index >= len(lines) or lines[index][0] < indent:
            return {}, index
        is_list = lines[index][1].startswith("-")
        result: Any = [] if is_list else {}
        while index < len(lines) and lines[index][0] == indent:
            content = lines[index][1]
            if is_list:
                if not content.startswith("-"):
                    break
                item = content[1:].strip()
                index += 1
                if not item:
                    value, index = block(index, lines[index][0]) if index < len(lines) and lines[index][0] > indent else (None, index)
                elif ":" in item and not item.startswith(("http:", "https:")):
                    key, raw_value = item.split(":", 1)
                    value = {key.strip(): _scalar(raw_value)} if raw_value.strip() else {key.strip(): None}
                    if index < len(lines) and lines[index][0] > indent:
                        nested, index = block(index, lines[index][0])
                        if raw_value.strip():
                            if isinstance(nested, dict):
                                value.update(nested)
                        else:
                            value[key.strip()] = nested
                else:
                    value = _scalar(item)
                result.append(value)
                continue
            if ":" not in content:
                raise HarnessError(f"cannot parse YAML line: {content}")
            key, raw_value = content.split(":", 1)
            key = key.strip()
            raw_value = raw_value.strip()
            index += 1
            if raw_value in {">", "|"}:
                parts = []
                while index < len(lines) and lines[index][0] > indent:
                    parts.append(lines[index][1])
                    index += 1
                result[key] = (" " if raw_value == ">" else "\n").join(parts).strip()
            elif raw_value:
                result[key] = _scalar(raw_value)
            elif index < len(lines) and lines[index][0] > indent:
                result[key], index = block(index, lines[index][0])
            else:
                result[key] = None
        return result, index

    return block(0, lines[0][0])[0] if lines else {}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_schema(document: dict[str, Any], schema_path: Path, label: str) -> None:
    try:
        from jsonschema import Draft202012Validator  # type: ignore
    except ImportError:
        _manual_shape_validation(document, label)
        return
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    errors = sorted(Draft202012Validator(schema).iter_errors(document), key=lambda e: list(e.path))
    if errors:
        details = "; ".join(f"{label} {'/'.join(map(str, e.path))}: {e.message}" for e in errors[:5])
        raise HarnessError(details)


def _manual_shape_validation(document: dict[str, Any], label: str) -> None:
    required = {
        "character": {"id", "display_name", "references", "identity", "background_policy"},
        "shot": {"id", "character", "references", "duration", "action", "camera", "audio", "generation"},
    }[label]
    missing = required - set(document)
    if missing:
        raise HarnessError(f"{label} missing required keys: {', '.join(sorted(missing))}")


def validate_profile(profile: dict[str, Any], label: str) -> None:
    if profile.get("turbo") and not 4 <= int(profile.get("steps", 0)) <= 8:
        raise HarnessError(f"{label}: Turbo profiles must use 4-8 steps")


def validate_shot_structure(shot: dict[str, Any], label: str) -> None:
    beats = shot.get("beats") or []
    if not beats and not (shot.get("action") or {}).get("description"):
        raise HarnessError(f"{label}: provide action.description or beats")
    previous_end = 0.0
    for beat in beats:
        start, end = float(beat["start"]), float(beat["end"])
        if start < previous_end or end <= start or end > float(shot["duration"]):
            raise HarnessError(f"{label}: beats must be ordered, non-overlapping, and within duration")
        previous_end = end


def load_contract() -> dict[str, Any]:
    return json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))


def validate_workflow_contract(graph: dict[str, Any], contract: dict[str, Any] | None = None) -> None:
    contract = contract or load_contract()
    errors = []
    for logical_name, node_id in contract.items():
        if logical_name in {"version", "workflow", "expected"}:
            continue
        if str(node_id) not in graph:
            errors.append(f"{logical_name}: node {node_id} is missing")
    for node_id, expectation in contract.get("expected", {}).items():
        node = graph.get(str(node_id))
        if node is None:
            errors.append(f"node {node_id} is missing")
            continue
        if node.get("class_type") != expectation.get("class_type"):
            errors.append(f"node {node_id}: expected class_type {expectation.get('class_type')}, got {node.get('class_type')}")
        inputs = node.get("inputs")
        for input_key in expectation.get("inputs", []):
            if not isinstance(inputs, dict) or input_key not in inputs:
                errors.append(f"node {node_id}: missing input {input_key}")
    ref_node = graph.get(str(contract["reference_node"]))
    if ref_node:
        if not any(key.startswith("ref_images.ref_image_") for key in ref_node.get("inputs", {})):
            errors.append(f"node {contract['reference_node']}: no reference input slots")
    if errors:
        raise HarnessError("workflow contract mismatch (fail fast): " + " | ".join(errors))


def character_manifest_paths() -> list[Path]:
    return sorted((ROOT / "characters").glob("**/*.yaml"))


def find_character_manifest(character_id: str) -> Path:
    matches = []
    for path in character_manifest_paths():
        try:
            if load_document(path).get("id") == character_id:
                matches.append(path)
        except (OSError, HarnessError):
            continue
    if not matches:
        raise HarnessError(f"character manifest not found for id: {character_id}")
    if len(matches) > 1:
        raise HarnessError(f"multiple character manifests found for id {character_id}: {', '.join(str(p.relative_to(ROOT)) for p in matches)}")
    return matches[0]


def resolve_reference_path(ref: dict[str, Any], character_path: Path, character_id: str) -> Path:
    """Resolve a manifest path when an optional game-name folder was inserted."""
    declared = ROOT / ref["file"]
    if declared.is_file():
        return declared
    try:
        character_parent = character_path.resolve().relative_to((ROOT / "characters").resolve()).parent.parts
    except ValueError:
        character_parent = ()
    ref_path = Path(ref["file"])
    parts = list(ref_path.parts)
    candidates: list[Path] = []
    if character_parent and len(parts) >= 3 and parts[0] == "assets" and parts[1] == "references":
        candidates.append(ROOT / "assets" / "references" / Path(*character_parent) / Path(*parts[2:]))
    if character_parent:
        candidates.append(ROOT / "assets" / "references" / Path(*character_parent) / character_id / ref_path.name)
    candidates.extend((ROOT / "assets" / "references").glob(f"**/{ref_path.name}"))
    existing = []
    seen = set()
    for candidate in candidates:
        candidate = candidate.resolve()
        if candidate.is_file() and candidate not in seen:
            existing.append(candidate)
            seen.add(candidate)
    if len(existing) == 1:
        return existing[0]
    if len(existing) > 1:
        paths = ", ".join(str(path.relative_to(ROOT)) for path in existing)
        raise HarnessError(f"ambiguous reference image for {ref['file']}: {paths}; specify the exact manifest path")
    raise HarnessError(
        f"reference image missing: {declared}. Checked optional game-folder variants; "
        "update only the manifest file name if the actual asset is named differently."
    )


def validate_repository() -> list[str]:
    if not WORKFLOW_PATH.is_file():
        raise HarnessError(f"canonical workflow missing: {WORKFLOW_PATH}")
    if not MODEL_CONFIG_PATH.is_file():
        raise HarnessError(f"model-path config missing: {MODEL_CONFIG_PATH}")
    model_config = load_document(MODEL_CONFIG_PATH)
    for name, section in model_config.items():
        if isinstance(section, dict) and isinstance(section.get("base_path"), str) and Path(section["base_path"]).is_absolute():
            raise HarnessError(f"model path config must stay portable; absolute base_path in {name}")
    graph = json.loads(WORKFLOW_PATH.read_text(encoding="utf-8"))
    validate_workflow_contract(graph)
    characters = character_manifest_paths()
    shots = list((ROOT / "shots").glob("**/*.yaml"))
    if not characters or not shots:
        raise HarnessError("at least one character and one shot manifest are required")
    character_map = {}
    for path in characters:
        doc = load_document(path)
        validate_schema(doc, ROOT / "schemas" / "character.schema.json", "character")
        if doc["id"] in character_map:
            raise HarnessError(f"duplicate character id: {doc['id']}")
        character_map[doc["id"]] = (path, doc)
    shot_documents = []
    for path in shots:
        doc = load_document(path)
        validate_schema(doc, ROOT / "schemas" / "shot.schema.json", "shot")
        validate_shot_structure(doc, str(path))
        validate_profile(doc["generation"]["explore"], f"{path} explore")
        validate_profile(doc["generation"]["keep"], f"{path} keep")
        shot_documents.append((path, doc))
    active_characters = {doc["character"] for _, doc in shot_documents}
    for character_id in active_characters:
        if character_id not in character_map:
            raise HarnessError(f"shot references unknown character {character_id}")
        character_path, character = character_map[character_id]
        for ref in character["references"]:
            resolve_reference_path(ref, character_path, character_id)
    names = []
    for path, doc in shot_documents:
        if doc["character"] not in character_map:
            raise HarnessError(f"shot {path} references unknown character {doc['character']}")
        refs = set(reference_lookup(character_map[doc["character"]][1]))
        unknown = set(doc["references"]) - refs
        if unknown:
            raise HarnessError(f"shot {path} references unknown reference ids: {', '.join(sorted(unknown))}")
        if len(doc["references"]) > 9:
            raise HarnessError(f"shot {path} has more than 9 references")
        names.append(str(path.relative_to(ROOT)))
    return names


def _node_id(graph: dict[str, Any], preferred: list[str], used: set[str]) -> str:
    for node_id in preferred:
        if node_id in graph and node_id not in used:
            used.add(node_id)
            return node_id
    candidate = max([int(k) for k in graph if str(k).isdigit()] or [0]) + 1
    while str(candidate) in graph or str(candidate) in used:
        candidate += 1
    used.add(str(candidate))
    return str(candidate)


def _add_model_patch(graph: dict[str, Any], used: set[str], class_type: str, inputs: dict[str, Any]) -> str:
    node_id = _node_id(graph, [], used)
    graph[node_id] = {"class_type": class_type, "inputs": inputs}
    return node_id


def effective_runtime(overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return the canonical H3 runtime with shot-level overrides merged in."""
    result = copy.deepcopy(DEFAULT_RUNTIME)

    def merge(destination: dict[str, Any], source: dict[str, Any]) -> None:
        for key, value in source.items():
            if isinstance(value, dict) and isinstance(destination.get(key), dict):
                merge(destination[key], value)
            else:
                destination[key] = copy.deepcopy(value)

    if overrides:
        merge(result, overrides)
    return result


def _apply_runtime_profile(graph: dict[str, Any], contract: dict[str, Any], runtime: dict[str, Any] | None, steps: int | None = None) -> dict[str, Any]:
    """Apply the canonical H3 runtime and any explicit shot-level overrides.

    Positive reference-workflow defaults are inserted for every graph. Experimental
    attention/cache paths remain explicit overrides so an A/B run is reproducible.
    """
    runtime = effective_runtime(runtime)
    ref_image_size = runtime.get("ref_image_size", "max")
    graph[contract["reference_node"]]["inputs"]["ref_image_size"] = ref_image_size

    if runtime.get("sampler"):
        graph[contract["sampler"]]["inputs"]["sampler_name"] = runtime["sampler"]
    if runtime.get("scheduler"):
        graph[contract["scheduler"]]["inputs"]["scheduler"] = runtime["scheduler"]

    models = runtime.get("models") or {}
    if models.get("transformer"):
        graph["127"]["inputs"]["unet_name"] = models["transformer"]
    if models.get("text_encoder"):
        graph["128"]["inputs"]["clip_name"] = models["text_encoder"]
    if models.get("turbo_lora"):
        graph["145"]["inputs"]["lora_name"] = models["turbo_lora"]

    used: set[str] = set()
    current_model = "127"
    model_shift = runtime.get("model_shift") or {}
    if model_shift.get("enabled"):
        current_model = _add_model_patch(
            graph,
            used,
            "MiniMaxH3SigmaShift",
            {
                "model": [current_model, 0],
                "shift_video": float(model_shift.get("shift_video", 12)),
                "shift_audio": float(model_shift.get("shift_audio", 3)),
            },
        )

    attention = runtime.get("attention") or {}
    backend = attention.get("backend", "default")
    if backend == "kitchen":
        current_model = _add_model_patch(
            graph,
            used,
            "ModelAttentionBackend",
            {"model": [current_model, 0], "attention": "comfy kitchen attention"},
        )
    elif backend == "sage":
        current_model = _add_model_patch(
            graph,
            used,
            "PathchSageAttentionKJ",
            {
                "model": [current_model, 0],
                "sage_attention": attention.get("sage_attention", "auto"),
                "allow_compile": bool(attention.get("allow_compile", False)),
            },
        )
        current_model = _add_model_patch(
            graph,
            used,
            "MiniMaxH3MemoryEfficientSageAttentionPatch",
            {"model": [current_model, 0]},
        )
    elif backend != "default":
        raise HarnessError(f"unsupported attention backend: {backend}")

    cache = runtime.get("cache") or {}
    approximation = runtime.get("approximation") or {}
    approximation_method = approximation.get("method", "none")
    if approximation_method not in {"none", "teacache", "spectrum", "speed_cache", "fastpath"}:
        raise HarnessError(f"unsupported approximation method: {approximation_method}")
    if approximation_method != "none" and cache.get("enabled"):
        raise HarnessError("cache.enabled and approximation.method cannot be enabled together; use one cache/forecast method")
    if cache.get("enabled"):
        current_model = _add_model_patch(
            graph,
            used,
            "AGSoftMiniMaxH3Cache",
            {
                "model": [current_model, 0],
                "profile": cache.get("profile", "Balanced"),
                "video_threshold": float(cache.get("video_threshold", 0.12)),
                "audio_threshold": float(cache.get("audio_threshold", 0.1)),
                "start_percent": float(cache.get("start_percent", 0.1)),
                "end_percent": float(cache.get("end_percent", 0.9)),
                "warmup_steps": int(cache.get("warmup_steps", 2)),
                "max_steps": int(cache.get("max_steps", 1)),
                "video_metric_stride": int(cache.get("video_metric_stride", 12)),
                "audio_metric_stride": int(cache.get("audio_metric_stride", 6)),
                "device": cache.get("device", "auto"),
                "verbose": bool(cache.get("verbose", True)),
            },
        )

    if approximation_method != "none":
        settings = approximation.get(approximation_method) or {}
        if approximation_method == "teacache":
            current_model = _add_model_patch(
                graph,
                used,
                "MiniMaxH3TeaCache",
                {
                    "model": [current_model, 0],
                    "rel_l1_thresh": float(settings.get("rel_l1_thresh", 0.15)),
                    "start_step": int(settings.get("start_step", 2)),
                    "end_step": int(settings.get("end_step", -2)),
                    "total_steps": int(steps or settings.get("total_steps", 20)),
                },
            )
        elif approximation_method == "spectrum":
            current_model = _add_model_patch(
                graph,
                used,
                "SpectrumApplyMiniMaxH3",
                {
                    "model": [current_model, 0],
                    "enabled": bool(settings.get("enabled", True)),
                    "blend_weight": float(settings.get("blend_weight", 0.50)),
                    "degree": int(settings.get("degree", 1)),
                    "ridge_lambda": float(settings.get("ridge_lambda", 0.10)),
                    "window_size": float(settings.get("window_size", 2.0)),
                    "flex_window": float(settings.get("flex_window", 0.75)),
                    "warmup_steps": int(settings.get("warmup_steps", 1)),
                    "tail_actual_steps": int(settings.get("tail_actual_steps", 1)),
                    "max_history": int(settings.get("max_history", 8)),
                    "debug": bool(settings.get("debug", False)),
                    "history_storage": settings.get("history_storage", "system_ram"),
                    "bootstrap_first_forecast": bool(settings.get("bootstrap_first_forecast", True)),
                    "anchor_residual_feedback": bool(settings.get("anchor_residual_feedback", False)),
                    "selective_rollback_correction": bool(settings.get("selective_rollback_correction", False)),
                    "offline_smoothing_replay": bool(settings.get("offline_smoothing_replay", True)),
                    "audio_blend_weight": float(settings.get("audio_blend_weight", 0.0)),
                    "offline_archive_storage": settings.get("offline_archive_storage", "system_ram"),
                    "model_aware_mode": settings.get("model_aware_mode", "off"),
                    "model_aware_risk_threshold": float(settings.get("model_aware_risk_threshold", 0.65)),
                    "model_aware_trust_shrinkage": bool(settings.get("model_aware_trust_shrinkage", False)),
                    "model_aware_replay_generic_correction": bool(settings.get("model_aware_replay_generic_correction", False)),
                    "generic_correction_mode": settings.get("generic_correction_mode", "coordinate_rls"),
                    "generic_correction_limiter": settings.get("generic_correction_limiter", "hard_clip"),
                    "generic_correction_limit": float(settings.get("generic_correction_limit", 0.40)),
                    "generic_correction_attenuation": settings.get("generic_correction_attenuation", "no_attenuation"),
                    "sa_pece_forecast_policy": settings.get("sa_pece_forecast_policy", "balanced"),
                },
            )
        elif approximation_method == "speed_cache":
            current_model = _add_model_patch(
                graph,
                used,
                "MiniMaxH3SpeedCache",
                {
                    "model": [current_model, 0],
                    "reuse_threshold": float(settings.get("reuse_threshold", 0.12)),
                    "start_percent": float(settings.get("start_percent", 0.10)),
                    "end_percent": float(settings.get("end_percent", 0.90)),
                    "max_consecutive_skips": int(settings.get("max_consecutive_skips", 2)),
                    "cache_device": settings.get("cache_device", "auto"),
                    "vram_reserve_gb": float(settings.get("vram_reserve_gb", 2.0)),
                    "ram_reserve_gb": float(settings.get("ram_reserve_gb", 4.0)),
                    "signature_tokens": int(settings.get("signature_tokens", 128)),
                    "signature_features": int(settings.get("signature_features", 64)),
                    "verbose": bool(settings.get("verbose", False)),
                    "sage_attention": settings.get("sage_attention", "auto"),
                },
            )
        elif approximation_method == "fastpath":
            current_model = _add_model_patch(
                graph,
                used,
                "MiniMaxH3EulerMiddleCache",
                {
                    "model": [current_model, 0],
                    "enabled": bool(settings.get("enabled", True)),
                    "prefix_blocks": int(settings.get("prefix_blocks", 8)),
                    "suffix_blocks": int(settings.get("suffix_blocks", 8)),
                    "reuse_threshold": float(settings.get("reuse_threshold", 0.12)),
                    "max_consecutive_reuses": int(settings.get("max_consecutive_reuses", 1)),
                    "cache_device": settings.get("cache_device", "gpu"),
                    "require_fastpath_schedule": bool(settings.get("require_fastpath_schedule", False)),
                    "strict_branch_identity": bool(settings.get("strict_branch_identity", True)),
                    "suppress_candidate_prefetch": bool(settings.get("suppress_candidate_prefetch", True)),
                    "verbose": bool(settings.get("verbose", False)),
                },
            )

    if current_model != "127":
        graph["145"]["inputs"]["model"] = [current_model, 0]
        graph["141"]["inputs"]["on_false"] = [current_model, 0]
    return runtime


def build_graph(prompt: str, references: list[dict[str, Any]], profile: dict[str, Any], seed: int, duration: float, prefix: str, image_names: list[str] | None = None, runtime: dict[str, Any] | None = None) -> dict[str, Any]:
    graph = json.loads(WORKFLOW_PATH.read_text(encoding="utf-8"))
    validate_workflow_contract(graph)
    contract = load_contract()
    runtime = _apply_runtime_profile(graph, contract, runtime, int(profile.get("steps", 20)))
    graph[contract["megapixels"]]["inputs"]["megapixels"] = profile["megapixels"]
    graph[contract["seed"]]["inputs"]["noise_seed"] = int(seed)
    graph[contract["duration"]]["inputs"]["value"] = duration
    graph[contract["steps_a"]]["inputs"]["value"] = int(profile["steps"])
    graph[contract["steps_b"]]["inputs"]["value"] = int(profile["steps"])
    graph[contract["turbo"]]["inputs"]["value"] = bool(profile["turbo"])
    graph[contract["filename_prefix"]]["inputs"]["filename_prefix"] = prefix.replace("\\", "/")
    graph[contract["prompt"]]["inputs"]["value"] = prompt

    ref_node = graph[contract["reference_node"]]
    old_ids = []
    for key, pair in list(ref_node["inputs"].items()):
        if key.startswith("ref_images.ref_image_"):
            if isinstance(pair, list) and pair:
                old_ids.append(str(pair[0]))
            del ref_node["inputs"][key]
    used: set[str] = set()
    preferred = old_ids + ["137", "147", "148"]
    image_names = image_names or [Path(ref["file"]).name for ref in references]
    if len(image_names) != len(references):
        raise HarnessError("image_names and references must have the same length")
    for index, (ref, image_name) in enumerate(zip(references, image_names)):
        node_id = _node_id(graph, preferred, used)
        ref_node["inputs"][f"ref_images.ref_image_{index}"] = [node_id, 0]
        graph[node_id] = {"class_type": "LoadImage", "inputs": {"image": image_name, "upload": "image"}}
    ref_node["inputs"]["ref_image_size"] = runtime["ref_image_size"]
    for stale_id in set(old_ids) - used:
        node = graph.get(stale_id)
        if node and node.get("class_type") == "LoadImage":
            del graph[stale_id]
    return graph


def ensure_directories() -> None:
    for path in (
        ROOT / "input",
        OUTPUT_DIR / "video",
        OUTPUT_DIR / "frames" / "pending",
        OUTPUT_DIR / "frames" / "accepted",
        OUTPUT_DIR / "frames" / "rejected",
        OUTPUT_DIR / "qc",
        ROOT / "temp",
        ROOT / "logs",
        RUNS_DIR,
    ):
        path.mkdir(parents=True, exist_ok=True)


def stage_references(character: dict[str, Any], references: list[dict[str, Any]], character_path: Path | None = None) -> list[str]:
    destination = ROOT / "input" / "h3" / character["id"]
    destination.mkdir(parents=True, exist_ok=True)
    names = []
    for ref in references:
        source = resolve_reference_path(ref, character_path or (ROOT / "characters" / f"{character['id']}.yaml"), character["id"])
        ref["resolved_file"] = source.relative_to(ROOT).as_posix()
        name = f"{ref['id']}_{source.name}"
        target = destination / name
        if not target.is_file() or sha256(target) != sha256(source):
            shutil.copy2(source, target)
        names.append(target.relative_to(ROOT / "input").as_posix())
    return names


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def api_json(api_url: str, endpoint: str, payload: dict[str, Any] | None = None, timeout: float = 30) -> Any:
    data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = Request(api_url.rstrip("/") + endpoint, data=data, headers={"Content-Type": "application/json"}, method="POST" if data else "GET")
    with urlopen(request, timeout=timeout) as response:
        body = response.read().decode("utf-8")
    return json.loads(body) if body else {}


def _history_result(history: dict[str, Any], prompt_id: str) -> tuple[str, str | None, list[dict[str, Any]]]:
    item = history.get(prompt_id) or history.get(str(prompt_id))
    if not item:
        return "queued", None, []
    status = item.get("status") or {}
    messages = status.get("messages") or []
    execution_failed = any(isinstance(message, list) and message and message[0] in {"execution_error", "execution_interrupted"} for message in messages)
    if status.get("status_str") in {"error", "failed"} or execution_failed:
        return "failed", json.dumps(status, ensure_ascii=False), []
    if status.get("completed") or status.get("status_str") == "success":
        outputs = []
        for node_output in (item.get("outputs") or {}).values():
            # ComfyUI's SaveVideo node currently reports video files under
            # `images`, while other save nodes may use one of the legacy keys.
            for key in ("gifs", "videos", "video", "files", "images"):
                values = node_output.get(key, []) if isinstance(node_output, dict) else []
                if isinstance(values, dict):
                    values = [values]
                outputs.extend(v for v in values if isinstance(v, dict))
        return "completed", None, outputs
    return "running", None, []


def wait_for_completion(api_url: str, prompt_id: str, timeout_seconds: float, poll_seconds: float = 2.0) -> tuple[list[dict[str, Any]], float]:
    started = time.monotonic()
    while True:
        if time.monotonic() - started > timeout_seconds:
            raise TimeoutError(f"timed out waiting for prompt {prompt_id}")
        history = api_json(api_url, f"/history/{prompt_id}")
        state, error, outputs = _history_result(history, prompt_id)
        if state == "completed":
            return outputs, time.monotonic() - started
        if state == "failed":
            raise HarnessError(error or f"ComfyUI failed prompt {prompt_id}")
        time.sleep(min(poll_seconds, max(0.1, timeout_seconds - (time.monotonic() - started))))


def resolve_outputs(outputs: list[dict[str, Any]]) -> list[str]:
    resolved = []
    for item in outputs:
        filename = item.get("filename")
        if not filename or Path(str(filename)).suffix.lower() not in VIDEO_SUFFIXES:
            continue
        base = OUTPUT_DIR if item.get("type", "output") == "output" else ROOT / str(item.get("type"))
        path = base / str(item.get("subfolder", "")) / filename
        try:
            path.resolve().relative_to(OUTPUT_DIR.resolve())
        except ValueError:
            continue
        if path.is_file():
            resolved.append(path.relative_to(ROOT).as_posix())
    return resolved


def _model_profile(graph: dict[str, Any]) -> dict[str, Any]:
    return {
        "transformer": graph.get("127", {}).get("inputs", {}).get("unet_name"),
        "text_encoder": graph.get("128", {}).get("inputs", {}).get("clip_name"),
        "turbo_lora": graph.get("145", {}).get("inputs", {}).get("lora_name"),
    }


def execute_run(shot_path: Path, seed: int, profile_name: str, api_url: str, timeout: float, retries: int) -> Path:
    ensure_directories()
    shot = load_document(shot_path)
    character_path = find_character_manifest(shot["character"])
    character = load_document(character_path)
    validate_schema(character, ROOT / "schemas" / "character.schema.json", "character")
    validate_schema(shot, ROOT / "schemas" / "shot.schema.json", "shot")
    validate_shot_structure(shot, str(shot_path))
    refs = selected_references(character, shot)
    profile = shot["generation"][profile_name]
    runtime = effective_runtime(shot.get("runtime"))
    prompt = compile_prompt(character, shot)
    prompt_id = hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:16]
    run_id = f"{datetime.now().strftime('%Y%m%d-%H%M%S')}-{shot['id']}-{profile_name}-{seed}-{uuid.uuid4().hex[:6]}"
    run_dir = RUNS_DIR / datetime.now().strftime("%Y-%m-%d") / run_id
    prompt_path = run_dir / "prompt.txt"
    prompt_path.parent.mkdir(parents=True, exist_ok=True)
    prompt_path.write_text(prompt, encoding="utf-8")
    image_names = stage_references(character, refs, character_path)
    graph = build_graph(prompt, refs, profile, seed, shot["duration"], f"video/{run_id}", image_names, runtime)
    workflow_snapshot = run_dir / "workflow.json"
    write_json(workflow_snapshot, graph)
    manifest: dict[str, Any] = {
        "run_id": run_id,
        "shot_id": shot["id"],
        "character": character["id"],
        "prompt_id": None,
        "prompt_hash": prompt_id,
        "seed": int(seed),
        "duration": shot["duration"],
        "megapixels": profile["megapixels"],
        "steps": profile["steps"],
        "turbo": profile["turbo"],
        "runtime": runtime,
        "references": [{"id": ref["id"], "file": ref.get("resolved_file", ref["file"]), "declared_file": ref["file"], "role": ref["role"], "picture_label": ref["picture_label"]} for ref in refs],
        "prompt_file": prompt_path.relative_to(ROOT).as_posix(),
        "workflow_file": WORKFLOW_PATH.relative_to(ROOT).as_posix(),
        "workflow_snapshot": workflow_snapshot.relative_to(ROOT).as_posix(),
        "workflow_sha256": sha256(WORKFLOW_PATH),
        "prompt_sha256": sha256(prompt_path),
        "model_profile": _model_profile(graph),
        "submitted_at": datetime.now(timezone.utc).isoformat(),
        "status": "queued",
        "attempts": [],
    }
    manifest_path = run_dir / "run.json"
    write_json(manifest_path, manifest)
    body = {"prompt": graph, "client_id": f"h3-{run_id}"}
    for attempt in range(retries + 1):
        try:
            result = api_json(api_url, "/prompt", body)
            current_prompt_id = str(result.get("prompt_id") or "")
            if not current_prompt_id:
                raise HarnessError(f"ComfyUI response did not contain prompt_id: {result}")
            manifest["prompt_id"] = current_prompt_id
            manifest["attempts"].append({"attempt": attempt + 1, "prompt_id": current_prompt_id, "submitted_at": datetime.now(timezone.utc).isoformat()})
            write_json(manifest_path, manifest)
            outputs, elapsed = wait_for_completion(api_url, current_prompt_id, timeout)
            output_paths = resolve_outputs(outputs)
            if not output_paths:
                raise HarnessError(f"ComfyUI completed prompt {current_prompt_id} but no real output video was found under output/")
            manifest.update({"status": "completed", "output_video": output_paths, "elapsed_seconds": round(elapsed, 3), "completed_at": datetime.now(timezone.utc).isoformat()})
            write_json(manifest_path, manifest)
            print(json.dumps({"run_id": run_id, "prompt_id": current_prompt_id, "status": "completed", "output_video": output_paths}, ensure_ascii=False))
            return manifest_path
        except (HarnessError, TimeoutError, HTTPError, URLError, OSError) as exc:
            manifest["last_error"] = str(exc)
            if attempt >= retries:
                manifest.update({"status": "failed", "error": str(exc), "failed_at": datetime.now(timezone.utc).isoformat()})
                write_json(manifest_path, manifest)
                raise
            manifest["status"] = "retrying"
            write_json(manifest_path, manifest)
    raise AssertionError("unreachable")


def find_run(run_id: str) -> tuple[Path, dict[str, Any]]:
    matches = list(RUNS_DIR.glob(f"*/{run_id}/run.json"))
    if not matches:
        raise HarnessError(f"run not found: {run_id}")
    path = matches[0]
    return path, json.loads(path.read_text(encoding="utf-8"))


def cmd_validate(_: argparse.Namespace) -> None:
    names = validate_repository()
    print(f"valid: workflow contract, {len(names)} shot manifest(s), model path config")


def cmd_prompt(args: argparse.Namespace) -> None:
    shot_path = (ROOT / args.shot).resolve()
    shot = load_document(shot_path)
    character = load_document(find_character_manifest(shot["character"]))
    print(compile_prompt(character, shot))


def cmd_run(args: argparse.Namespace) -> None:
    path = execute_run((ROOT / args.shot).resolve(), args.seed, args.profile, args.api_url, args.timeout, args.retries)
    print(f"run manifest: {path.relative_to(ROOT)}")


def cmd_explore(args: argparse.Namespace) -> None:
    shot = load_document((ROOT / args.shot).resolve())
    profile = shot["generation"]["explore"]
    count = args.count or profile["takes"]
    for offset in range(count):
        seed = args.start_seed + offset
        execute_run((ROOT / args.shot).resolve(), seed, "explore", args.api_url, args.timeout, args.retries)


def cmd_extract(args: argparse.Namespace) -> None:
    manifest_path, run = find_run(args.run_id)
    from extract_keyframes import extract_run

    paths = extract_run(ROOT, run)
    run["frames_pending"] = [path.relative_to(ROOT).as_posix() for path in paths]
    run["frames_csv"] = f"output/frames/pending/{args.run_id}/frames.csv"
    run["contact_sheet"] = f"output/qc/{args.run_id}/contact_sheet.jpg"
    run["qc_status"] = "pending_manual_review"
    write_json(manifest_path, run)
    print(f"pending frames: {len(paths)}")
    print(f"contact sheet: {ROOT / 'output' / 'qc' / args.run_id / 'contact_sheet.jpg'}")


def cmd_qc(args: argparse.Namespace) -> None:
    manifest_path, run = find_run(args.run_id)
    from extract_keyframes import create_contact_sheet, read_image

    pending_dir = OUTPUT_DIR / "frames" / "pending" / args.run_id
    csv_path = pending_dir / "frames.csv"
    if not csv_path.is_file():
        raise HarnessError(f"run has no extracted frames: {csv_path}")
    rows = []
    import csv
    with csv_path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    candidates = []
    for row in rows:
        path = pending_dir / row["frame"]
        if path.is_file():
            candidates.append({"path": path, "image": read_image(path), "time": float(row["time"]), "sharpness": float(row["sharpness"]), "duplicate_score": float(row["duplicate_score"])})
    references = [ROOT / item["file"] for item in run.get("references", [])]
    sheet = create_contact_sheet(ROOT, args.run_id, references, candidates)
    run["contact_sheet"] = sheet.relative_to(ROOT).as_posix()
    run["qc_status"] = "pending_manual_review"
    write_json(manifest_path, run)
    print(sheet)


def _promote(run_id: str, frame_name: str, destination_name: str) -> None:
    manifest_path, run = find_run(run_id)
    pending_root = OUTPUT_DIR / "frames" / "pending" / run_id
    source = pending_root / (frame_name if frame_name.endswith(".png") else frame_name + ".png")
    if not source.is_file():
        raise HarnessError(f"pending frame not found: {source}")
    destination = OUTPUT_DIR / "frames" / destination_name / run_id
    destination.mkdir(parents=True, exist_ok=True)
    target = destination / source.name
    shutil.move(str(source), str(target))
    sidecar = {
        "source_type": "h3_synthetic",
        "run_id": run_id,
        "source_video": (run.get("output_video") or [None])[0],
        "character": run["character"],
        "shot": run["shot_id"],
        "seed": run["seed"],
        "promoted_at": datetime.now(timezone.utc).isoformat(),
    }
    write_json(target.with_suffix(".json"), sidecar)
    run.setdefault("qc_events", []).append({"frame": source.stem, "status": destination_name, "at": sidecar["promoted_at"]})
    run["qc_status"] = "review_in_progress"
    write_json(manifest_path, run)
    print(target.relative_to(ROOT))


def cmd_accept(args: argparse.Namespace) -> None:
    _promote(args.run_id, args.frame, "accepted")


def cmd_reject(args: argparse.Namespace) -> None:
    _promote(args.run_id, args.frame, "rejected")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manifest-driven MiniMax H3 Ref2VA harness")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("validate").set_defaults(func=cmd_validate)
    prompt = sub.add_parser("prompt"); prompt.add_argument("shot"); prompt.set_defaults(func=cmd_prompt)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--api-url", default="http://127.0.0.1:8189")
    common.add_argument("--timeout", type=float, default=3600)
    common.add_argument("--retries", type=int, default=1)
    run = sub.add_parser("run", parents=[common]); run.add_argument("shot"); run.add_argument("--seed", type=int, required=True); run.add_argument("--profile", choices=["explore", "keep"], default="keep"); run.set_defaults(func=cmd_run)
    explore = sub.add_parser("explore", parents=[common]); explore.add_argument("shot"); explore.add_argument("--start-seed", type=int, default=734112); explore.add_argument("--count", type=int); explore.set_defaults(func=cmd_explore)
    extract = sub.add_parser("extract"); extract.add_argument("run_id"); extract.set_defaults(func=cmd_extract)
    qc = sub.add_parser("qc"); qc.add_argument("run_id"); qc.set_defaults(func=cmd_qc)
    for name, func in (("accept", cmd_accept), ("reject", cmd_reject)):
        command = sub.add_parser(name); command.add_argument("run_id"); command.add_argument("frame"); command.set_defaults(func=func)
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        args = build_parser().parse_args(argv)
        args.func(args)
        return 0
    except (HarnessError, TimeoutError, HTTPError, URLError, OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
