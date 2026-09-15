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
    # Keep the first occurrence for legacy manifests that reused an id such as
    # `face`; later occurrences remain addressable as face_2, face_3, ... .
    by_id = reference_lookup(character)
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


def reference_lookup(character: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Index references and give legacy duplicate ids deterministic aliases."""
    by_id: dict[str, dict[str, Any]] = {}
    counts: dict[str, int] = {}
    for item in character["references"]:
        ref_id = item["id"]
        counts[ref_id] = counts.get(ref_id, 0) + 1
        key = ref_id if counts[ref_id] == 1 else f"{ref_id}_{counts[ref_id]}"
        by_id[key] = item
    return by_id


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
    action = " ".join(str((shot.get("action") or {}).get("description", "")).split())
    background = character["background_policy"]["description"]
    mode = shot.get("reference_mode", "first_frame")
    free_mode = mode in {"free", "reference_generation", "storyboard"}
    picture_list = ", ".join(f"<{ref['picture_label']}>" for ref in references)
    if free_mode:
        subject_definitions = (
            f"<Subject 1> is the {identity['gender']} {identity['style']} character whose appearance is derived from {picture_list}. "
            f"Preserve {features}, stable facial proportions, colors, and linework. The selected pictures are appearance references only and are not fixed video frames.\n"
            f"{ref_definitions}\n"
            f"<Subject 2> is {background} with no props, scenery, extra characters, particles, text, or watermark."
        )
    else:
        subject_definitions = (
            f"<Subject 1> is the {identity['gender']} {identity['style']} character defined jointly by the selected reference pictures. "
            f"Preserve {features}, stable facial proportions, colors, and linework.\n"
            f"{ref_definitions}\n"
            f"<Subject 2> is {background} with no props, scenery, extra characters, particles, text, or watermark."
        )
    opening = shot.get("opening") or {}
    opening_text = ""
    if opening:
        opening_text = f"Opening state: {opening.get('description', '')}"
        if opening.get("framing"):
            opening_text += f" Framing: {opening['framing']}."
        if opening.get("view"):
            opening_text += f" View: {opening['view']}."
    beats = shot.get("beats") or []
    timeline = "\n".join(f"{beat['start']}-{beat['end']}s: {beat['description']}" for beat in beats)
    if not timeline:
        timeline = f"Action: {action}"
    ending = (shot.get("ending") or {}).get("description")
    constraints = shot.get("constraints") or []
    detailed = ". ".join(part.strip(". ") for part in [opening_text, f"The camera uses a {camera['speed']} {camera['amplitude']} {camera['type']}", f"Timeline:\n{timeline}" if beats else timeline, f"Ending state: {ending}" if ending else "", f"Constraints: {'; '.join(constraints)}" if constraints else ""] if part).strip() + ". Keep the character's identity, face, eyes, hair, clothing, and body proportions stable. No scene cut, no camera orbit, no extra characters, no exposure, no adult content, no props, no complex scenery, no subtitles, no visible text, and no watermark. <Subject 2> remains unchanged throughout."
    if mode == "first_frame":
        detailed += " The shot begins from <Picture 1>."
    elif mode == "last_frame":
        detailed += " The shot ends at <Picture 1>."
    elif mode == "keyframe":
        detailed += " Treat only the explicitly described picture moment as a keyframe; do not force other pictures to be video frames."
    if free_mode:
        summary = f"[reference generation] Generate one continuous {duration}-second single-character shot. Use the selected pictures for identity, appearance, and semantic reference only; design the opening composition and motion described below without forcing any picture to be a video frame."
    elif mode == "last_frame":
        summary = f"[keyframe completion] Generate one continuous {duration}-second shot that resolves to <Picture 1> as the final frame while preserving <Subject 1>."
    elif mode == "keyframe":
        summary = f"[keyframe completion] Generate one continuous {duration}-second shot using the selected picture references at the explicitly described keyframe moments."
    else:
        summary = f"[keyframe completion] Generate one continuous {duration}-second single-character shot beginning from <Picture 1>. Preserve <Subject 1> while adding the controlled performance described below."
    return "\n\n".join(
        [
            "subject_definitions:\n" + subject_definitions,
            "summary:\n" + summary,
            "retention_analysis:\n<Subject 1> (appears in [Shot 1]): fully_preserved - preserve identity, face, eyes, hair, clothing, proportions, colors, and linework.\n"
            + ref_retention
            + "\n<Subject 2> (appears in [Shot 1]): fully_preserved - keep the background unchanged.",
            "detailed_description:\n" + detailed,
            "overall_soundscape:\nN/A. Do not generate dialogue, singing, effects, or environmental ambience.",
            "non_diegetic_music:\nN/A. Treat the deliverable as silent.",
        ]
    )


def compile_prompt_from_paths(character_path: Path, shot_path: Path, loader) -> str:
    return compile_prompt(loader(character_path), loader(shot_path))
