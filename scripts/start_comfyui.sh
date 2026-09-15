#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="${REPO_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
LISTEN="${LISTEN:-127.0.0.1}"
PORT="${PORT:-8189}"
COMFY_ROOT="$REPO_ROOT/ComfyUI"
INPUT_DIR="$REPO_ROOT/input"
OUTPUT_DIR="$REPO_ROOT/output"
TEMP_DIR="$REPO_ROOT/temp"
MODEL_CONFIG="$REPO_ROOT/configs/extra_model_paths.yaml"

mkdir -p "$INPUT_DIR" "$OUTPUT_DIR/video" "$OUTPUT_DIR/frames/pending" "$OUTPUT_DIR/frames/accepted" "$OUTPUT_DIR/frames/rejected" "$OUTPUT_DIR/qc" "$TEMP_DIR" "$REPO_ROOT/logs" "$REPO_ROOT/runs"
test -f "$COMFY_ROOT/main.py"
test -f "$MODEL_CONFIG"
export PYTHONPATH="$REPO_ROOT/runtime/venv/Lib/site-packages:$COMFY_ROOT${PYTHONPATH:+:$PYTHONPATH}"

ARGS=(main.py --listen "$LISTEN" --port "$PORT" --input-directory "$INPUT_DIR" --output-directory "$OUTPUT_DIR" --temp-directory "$TEMP_DIR" --extra-model-paths-config "$MODEL_CONFIG")
if [[ "${LOW_VRAM:-0}" == "1" ]]; then ARGS+=(--lowvram); fi
if [[ "${CPU_VAE:-0}" == "1" ]]; then ARGS+=(--cpu-vae); fi
cd "$COMFY_ROOT"
exec "$PYTHON_BIN" "${ARGS[@]}"
