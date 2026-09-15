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

from h3_prompt import compile_prompt, selected_references


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = ROOT / "workflows" / "h3_ref2va_template_api.json"
CONTRACT_PATH = ROOT / "workflows" / "h3_ref2va_contract.json"
MODEL_CONFIG_PATH = ROOT / "configs" / "extra_model_paths.yaml"
RUNS_DIR = ROOT / "runs"
OUTPUT_DIR = ROOT / "output"


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
    characters = list((ROOT / "characters").glob("*.yaml"))
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
        if len({ref["id"] for ref in doc["references"]}) != len(doc["references"]):
            raise HarnessError(f"duplicate reference id in {path}")
        for ref in doc["references"]:
            if not (ROOT / ref["file"]).is_file():
                raise HarnessError(f"reference image missing: {ROOT / ref['file']}")
    names = []
    for path in shots:
        doc = load_document(path)
        validate_schema(doc, ROOT / "schemas" / "shot.schema.json", "shot")
        validate_profile(doc["generation"]["explore"], f"{path} explore")
        validate_profile(doc["generation"]["keep"], f"{path} keep")
        if doc["character"] not in character_map:
            raise HarnessError(f"shot {path} references unknown character {doc['character']}")
        refs = {ref["id"] for ref in character_map[doc["character"]][1]["references"]}
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


def build_graph(prompt: str, references: list[dict[str, Any]], profile: dict[str, Any], seed: int, duration: float, prefix: str, image_names: list[str] | None = None) -> dict[str, Any]:
    graph = json.loads(WORKFLOW_PATH.read_text(encoding="utf-8"))
    validate_workflow_contract(graph)
    contract = load_contract()
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
    ref_node["inputs"]["ref_image_size"] = "max"
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


def stage_references(character: dict[str, Any], references: list[dict[str, Any]]) -> list[str]:
    destination = ROOT / "input" / "h3" / character["id"]
    destination.mkdir(parents=True, exist_ok=True)
    names = []
    for ref in references:
        source = ROOT / ref["file"]
        if not source.is_file():
            raise HarnessError(f"reference image missing: {source}")
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
            for key in ("gifs", "videos", "video", "files"):
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
        if not filename:
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
    character_path = ROOT / "characters" / f"{shot['character']}.yaml"
    character = load_document(character_path)
    validate_schema(character, ROOT / "schemas" / "character.schema.json", "character")
    validate_schema(shot, ROOT / "schemas" / "shot.schema.json", "shot")
    refs = selected_references(character, shot)
    profile = shot["generation"][profile_name]
    prompt = compile_prompt(character, shot)
    prompt_id = hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:16]
    run_id = f"{datetime.now().strftime('%Y%m%d-%H%M%S')}-{shot['id']}-{profile_name}-{seed}-{uuid.uuid4().hex[:6]}"
    run_dir = RUNS_DIR / datetime.now().strftime("%Y-%m-%d") / run_id
    prompt_path = run_dir / "prompt.txt"
    prompt_path.parent.mkdir(parents=True, exist_ok=True)
    prompt_path.write_text(prompt, encoding="utf-8")
    image_names = stage_references(character, refs)
    graph = build_graph(prompt, refs, profile, seed, shot["duration"], f"video/{run_id}", image_names)
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
        "references": [{"id": ref["id"], "file": ref["file"], "role": ref["role"], "picture_label": ref["picture_label"]} for ref in refs],
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
    character = load_document(ROOT / "characters" / f"{shot['character']}.yaml")
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
