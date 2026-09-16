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
ATOM_REGISTRY_PATH = LIBRARY_ROOT / "atoms" / "registry.yaml"
ATOM_REGISTRY_SCHEMA_PATH = LIBRARY_ROOT / "schema" / "atom-registry.schema.json"
COMPILED_ATOM_PATH = LIBRARY_ROOT / "compiled" / "action_atoms_h3.json"
ACTION_AUDIT_PATH = LIBRARY_ROOT / "compiled" / "action_audit.json"
ATOM_SCHEMA_PATH = LIBRARY_ROOT / "schema" / "action-atom.schema.json"

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


def load_atom_registry() -> dict[str, Any]:
    """Load and validate the canonical dimension registry and composition rules."""
    if not ATOM_REGISTRY_PATH.is_file():
        raise LibraryError(f"missing atom registry: {_relative(ATOM_REGISTRY_PATH)}")
    registry = load_document(ATOM_REGISTRY_PATH)
    try:
        validate_schema(registry, ATOM_REGISTRY_SCHEMA_PATH, "NSFW atom registry")
    except HarnessError as exc:
        raise LibraryError(str(exc)) from exc
    dimensions = set(registry["dimension_order"])
    definitions = registry["definitions"]
    definition_ids = [str(item["id"]) for item in definitions]
    if len(definition_ids) != len(set(definition_ids)):
        raise LibraryError("atom registry contains duplicate definition ids")
    for item in definitions:
        if item["dimension"] not in dimensions:
            raise LibraryError(f"atom definition uses unknown dimension: {item['id']}")
        if not item["id"].startswith(f"{item['dimension']}."):
            raise LibraryError(f"atom id does not match its dimension: {item['id']}")
    known = set(definition_ids)
    composition = registry["composition"]
    for atom_id in composition["default_atoms"]:
        if atom_id not in known:
            raise LibraryError(f"composition default references unknown atom: {atom_id}")
    for rule in composition["conflict_rules"]:
        for atom_id in rule:
            if atom_id not in known:
                raise LibraryError(f"composition conflict references unknown atom: {atom_id}")
    for rule in composition["visibility_rules"]:
        for atom_id in rule["if"] + rule["require_any"]:
            if atom_id not in known:
                raise LibraryError(f"composition visibility rule references unknown atom: {atom_id}")
    for rule in composition["transition_exceptions"]:
        for atom_id in rule:
            if atom_id not in known:
                raise LibraryError(f"composition transition references unknown atom: {atom_id}")
    for example in composition["examples"]:
        for atom_id in example["atoms"]:
            if atom_id not in known:
                raise LibraryError(f"composition example references unknown atom: {atom_id}")
    return registry


def compose_atoms(atom_ids: list[str], temporal: bool = False) -> dict[str, Any]:
    """Compose canonical atoms into an H3 fragment while enforcing registry rules."""
    registry = load_atom_registry()
    definitions = {str(item["id"]): item for item in registry["definitions"]}
    selected = list(dict.fromkeys(atom_ids))
    if not selected:
        raise LibraryError("compose requires at least one atom id")
    if len(selected) > int(registry["composition"]["max_atoms_per_shot"]):
        raise LibraryError("composition exceeds max_atoms_per_shot")
    unknown = sorted(set(selected) - set(definitions))
    if unknown:
        raise LibraryError(f"compose references unknown atom(s): {', '.join(unknown)}")

    by_dimension: dict[str, list[str]] = {}
    for atom_id in selected:
        dimension = str(definitions[atom_id]["dimension"])
        by_dimension.setdefault(dimension, []).append(atom_id)
    one_of = set(registry["composition"]["one_of_dimensions"])
    for dimension in sorted(one_of):
        values = by_dimension.get(dimension, [])
        if len(values) > 1:
            raise LibraryError(f"compose allows only one {dimension} atom: {', '.join(values)}")

    selected_set = set(selected)
    transition_pairs = {frozenset(pair) for pair in registry["composition"]["transition_exceptions"]}
    for pair in registry["composition"]["conflict_rules"]:
        conflict = frozenset(pair)
        if conflict.issubset(selected_set) and not (temporal and conflict in transition_pairs):
            raise LibraryError(f"compose contains conflicting atoms: {pair[0]} + {pair[1]}")
    for rule in registry["composition"]["visibility_rules"]:
        if set(rule["if"]).issubset(selected_set) and not selected_set.intersection(rule["require_any"]):
            required = ", ".join(rule["require_any"])
            raise LibraryError(f"compose violates visibility rule; add one of: {required}")

    ordered = []
    for dimension in registry["dimension_order"]:
        ordered.extend(by_dimension.get(dimension, []))
    phrases = {str(item["id"]): str(item["h3_phrase"]) for item in registry["definitions"]}
    prompt_parts = [
        "Generate one continuous H3 sequence for clearly adult fictional subjects in an explicitly consensual context.",
    ]
    for atom_id in ordered:
        prompt_parts.append(f"{definitions[atom_id]['dimension']}: {phrases[atom_id]}.")
    prompt_parts.append(
        "Preserve identity, anatomy, camera continuity, and reference semantics. "
        "Do not introduce minors, real people, non-consensual activity, or sexual violence."
    )
    return {
        "schema_version": 1,
        "temporal": temporal,
        "atoms": ordered,
        "dimensions": by_dimension,
        "h3_prompt": " ".join(prompt_parts),
    }


def load_compiled_atom_library() -> list[dict[str, Any]]:
    """Load structured H3 atoms and verify source traceability and registry references."""
    if not COMPILED_ATOM_PATH.is_file():
        raise LibraryError(f"missing compiled atom library: {_relative(COMPILED_ATOM_PATH)}")
    try:
        atoms = json.loads(COMPILED_ATOM_PATH.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LibraryError(f"compiled atom library is not valid JSON: {exc}") from exc
    raw_actions = load_action_library()
    registry = load_atom_registry()
    known = {str(item["id"]) for item in registry["definitions"]}
    if not isinstance(atoms, list) or len(atoms) != len(raw_actions):
        raise LibraryError(f"compiled atom count mismatch: expected {len(raw_actions)}")
    seen_labels: set[str] = set()
    for atom in atoms:
        if not isinstance(atom, dict) or not isinstance(atom.get("label"), str):
            raise LibraryError("compiled atom is missing a string label")
        label = atom["label"]
        if label in seen_labels or label not in raw_actions:
            raise LibraryError(f"compiled atom label is missing or duplicated: {label}")
        seen_labels.add(label)
        if atom.get("source", {}).get("raw_value") != raw_actions[label]:
            raise LibraryError(f"compiled atom source mismatch: {label}")
        try:
            validate_schema(atom, ATOM_SCHEMA_PATH, f"NSFW action atom {label}")
        except HarnessError as exc:
            raise LibraryError(str(exc)) from exc
        for dimension, values in atom["dimensions"].items():
            for atom_id in values:
                if atom_id not in known:
                    raise LibraryError(f"{label} references unknown {dimension} atom: {atom_id}")
        if not atom["semantic_fingerprint"]:
            raise LibraryError(f"compiled atom has empty semantic fingerprint: {label}")
    return atoms


def validate_compiled_atom_library() -> int:
    """Validate and return the number of structured H3 atom records."""
    return len(load_compiled_atom_library())


def load_action_audit() -> dict[str, Any]:
    """Load the deterministic audit summary generated with the atom compiler."""
    if not ACTION_AUDIT_PATH.is_file():
        raise LibraryError(f"missing action audit: {_relative(ACTION_AUDIT_PATH)}")
    try:
        audit = json.loads(ACTION_AUDIT_PATH.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LibraryError(f"action audit is not valid JSON: {exc}") from exc
    source = audit.get("source") or {}
    raw_actions = load_action_library()
    if source.get("entry_count") != len(raw_actions):
        raise LibraryError("action audit entry count is stale")
    if source.get("unique_exact_values") != len(set(raw_actions.values())):
        raise LibraryError("action audit exact-duplicate count is stale")
    return audit


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
    validate_compiled_atom_library()
    load_action_audit()

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


def cmd_atom_info(_: argparse.Namespace) -> None:
    atoms = load_compiled_atom_library()
    registry = load_atom_registry()
    audit = load_action_audit()
    print(f"valid: {len(atoms)} structured atom(s), {len(registry['definitions'])} canonical definition(s)")
    print(json.dumps(audit["source"], ensure_ascii=False, indent=2))
    print(json.dumps(audit["review_counts"], ensure_ascii=False, indent=2))


def cmd_atom_list(args: argparse.Namespace) -> None:
    atoms = load_compiled_atom_library()
    for atom in atoms:
        if args.dimension and not any(atom["dimensions"].get(args.dimension, [])):
            continue
        if args.review and atom["review"]["status"] != args.review:
            continue
        action = atom["dimensions"]["action"][0]
        print(f"{atom['label']}\t{atom['review']['status']}\t{action}\t{atom['semantic_fingerprint']}")


def cmd_atom_show(args: argparse.Namespace) -> None:
    atoms = load_compiled_atom_library()
    atom = next((item for item in atoms if item["label"] == args.name), None)
    if atom is None:
        raise LibraryError(f"atom not found with exact case-sensitive name: {args.name}")
    if args.prompt:
        print(atom["h3"]["prompt_fragment"])
    else:
        print(json.dumps(atom, ensure_ascii=False, indent=2))


def cmd_compose(args: argparse.Namespace) -> None:
    atom_ids = [item.strip() for item in args.atoms.split(",") if item.strip()]
    result = compose_atoms(atom_ids, args.temporal)
    if args.prompt:
        print(result["h3_prompt"])
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2))


def cmd_audit(_: argparse.Namespace) -> None:
    audit = load_action_audit()
    print(json.dumps(audit, ensure_ascii=False, indent=2))


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
    sub.add_parser("atom-info").set_defaults(func=cmd_atom_info)
    atom_list = sub.add_parser("atom-list")
    atom_list.add_argument("--dimension", choices=["action", "interaction", "pose", "prop", "appearance", "expression", "physiology", "camera", "setting", "motion", "effects", "audio"])
    atom_list.add_argument("--review", choices=["candidate", "manual_review", "blocked"])
    atom_list.set_defaults(func=cmd_atom_list)
    atom_show = sub.add_parser("atom-show")
    atom_show.add_argument("name")
    atom_show.add_argument("--prompt", action="store_true", help="show the H3 prompt fragment only")
    atom_show.set_defaults(func=cmd_atom_show)
    compose = sub.add_parser("compose")
    compose.add_argument("--atoms", required=True, help="comma-separated canonical atom ids")
    compose.add_argument("--temporal", action="store_true", help="allow registered sequential transition exceptions")
    compose.add_argument("--prompt", action="store_true", help="show the H3 prompt only")
    compose.set_defaults(func=cmd_compose)
    sub.add_parser("audit").set_defaults(func=cmd_audit)
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
