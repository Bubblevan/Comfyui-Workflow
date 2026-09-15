import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import nsfw_library  # noqa: E402


@pytest.fixture
def local_tmp():
    with tempfile.TemporaryDirectory(dir=ROOT / "temp") as directory:
        yield Path(directory)


def test_nsfw_library_validates():
    entries, recipes = nsfw_library.validate_library()
    assert entries == 6
    assert recipes == 1
    assert nsfw_library.validate_workflow_registry() == 4
    assert nsfw_library.validate_action_import() == 654
    assert nsfw_library.validate_compiled_action_library() == 654


def test_action_content_is_transformed_to_h3_sections():
    card = next(item for item in nsfw_library.load_compiled_action_library() if item["label"] == "sex")
    assert "detailed_description:" in card["h3"]["prompt"]
    assert card["h3"]["prompt"] != card["source"]["raw_value"]
    assert card["shot_fragment"]["beats"][0]["description"]


def test_nsfw_entries_are_adult_only_and_consensual():
    for path in nsfw_library.entry_paths():
        entry = nsfw_library.load_document(path)
        assert entry["safety"]["adult_only"] is True
        assert entry["safety"]["fictional_only"] is True
        assert entry["safety"]["consent_model"] == "explicit_roleplay"


def test_materialize_recipe(local_tmp):
    target = local_tmp / "shot.yaml"
    result = nsfw_library.materialize_recipe(
        "shot_hypnosis_eye_transition",
        "nun",
        ["primary", "face"],
        target,
    )
    assert result == target
    data = nsfw_library.load_document(target)
    assert data["character"] == "nun"
    assert data["references"] == ["primary", "face"]
    assert data["id"] == "shot_hypnosis_eye_transition"


def test_materialize_does_not_overwrite(local_tmp):
    target = local_tmp / "shot.yaml"
    target.write_text("existing\n", encoding="utf-8")
    with pytest.raises(nsfw_library.LibraryError, match="refusing to overwrite"):
        nsfw_library.materialize_recipe("shot_hypnosis_eye_transition", "nun", ["primary"], target)
