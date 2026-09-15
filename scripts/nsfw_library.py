"""Validate and materialize the local MiniMax H3 adult prompt-card library."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
LIBRARY_ROOT = ROOT / "library" / "nsfw"
CATALOG_PATH = LIBRARY_ROOT / "catalog.yaml"
SCHEMA_PATH = LIBRARY_ROOT / "schema" / "entry.schema.json"
SHOT_SCHEMA_PATH = ROOT / "schemas" / "shot.schema.json"
WORKFLOW_ROOT = LIBRARY_ROOT / "workflows" / "stefan_h3_v22"
WORKFLOW_REGISTRY_PATH = LIBRARY_ROOT / "workflows" / "registry.yaml"
IMPORT_ROOT = LIBRARY_ROOT / "imports"
IMPORT_REGISTRY_PATH = IMPORT_ROOT / "registry.yaml"
COMPILED_ACTION_PATH = LIBRARY_ROOT / "compiled" / "action_cards_h3.json"

sys.path.insert(0, str(Path(__file__).resolve().parent))
from h3 import HarnessError, load_document, validate_schema  # noqa: E402


class LibraryError(RuntimeError):
    """Raised when a library document is invalid or cannot be resolved."""


def entry_paths() -> list[Path]:
    return sorted((LIBRARY_ROOT / "entries").glob("**/*.yaml"))


def recipe_paths() -> list[Path]:
    return sorted((LIBRARY_ROOT / "recipes").glob("**/*.yaml"))


def _relative(path: Path) -> str:
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def _entry_by_id() -> dict[str, tuple[Path, dict[str, Any]]]:
    result: dict[str, tuple[Path, dict[str, Any]]] = {}
    for path in entry_paths():
        document = load_document(path)
        entry_id = str(document.get("id", ""))
        if entry_id in result:
            raise LibraryError(f"duplicate library entry id: {entry_id}")
        result[entry_id] = (path, document)
    return result


def _recipe_by_id() -> dict[str, tuple[Path, dict[str, Any]]]:
    result: dict[str, tuple[Path, dict[str, Any]]] = {}
    for path in recipe_paths():
        document = load_document(path)
        recipe_id = str(document.get("id", ""))
        if recipe_id in result:
            raise LibraryError(f"duplicate recipe id: {recipe_id}")
        result[recipe_id] = (path, document)
    return result


def _validate_entry_timeline(path: Path, entry: dict[str, Any]) -> None:
    beats = entry["prompt"]["beats"]
    previous_end = 0.0
    duration = float(entry["compatibility"]["recommended_duration"])
    for index, beat in enumerate(beats):
        start = float(beat["start"])
        end = float(beat["end"])
        if end <= start:
            raise LibraryError(f"{_relative(path)} beat {index} must have end > start")
        if start < previous_end:
            raise LibraryError(f"{_relative(path)} beats overlap or are out of order")
        if end > duration:
            raise LibraryError(f"{_relative(path)} beat {index} ends after recommended_duration")
        previous_end = end


def _validate_catalog(catalog: dict[str, Any]) -> None:
    if catalog.get("schema_version") != 1:
        raise LibraryError("library catalog schema_version must be 1")
    policy = catalog.get("policy") or {}
    required_policy = {
        "adult_only": True,
        "fictional_only": True,
        "consent_model": "explicit_roleplay",
    }
    for key, expected in required_policy.items():
        if policy.get(key) != expected:
            raise LibraryError(f"catalog policy.{key} must be {expected!r}")


def _source_ids() -> set[str]:
    path = LIBRARY_ROOT / "sources.yaml"
    if not path.is_file():
        raise LibraryError(f"missing source index: {_relative(path)}")
    document = load_document(path)
    if document.get("schema_version") != 1:
        raise LibraryError("library source index schema_version must be 1")
    sources = document.get("sources") or []
    return {str(source["id"]) for source in sources if source.get("id")}


def validate_workflow_registry() -> int:
    """Validate imported workflow files against their local byte/hash registry."""
    if not WORKFLOW_REGISTRY_PATH.is_file():
        raise LibraryError(f"missing workflow registry: {_relative(WORKFLOW_REGISTRY_PATH)}")
    registry = load_document(WORKFLOW_REGISTRY_PATH)
    if registry.get("schema_version") != 1:
        raise LibraryError("workflow registry schema_version must be 1")
    files = registry.get("files") or []
    if not files:
        raise LibraryError("workflow registry has no files")
    for item in files:
        path = WORKFLOW_ROOT / str(item["file"])
        if not path.is_file():
            raise LibraryError(f"missing workflow snapshot: {_relative(path)}")
        actual_bytes = path.stat().st_size
        actual_hash = hashlib.sha256(path.read_bytes()).hexdigest().upper()
        if actual_bytes != int(item["bytes"]):
            raise LibraryError(f"workflow byte-size mismatch: {_relative(path)}")
        if actual_hash != str(item["sha256"]).upper():
            raise LibraryError(f"workflow sha256 mismatch: {_relative(path)}")
    return len(files)


def load_action_library() -> dict[str, str]:
    """Load the migrated action dictionary without normalizing its keys or values."""
    if not IMPORT_REGISTRY_PATH.is_file():
        raise LibraryError(f"missing import registry: {_relative(IMPORT_REGISTRY_PATH)}")
    registry = load_document(IMPORT_REGISTRY_PATH)
    if registry.get("schema_version") != 1:
        raise LibraryError("import registry schema_version must be 1")
    imports = registry.get("imports") or []
    action = next((item for item in imports if item.get("id") == "isekai.action"), None)
    if not action:
        raise LibraryError("import registry has no isekai.action entry")
    path = IMPORT_ROOT / str(action["file"])
    if not path.is_file():
        raise LibraryError(f"missing migrated action file: {_relative(path)}")
    raw = path.read_bytes()
    actual_hash = hashlib.sha256(raw).hexdigest().upper()
    if len(raw) != int(action["bytes"]):
        raise LibraryError(f"action import byte-size mismatch: {_relative(path)}")
    if actual_hash != str(action["sha256"]).upper():
        raise LibraryError(f"action import sha256 mismatch: {_relative(path)}")
    try:
        data = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LibraryError(f"migrated action file is not valid UTF-8 JSON: {exc}") from exc
    if not isinstance(data, dict) or not all(isinstance(key, str) and isinstance(value, str) for key, value in data.items()):
        raise LibraryError("migrated action file must be a JSON object with string keys and values")
    if len(data) != int(action["entry_count"]):
        raise LibraryError(f"action import entry-count mismatch: expected {action['entry_count']}, got {len(data)}")
    return data


def validate_action_import() -> int:
    """Validate and return the number of migrated action entries."""
    return len(load_action_library())


def load_compiled_action_library() -> list[dict[str, Any]]:
    """Load H3 cards and verify that each card is traceable to the raw action map."""
    if not COMPILED_ACTION_PATH.is_file():
        raise LibraryError(f"missing compiled action library: {_relative(COMPILED_ACTION_PATH)}")
    try:
        cards = json.loads(COMPILED_ACTION_PATH.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LibraryError(f"compiled action library is not valid JSON: {exc}") from exc
    raw_actions = load_action_library()
    if not isinstance(cards, list) or len(cards) != len(raw_actions):
        raise LibraryError(f"compiled action count mismatch: expected {len(raw_actions)}")
    seen_labels: set[str] = set()
    for card in cards:
        if not isinstance(card, dict) or not isinstance(card.get("label"), str):
            raise LibraryError("compiled action card is missing a string label")
        label = card["label"]
        if label in seen_labels or label not in raw_actions:
            raise LibraryError(f"compiled action label is missing or duplicated: {label}")
        seen_labels.add(label)
        source = card.get("source") or {}
        h3 = card.get("h3") or {}
        if source.get("raw_value") != raw_actions[label]:
            raise LibraryError(f"compiled action source mismatch: {label}")
        required_sections = {
            "subject_definitions",
            "summary",
            "retention_analysis",
            "detailed_description",
            "overall_soundscape",
            "non_diegetic_music",
            "prompt",
        }
        if not required_sections.issubset(h3) or not all(isinstance(h3[key], str) and h3[key].strip() for key in required_sections):
            raise LibraryError(f"compiled action is missing H3 sections: {label}")
        if h3["prompt"] == raw_actions[label]:
            raise LibraryError(f"compiled action was not transformed from tags: {label}")
    return cards


def validate_compiled_action_library() -> int:
    """Validate and return the number of generated H3 action cards."""
    return len(load_compiled_action_library())


def validate_library() -> tuple[int, int]:
    """Validate all cards and recipes; return (entry_count, recipe_count)."""
    if not CATALOG_PATH.is_file():
        raise LibraryError(f"missing catalog: {_relative(CATALOG_PATH)}")
    catalog = load_document(CATALOG_PATH)
    _validate_catalog(catalog)
    source_ids = _source_ids()
    validate_workflow_registry()
    validate_action_import()
    validate_compiled_action_library()

    entries = _entry_by_id()
    catalog_entries = {item["id"]: item["path"] for item in catalog.get("entries", [])}
    if set(entries) != set(catalog_entries):
        missing = sorted(set(catalog_entries) - set(entries))
        extra = sorted(set(entries) - set(catalog_entries))
        raise LibraryError(f"catalog entry mismatch; missing={missing}, extra={extra}")

    for entry_id, (path, entry) in entries.items():
        try:
            validate_schema(entry, SCHEMA_PATH, f"NSFW entry {entry_id}")
        except HarnessError as exc:
            raise LibraryError(str(exc)) from exc
        missing_sources = sorted(set(entry["provenance"]["source_ids"]) - source_ids)
        if missing_sources:
            raise LibraryError(f"{entry_id} references unknown source ids: {', '.join(missing_sources)}")
        _validate_entry_timeline(path, entry)
        expected_path = (LIBRARY_ROOT / catalog_entries[entry_id]).resolve()
        if path.resolve() != expected_path:
            raise LibraryError(f"catalog path mismatch for {entry_id}: {_relative(path)}")

    recipes = _recipe_by_id()
    catalog_recipes = {item["id"]: item["path"] for item in catalog.get("recipes", [])}
    if set(recipes) != set(catalog_recipes):
        missing = sorted(set(catalog_recipes) - set(recipes))
        extra = sorted(set(recipes) - set(catalog_recipes))
        raise LibraryError(f"catalog recipe mismatch; missing={missing}, extra={extra}")

    for recipe_id, (path, recipe) in recipes.items():
        try:
            validate_schema(recipe, SHOT_SCHEMA_PATH, f"NSFW recipe {recipe_id}")
        except HarnessError as exc:
            raise LibraryError(str(exc)) from exc
        if recipe.get("character") != "__CHARACTER__":
            raise LibraryError(f"{_relative(path)} must use character placeholder __CHARACTER__")
        if not recipe.get("references"):
            raise LibraryError(f"{_relative(path)} must declare at least one reference")
        expected_path = (LIBRARY_ROOT / catalog_recipes[recipe_id]).resolve()
        if path.resolve() != expected_path:
            raise LibraryError(f"catalog path mismatch for {recipe_id}: {_relative(path)}")

    return len(entries), len(recipes)


def _resolve_card(card_id: str) -> tuple[str, Path, dict[str, Any]]:
    entries = _entry_by_id()
    if card_id in entries:
        path, document = entries[card_id]
        return "entry", path, document
    recipes = _recipe_by_id()
    if card_id in recipes:
        path, document = recipes[card_id]
        return "recipe", path, document
    raise LibraryError(f"library item not found: {card_id}")


def materialize_recipe(recipe_id: str, character: str, references: list[str], output: Path, force: bool = False) -> Path:
    kind, _, recipe = _resolve_card(recipe_id)
    if kind != "recipe":
        raise LibraryError(f"materialize requires a recipe id, got entry: {recipe_id}")
    if not character.strip():
        raise LibraryError("character must not be empty")
    if not references or any(not ref.strip() for ref in references):
        raise LibraryError("at least one non-empty reference is required")
    target = output if output.is_absolute() else ROOT / output
    if target.exists() and not force:
        raise LibraryError(f"refusing to overwrite existing file without --force: {_relative(target)}")
    materialized = copy.deepcopy(recipe)
    materialized["character"] = character
    materialized["references"] = references
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        import yaml  # type: ignore

        safe_dump = getattr(yaml, "safe_dump", None)
        if not callable(safe_dump):
            raise ImportError("PyYAML safe_dump is unavailable")
        target.write_text(safe_dump(materialized, allow_unicode=True, sort_keys=False), encoding="utf-8")
    except (ImportError, AttributeError):
        target.write_text(json.dumps(materialized, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return target


def cmd_validate(_: argparse.Namespace) -> None:
    entries, recipes = validate_library()
    print(f"valid: {entries} NSFW prompt card(s), {recipes} recipe(s)")


def cmd_list(args: argparse.Namespace) -> None:
    validate_library()
    entries = _entry_by_id()
    for entry_id in sorted(entries):
        _, entry = entries[entry_id]
        if args.category and entry["category"] != args.category:
            continue
        tags = ", ".join(entry["tags"])
        print(f"{entry_id}\t{entry['category']}\t{entry['title']}\t[{tags}]")


def cmd_show(args: argparse.Namespace) -> None:
    validate_library()
    kind, path, document = _resolve_card(args.item)
    print(f"# {kind}: {_relative(path)}")
    print(json.dumps(document, ensure_ascii=False, indent=2))


def cmd_materialize(args: argparse.Namespace) -> None:
    validate_library()
    target = materialize_recipe(args.recipe, args.character, [item.strip() for item in args.references.split(",")], Path(args.out), args.force)
    print(f"materialized: {_relative(target)}")


def cmd_workflow_info(_: argparse.Namespace) -> None:
    count = validate_workflow_registry()
    registry = load_document(WORKFLOW_REGISTRY_PATH)
    print(f"valid: {count} workflow snapshot(s) in {registry['snapshot_id']}")
    for item in registry["files"]:
        print(f"{item['id']}\t{item['role']}\t{item['bytes']} bytes\tsha256={item['sha256']}")


def cmd_action_info(_: argparse.Namespace) -> None:
    actions = load_action_library()
    cards = load_compiled_action_library()
    print(f"valid: {len(actions)} source action(s), {len(cards)} compiled H3 card(s)")


def cmd_action_list(args: argparse.Namespace) -> None:
    cards = load_compiled_action_library()
    needle = (args.contains or "").casefold()
    for name in sorted((card["label"] for card in cards), key=str.casefold):
        if not needle or needle in name.casefold():
            print(name)


def cmd_action_show(args: argparse.Namespace) -> None:
    cards = load_compiled_action_library()
    card = next((item for item in cards if item["label"] == args.name), None)
    if card is None:
        raise LibraryError(f"action not found with exact case-sensitive name: {args.name}")
    if args.raw:
        print(card["source"]["raw_value"])
    else:
        print(card["h3"]["prompt"])


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Local MiniMax H3 NSFW prompt-card library")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("validate").set_defaults(func=cmd_validate)
    sub.add_parser("workflow-info").set_defaults(func=cmd_workflow_info)
    sub.add_parser("action-info").set_defaults(func=cmd_action_info)
    action_list = sub.add_parser("action-list")
    action_list.add_argument("--contains")
    action_list.set_defaults(func=cmd_action_list)
    action_show = sub.add_parser("action-show")
    action_show.add_argument("name")
    action_show.add_argument("--raw", action="store_true", help="show the original source string instead of the H3 prompt")
    action_show.set_defaults(func=cmd_action_show)
    list_parser = sub.add_parser("list")
    list_parser.add_argument("--category", choices=["effect", "pose", "camera", "motion"])
    list_parser.set_defaults(func=cmd_list)
    show = sub.add_parser("show")
    show.add_argument("item")
    show.set_defaults(func=cmd_show)
    materialize = sub.add_parser("materialize")
    materialize.add_argument("recipe")
    materialize.add_argument("--character", required=True)
    materialize.add_argument("--references", required=True, help="comma-separated reference ids")
    materialize.add_argument("--out", required=True)
    materialize.add_argument("--force", action="store_true")
    materialize.set_defaults(func=cmd_materialize)
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        args = build_parser().parse_args(argv)
        args.func(args)
        return 0
    except (LibraryError, OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
