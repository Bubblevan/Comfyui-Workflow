"""Compile character and shot manifests into the six-section H3 Ref2VA prompt."""

from __future__ import annotations

from pathlib import Path
from typing import Any


SECTION_NAMES = (
    "subject_definitions",
    "summary",
    "retention_analysis",
    "detailed_description",
    "overall_soundscape",
    "non_diegetic_music",
)


def selected_references(character: dict[str, Any], shot: dict[str, Any]) -> list[dict[str, Any]]:
    """Return only references named by the shot, preserving character order."""
    by_id = {item["id"]: item for item in character["references"]}
    selected_ids = shot.get("references") or [item["id"] for item in character["references"]]
    missing = [ref_id for ref_id in selected_ids if ref_id not in by_id]
    if missing:
        raise ValueError(f"shot references are not defined by character: {', '.join(missing)}")
    if not 1 <= len(selected_ids) <= 9:
        raise ValueError("Ref2VA requires between 1 and 9 selected references")
    refs = [by_id[ref_id].copy() for ref_id in selected_ids]
    for index, ref in enumerate(refs, 1):
        # Picture labels are assigned by usage, not by a character's unused references.
        ref["picture_label"] = f"Picture {index}"
    return refs


def _reference_lines(references: list[dict[str, Any]]) -> tuple[str, str]:
    definitions: list[str] = []
    retention: list[str] = []
    for ref in references:
        label = ref["picture_label"]
        role = ref["role"]
        description = ref.get("description") or role
        definitions.append(f"{label} is the {role} reference: {description}.")
        retention.append(
            f"{label} ({role} for [Shot 1]): fully_preserved - keep its semantic role consistent throughout the shot."
        )
    return "\n".join(definitions), "\n".join(retention)


def compile_prompt(character: dict[str, Any], shot: dict[str, Any]) -> str:
    """Compile the official six-field layout without character-specific logic."""
    references = selected_references(character, shot)
    template_path = Path(__file__).resolve().parents[1] / "templates" / "h3_ref2va_prompt.j2"
    try:
        from jinja2 import Environment, StrictUndefined  # type: ignore

        template = Environment(undefined=StrictUndefined, trim_blocks=True, lstrip_blocks=True).from_string(template_path.read_text(encoding="utf-8"))
        return template.render(character=character, shot=shot, references=references).strip()
    except ImportError:
        # The deterministic fallback below keeps the CLI usable with stdlib-only Python.
        pass
    identity = character["identity"]
    features = ", ".join(identity["invariant_features"])
    ref_definitions, ref_retention = _reference_lines(references)
    duration = shot["duration"]
    camera = shot["camera"]
    action = " ".join(str(shot["action"]["description"]).split())
    background = character["background_policy"]["description"]
    subject_definitions = (
        f"<Subject 1> is the {identity['gender']} {identity['style']} character defined jointly by the selected reference pictures. "
        f"Preserve {features}, stable facial proportions, colors, and linework.\n"
        f"{ref_definitions}\n"
        f"<Subject 2> is {background} with no props, scenery, extra characters, particles, text, or watermark."
    )
    return "\n\n".join(
        [
            "subject_definitions:\n" + subject_definitions,
            f"summary:\n[reference-to-video] Generate one continuous {duration}-second single-character shot anchored by <Picture 1>. Preserve <Subject 1> while adding only one small controlled performance.",
            "retention_analysis:\n<Subject 1> (appears in [Shot 1]): fully_preserved - preserve identity, face, eyes, hair, clothing, proportions, colors, and linework.\n"
            + ref_retention
            + "\n<Subject 2> (appears in [Shot 1]): fully_preserved - keep the background unchanged.",
            f"detailed_description:\nThe shot begins from <Picture 1>. The camera uses a {camera['speed']} {camera['amplitude']} {camera['type']}. {action} Keep the character's identity, face, eyes, hair, clothing, and body proportions stable. No scene cut, no camera orbit, no extra characters, no exposure, no adult content, no props, no complex scenery, no subtitles, no visible text, and no watermark. <Subject 2> remains unchanged throughout.",
            "overall_soundscape:\nN/A. Do not generate dialogue, singing, effects, or environmental ambience.",
            "non_diegetic_music:\nN/A. Treat the deliverable as silent.",
        ]
    )


def compile_prompt_from_paths(character_path: Path, shot_path: Path, loader) -> str:
    return compile_prompt(loader(character_path), loader(shot_path))
