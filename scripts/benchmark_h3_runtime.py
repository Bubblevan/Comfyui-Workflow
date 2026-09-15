"""Run a small, reproducible H3 runtime ablation against a live ComfyUI API.

The benchmark keeps the shot, seed, profile, references, and model graph fixed;
only the attention backend changes.  It is intentionally an API-level benchmark
so the reported time includes the real ComfyUI queue and execution path.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import h3  # noqa: E402


VARIANT_OVERRIDES: dict[str, dict[str, Any]] = {
    "mainline": {},
    "pytorch": {"attention": {"backend": "default"}},
    "sage": {"attention": {"backend": "sage", "sage_attention": "auto", "allow_compile": False}},
}


def _load_case(shot_path: Path, profile_name: str) -> tuple[dict[str, Any], dict[str, Any], Path, list[dict[str, Any]], dict[str, Any], str]:
    shot = h3.load_document(shot_path)
    character_path = h3.find_character_manifest(shot["character"])
    character = h3.load_document(character_path)
    h3.validate_schema(character, ROOT / "schemas" / "character.schema.json", "character")
    h3.validate_schema(shot, ROOT / "schemas" / "shot.schema.json", "shot")
    h3.validate_shot_structure(shot, str(shot_path))
    if profile_name not in shot["generation"]:
        raise h3.HarnessError(f"profile not found: {profile_name}")
    refs = h3.selected_references(character, shot)
    profile = shot["generation"][profile_name]
    prompt = h3.compile_prompt(character, shot)
    return shot, character, character_path, refs, profile, prompt


def run_variant(shot_path: Path, profile_name: str, seed: int, api_url: str, timeout: float, variant: str) -> dict[str, Any]:
    shot, character, character_path, refs, profile, prompt = _load_case(shot_path, profile_name)
    runtime = h3.effective_runtime(VARIANT_OVERRIDES[variant])
    run_stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    run_id = f"bench-{run_stamp}-{shot['id']}-{profile_name}-{variant}-{seed}-{uuid.uuid4().hex[:6]}"
    image_names = h3.stage_references(character, refs, character_path)
    graph = h3.build_graph(
        prompt,
        refs,
        profile,
        seed,
        shot["duration"],
        f"video/{run_id}",
        image_names,
        runtime,
    )
    started = time.monotonic()
    try:
        response = h3.api_json(api_url, "/prompt", {"prompt": graph, "client_id": f"h3-benchmark-{run_id}"})
        prompt_id = str(response.get("prompt_id") or "")
        if not prompt_id:
            raise h3.HarnessError(f"ComfyUI response did not contain prompt_id: {response}")
        outputs, wait_seconds = h3.wait_for_completion(api_url, prompt_id, timeout)
        output_paths = h3.resolve_outputs(outputs)
        if not output_paths:
            raise h3.HarnessError(f"completed prompt {prompt_id} but no output video was found")
        status = "completed"
        error = None
    except Exception as exc:  # Keep the report useful when one optional backend fails.
        prompt_id = None
        wait_seconds = None
        output_paths = []
        status = "failed"
        error = str(exc)

    classes = [node.get("class_type") for node in graph.values() if isinstance(node, dict)]
    result: dict[str, Any] = {
        "variant": variant,
        "status": status,
        "error": error,
        "prompt_id": prompt_id,
        "seed": seed,
        "profile": profile_name,
        "runtime": runtime,
        "sampler": graph.get("123", {}).get("inputs", {}).get("sampler_name"),
        "scheduler": graph.get("124", {}).get("inputs", {}).get("scheduler"),
        "node_classes": {
            "MiniMaxH3SigmaShift": classes.count("MiniMaxH3SigmaShift"),
            "ModelAttentionBackend": classes.count("ModelAttentionBackend"),
            "PathchSageAttentionKJ": classes.count("PathchSageAttentionKJ"),
            "MiniMaxH3MemoryEfficientSageAttentionPatch": classes.count("MiniMaxH3MemoryEfficientSageAttentionPatch"),
            "AGSoftMiniMaxH3Cache": classes.count("AGSoftMiniMaxH3Cache"),
        },
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "wait_seconds": None if wait_seconds is None else round(wait_seconds, 3),
        "output_video": output_paths,
        "measured_at": datetime.now(timezone.utc).isoformat(),
    }
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("shot", help="shot manifest, relative to the repository root")
    parser.add_argument("--api-url", default="http://127.0.0.1:8189")
    parser.add_argument("--profile", choices=["explore", "keep"], default="explore")
    parser.add_argument("--seed", type=int, default=424242)
    parser.add_argument("--timeout", type=float, default=3600)
    parser.add_argument("--variants", nargs="+", choices=sorted(VARIANT_OVERRIDES), default=["mainline", "pytorch", "sage"])
    parser.add_argument("--output", type=Path, help="report path; defaults to benchmarks/h3-runtime-ablation-<timestamp>.json")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    shot_path = (ROOT / args.shot).resolve()
    report_path = args.output or ROOT / "benchmarks" / f"h3-runtime-ablation-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
    report: dict[str, Any] = {
        "shot": shot_path.relative_to(ROOT).as_posix(),
        "api_url": args.api_url,
        "profile": args.profile,
        "seed": args.seed,
        "variants": [],
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    for variant in args.variants:
        print(f"running {variant} ...", flush=True)
        result = run_variant(shot_path, args.profile, args.seed, args.api_url, args.timeout, variant)
        report["variants"].append(result)
        print(json.dumps(result, ensure_ascii=False), flush=True)
    h3.write_json(report_path, report)
    print(f"report: {report_path.relative_to(ROOT).as_posix()}")
    return 0 if all(item["status"] == "completed" for item in report["variants"]) else 2


if __name__ == "__main__":
    raise SystemExit(main())
