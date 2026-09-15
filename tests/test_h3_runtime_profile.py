import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import h3  # noqa: E402


def _refs():
    return [
        {"id": "primary", "file": "primary.png", "role": "identity", "picture_label": "Picture 1"},
        {"id": "face", "file": "face.png", "role": "face", "picture_label": "Picture 2"},
    ]


def _profile():
    return {"megapixels": 0.5, "steps": 4, "turbo": True, "takes": 1}


def test_default_graph_uses_reference_workflow_runtime_path():
    graph = h3.build_graph("prompt", _refs(), _profile(), 1, 5, "video/default", ["primary.png", "face.png"])
    assert graph["136"]["inputs"]["ref_image_size"] == "match"
    assert graph["123"]["inputs"]["sampler_name"] == "euler"
    assert graph["124"]["inputs"]["scheduler"] == "simple"
    types = [node.get("class_type") for node in graph.values()]
    assert "MiniMaxH3SigmaShift" in types
    assert "ModelAttentionBackend" in types
    assert "PathchSageAttentionKJ" not in types
    assert not any(node.get("class_type") == "AGSoftMiniMaxH3Cache" for node in graph.values())


def test_effective_runtime_merges_nested_overrides():
    runtime = h3.effective_runtime({"attention": {"backend": "sage"}, "sampler": "res_multistep"})
    assert runtime["ref_image_size"] == "match"
    assert runtime["sampler"] == "res_multistep"
    assert runtime["scheduler"] == "simple"
    assert runtime["model_shift"]["enabled"] is True
    assert runtime["attention"]["backend"] == "sage"
    assert runtime["attention"]["allow_compile"] is False


def test_reference_runtime_profile_inserts_borrowed_nodes():
    graph = h3.build_graph(
        "prompt",
        _refs(),
        _profile(),
        1,
        5,
        "video/reference-profile",
        ["primary.png", "face.png"],
        {
            "ref_image_size": "match",
            "sampler": "euler",
            "scheduler": "simple",
            "model_shift": {"enabled": True, "shift_video": 12, "shift_audio": 3},
            "attention": {"backend": "sage", "sage_attention": "auto", "allow_compile": False},
            "cache": {"enabled": True, "profile": "Balanced"},
        },
    )
    assert graph["136"]["inputs"]["ref_image_size"] == "match"
    assert graph["123"]["inputs"]["sampler_name"] == "euler"
    assert graph["124"]["inputs"]["scheduler"] == "simple"
    types = [node.get("class_type") for node in graph.values()]
    assert "MiniMaxH3SigmaShift" in types
    assert "PathchSageAttentionKJ" in types
    assert "MiniMaxH3MemoryEfficientSageAttentionPatch" in types
    assert "AGSoftMiniMaxH3Cache" in types
    assert graph["141"]["inputs"]["on_false"][0] != "127"
    assert graph["145"]["inputs"]["model"][0] == graph["141"]["inputs"]["on_false"][0]
