import copy
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import h3  # noqa: E402
from h3_prompt import compile_prompt, selected_references  # noqa: E402


def character_with_refs(count: int) -> dict:
    refs = [{"id": f"ref{i}", "file": f"assets/ref{i}.png", "role": f"role {i}", "picture_label": f"Picture {i}"} for i in range(1, count + 1)]
    return {"id": "test", "display_name": "Test", "references": refs, "identity": {"gender": "adult", "style": "2D", "invariant_features": ["blue hair"]}, "background_policy": {"type": "neutral", "description": "a plain background"}}


def shot_for(character: dict, count: int) -> dict:
    return {"id": "shot", "character": character["id"], "references": [f"ref{i}" for i in range(1, count + 1)], "duration": 5, "action": {"description": "holds a pose"}, "camera": {"type": "push_in", "amplitude": "small", "speed": "slow"}, "audio": {"policy": "silent"}, "generation": {"explore": {"megapixels": 0.5, "steps": 4, "turbo": True, "takes": 4}, "keep": {"megapixels": 0.75, "steps": 8, "turbo": True, "takes": 1}}}


def test_character_schema():
    document = h3.load_document(ROOT / "characters" / "nun.yaml")
    h3.validate_schema(document, ROOT / "schemas" / "character.schema.json", "character")


def test_shot_schema():
    document = h3.load_document(ROOT / "shots" / "nun" / "shot01_idle.yaml")
    h3.validate_schema(document, ROOT / "schemas" / "shot.schema.json", "shot")


@pytest.mark.parametrize("count", [1, 3, 9])
def test_prompt_picture_mapping(count):
    character = character_with_refs(count)
    prompt = compile_prompt(character, shot_for(character, count))
    for index in range(1, count + 1):
        assert f"Picture {index}" in prompt
        assert f"role {index}" in prompt
    if count < 9:
        assert f"Picture {count + 1}" not in prompt


def test_workflow_contract_fail_fast():
    graph = json.loads((ROOT / "workflows" / "h3_ref2va_template_api.json").read_text(encoding="utf-8"))
    h3.validate_workflow_contract(graph)
    broken = copy.deepcopy(graph)
    broken["115"]["class_type"] = "WrongNode"
    with pytest.raises(h3.HarnessError, match="fail fast"):
        h3.validate_workflow_contract(broken)


def test_fake_api_history_response():
    outputs, error, files = h3._history_result({"p1": {"status": {"completed": True, "status_str": "success"}, "outputs": {"92": {"gifs": [{"filename": "video.mp4", "subfolder": "", "type": "output"}]}}}}, "p1")
    assert (outputs, error) == ("completed", None)
    assert files[0]["filename"] == "video.mp4"


def test_output_path_and_seed_reproducibility_metadata():
    character = character_with_refs(1)
    refs = selected_references(character, shot_for(character, 1))
    profile = shot_for(character, 1)["generation"]["keep"]
    first = h3.build_graph("prompt", refs, profile, 734112, 5, "video/run-a", ["ref.png"])
    second = h3.build_graph("prompt", refs, profile, 734112, 5, "video/run-a", ["ref.png"])
    assert first["92"]["inputs"]["filename_prefix"] == "video/run-a"
    assert first["129"]["inputs"]["noise_seed"] == second["129"]["inputs"]["noise_seed"] == 734112


def test_run_manifest(tmp_path):
    path = tmp_path / "run.json"
    data = {"run_id": "r", "seed": 734112, "status": "queued", "references": [], "workflow_sha256": "abc", "prompt_sha256": "def"}
    h3.write_json(path, data)
    assert json.loads(path.read_text(encoding="utf-8"))["seed"] == 734112


def test_extract_duplicate_filter():
    np = pytest.importorskip("numpy")
    pytest.importorskip("cv2")
    from extract_keyframes import filter_duplicate_candidates

    base = np.zeros((64, 64, 3), dtype=np.uint8)
    base[15:45, 15:45] = 120
    different = base.copy()
    different[:, :8] = 255
    candidates = [{"frame": 0, "sharpness": 20, "image": base}, {"frame": 1, "sharpness": 30, "image": base.copy()}, {"frame": 2, "sharpness": 25, "image": different}]
    selected = filter_duplicate_candidates(candidates)
    assert len(selected) < len(candidates)
    assert selected[0]["duplicate_score"] == 0.0
