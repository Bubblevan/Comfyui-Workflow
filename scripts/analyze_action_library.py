"""Audit and compile the legacy action map into compositional MiniMax H3 atoms."""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, OrderedDict, defaultdict
from functools import lru_cache
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SOURCE_PATH = ROOT / "library" / "nsfw" / "imports" / "action.json"
OUTPUT_PATH = ROOT / "library" / "nsfw" / "compiled" / "action_atoms_h3.json"
AUDIT_PATH = ROOT / "library" / "nsfw" / "compiled" / "action_audit.json"
REGISTRY_PATH = ROOT / "library" / "nsfw" / "atoms" / "registry.yaml"

sys.path.insert(0, str(ROOT / "scripts"))
from h3 import load_document  # noqa: E402

QUALITY_MARKERS = {
    "hda", "masterpiece", "best quality", "good quality", "ultra", "raw photo",
    "8k", "highres", "absurdres", "uncensored", "professional lighting",
    "ultra detailed", "ultra-detailed",
}
NON_CONSENSUAL_MARKERS = {
    "rape", "after rape", "chikan", "molestation", "forced", "unconscious",
    "sleeping sex", "asphyxia", "drowning",
}
AGE_MARKERS = {
    "school", "school uniform", "young", "teen", "teenage", "child", "diaper",
    "nursing", "oyakodon",
}
RESTRAINT_MARKERS = {
    "bondage", "restrained", "hogtied", "gag", "choke", "choking", "leash",
    "shackles", "bound wrists", "bound ankles", "stationary restraints",
}
PARTNER_MARKERS = {
    "sex", "anal sex", "fellatio", "oral sex", "foot job", "hand job", "paizuri",
    "girl on top", "kiss", "hug", "embrace", "sucking", "breast sucking",
    "group sex", "threesome", "orgy", "penetration",
}
ADULT_ACTIVITY_MARKERS = {
    "sex", "anal", "fellatio", "oral", "paizuri", "masturb", "dildo", "vibrator",
    "toy", "pussy", "penis", "breast", "nipple", "vaginal", "clitoral", "insertion",
    "penetration", "orgasm", "cum", "creampie", "ejaculat", "suck", "lick", "futa",
    "hentai", "horny", "pubic", "sex machine", "tentacle", "slime sex",
}
SELF_MARKERS = {
    "masturbation", "object masturbation", "crotch rub", "pillow humping",
    "pillow humping", "dildo", "vibrator", "anal toy", "sex toy",
}
AFTERCARE_MARKERS = {"after sex", "after anal sex", "aftercare", "tired after"}
NONSEXUAL_MARKERS = {
    "wake up", "sleep", "showering", "washing body", "bath", "massage",
    "talking phone", "game playing", "playing game", "washing machine",
}
PROP_MARKERS = {
    "pillow", "dildo", "vibrator", "toy", "machine", "bottle", "banana",
    "zucchini", "carrot", "popsicle", "leek", "eggplant", "daikon", "corn",
    "candy cane", "lollipop", "pencil", "pen", "tube", "stick", "wand",
    "recorder", "flute", "microphone", "sword", "katana", "shovel", "broom",
    "staff", "traffic cone", "beads", "plug", "desk", "table", "chair",
}
SOURCE_NOISE_MARKERS = QUALITY_MARKERS | {
    "photo", "hda_tentaclesex", "hda_masterpiece", "lora", "artist", "style",
}
EXPRESSION_RULES: list[tuple[str, str]] = [
    ("hypnosis", "expression.hypnosis_transition"),
    ("ahegao", "expression.ahegao"),
    ("rolling eyes", "expression.rolling_eyes"),
    ("empty eyes", "expression.dazed_vacant"),
    ("vacant gaze", "expression.dazed_vacant"),
    ("closed eyes", "expression.dazed_vacant"),
    ("tongue out", "expression.tongue_out"),
    ("tongue", "expression.tongue_out"),
    ("blush", "expression.embarrassed_blush"),
    ("embarrassed", "expression.embarrassed_blush"),
    ("shy", "expression.embarrassed_blush"),
    ("pout", "expression.pout"),
    ("cat mouth", "expression.cat_mouth"),
    ("smile", "expression.anticipatory_smile"),
    ("looking at viewer", "expression.focused_eye_contact"),
]
POSE_RULES: list[tuple[str, str]] = [
    ("reverse upright straddle", "pose.straddling"),
    ("upright straddle", "pose.straddling"),
    ("straddling", "pose.straddling"),
    ("riding", "pose.straddling"),
    ("on back", "pose.lying_back"),
    ("lying", "pose.lying_back"),
    ("on stomach", "pose.lying_stomach"),
    ("on all fours", "pose.all_fours"),
    ("on all four", "pose.all_fours"),
    ("all fours", "pose.all_fours"),
    ("kneeling", "pose.kneeling"),
    ("sitting", "pose.seated"),
    ("sit", "pose.seated"),
    ("squatting", "pose.kneeling"),
    ("standing", "pose.standing"),
    ("legs up", "pose.legs_raised"),
    ("leg up", "pose.legs_raised"),
    ("spread legs", "pose.legs_raised"),
    ("arms behind", "pose.arms_behind"),
    ("arms up", "pose.arms_behind"),
    ("leaning", "pose.leaning_support"),
]
CAMERA_RULES: list[tuple[str, str]] = [
    ("pov", "camera.pov"),
    ("point of view", "camera.pov"),
    ("looking at viewer", "camera.looking_at_viewer"),
    ("looking back", "camera.side_view"),
    ("from above", "camera.high_angle"),
    ("top view", "camera.high_angle"),
    ("from below", "camera.low_angle"),
    ("from behind", "camera.side_view"),
    ("from side", "camera.side_view"),
    ("side view", "camera.side_view"),
    ("closeup", "camera.face_closeup"),
    ("close-up", "camera.face_closeup"),
    ("extra closeup", "camera.face_closeup"),
    ("full body", "camera.full_body"),
    ("upper body", "camera.medium"),
    ("cowboy shot", "camera.medium"),
    ("dutch angle", "camera.oblique"),
]
APPEARANCE_RULES: list[tuple[str, str]] = [
    ("nude", "appearance.nudity_state"),
    ("bottomless", "appearance.nudity_state"),
    ("no panties", "appearance.nudity_state"),
    ("breasts", "appearance.body_detail"),
    ("breast", "appearance.body_detail"),
    ("cleavage", "appearance.body_detail"),
    ("nipples", "appearance.body_detail"),
    ("pussy", "appearance.body_detail"),
    ("vulva", "appearance.body_detail"),
    ("penis", "appearance.body_detail"),
    ("testicles", "appearance.body_detail"),
    ("anus", "appearance.body_detail"),
    ("ass", "appearance.body_detail"),
    ("underwear", "appearance.clothing"),
    ("panties", "appearance.clothing"),
    ("thighhigh", "appearance.clothing"),
    ("stocking", "appearance.clothing"),
    ("lingerie", "appearance.clothing"),
    ("skirt", "appearance.clothing"),
    ("dress", "appearance.clothing"),
    ("shirt", "appearance.clothing"),
    ("bra", "appearance.clothing"),
    ("hair", "appearance.hair_or_identity"),
    ("twintail", "appearance.hair_or_identity"),
    ("ponytail", "appearance.hair_or_identity"),
    ("skin", "appearance.body_detail"),
]
SETTING_RULES: list[tuple[str, str]] = [
    ("bedroom", "setting.bedroom"),
    ("on bed", "setting.bedroom"),
    ("bathroom", "setting.bathroom"),
    ("shower", "setting.bathroom"),
    ("desk", "setting.desk_or_table"),
    ("table", "setting.desk_or_table"),
    ("chair", "setting.desk_or_table"),
    ("laboratory", "setting.laboratory_fantasy"),
    ("science fiction", "setting.laboratory_fantasy"),
    ("indoors", "setting.indoors"),
    ("car", "setting.vehicle"),
    ("train", "setting.vehicle"),
    ("park", "setting.outdoor_scene"),
    ("outdoors", "setting.staged_public"),
    ("public", "setting.staged_public"),
]
MOTION_RULES: list[tuple[str, str]] = [
    ("after sex", "motion.aftercare_settle"),
    ("after anal sex", "motion.aftercare_settle"),
    ("tired after", "motion.aftercare_settle"),
    ("hypnosis", "motion.gradual_transition"),
    ("transition", "motion.gradual_transition"),
    ("breathing", "motion.breathing"),
    ("trembling", "motion.continuous_rhythm"),
    ("shaking", "motion.continuous_rhythm"),
    ("riding", "motion.continuous_rhythm"),
    ("motion lines", "motion.continuous_rhythm"),
]
EFFECT_RULES: list[tuple[str, str]] = [
    ("loss of catchlights", "effects.loss_of_catchlights"),
    ("catchlight", "effects.loss_of_catchlights"),
    ("pink iris", "effects.full_iris_glow"),
    ("purple iris", "effects.full_iris_glow"),
    ("glowing iris", "effects.full_iris_glow"),
    ("hypnosis", "effects.concentric_rings"),
    ("ring eyes", "effects.concentric_rings"),
    ("heart in eyes", "effects.heart_highlight"),
    ("heart eyes", "effects.heart_highlight"),
    ("steam", "effects.steam_or_haze"),
    ("haze", "effects.steam_or_haze"),
    ("motion lines", "effects.motion_lines"),
]
PHYSIOLOGY_RULES: list[tuple[str, str]] = [
    ("drooling", "physiology.saliva"),
    ("saliva", "physiology.saliva"),
    ("sweat", "physiology.perspiration"),
    ("perspiration", "physiology.perspiration"),
    ("trembling", "physiology.trembling"),
    ("shaking", "physiology.trembling"),
    ("breathing", "physiology.breathing"),
    ("erection", "physiology.arousal_response"),
    ("cum", "physiology.fluid_cue"),
    ("juice", "physiology.fluid_cue"),
    ("bukkake", "physiology.fluid_cue"),
]
PROP_RULES: list[tuple[str, str]] = [
    ("pillow", "prop.soft_support"),
    ("dildo", "prop.adult_toy"),
    ("vibrator", "prop.adult_toy"),
    ("toy", "prop.adult_toy"),
    ("sex machine", "prop.scifi_machine"),
    ("machine", "prop.scifi_machine"),
    ("tentacle", "prop.fantasy_appendage"),
    ("beads", "prop.adult_toy"),
    ("plug", "prop.adult_toy"),
    ("desk", "prop.surface"),
    ("table", "prop.surface"),
    ("chair", "prop.surface"),
]
PROP_FALLBACK_MARKERS = {
    "banana", "bottle", "zucchini", "carrot", "popsicle", "leek", "eggplant",
    "daikon", "corn", "candy cane", "lollipop", "pencil", "pen", "tube", "stick",
    "wand", "recorder", "flute", "microphone", "sword", "katana", "shovel",
    "broom", "staff", "traffic cone",
}


def clean_token(value: str) -> str:
    value = value.strip().lower().replace("_", " ")
    value = re.sub(r"<lora:[^>]+>", " ", value, flags=re.IGNORECASE)
    value = re.sub(r"^[\(\[\+]+|[\)\]]+$", "", value).strip()
    value = re.sub(r":\s*[0-9]+(?:\.[0-9]+)?$", "", value).strip()
    value = re.sub(r"\s+", " ", value)
    return value.strip(" ,")


def normalized_label(label: str) -> str:
    value = clean_token(label)
    return re.sub(r"\s+\d+\s*$", "", value).strip()


def unique(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value and value not in seen:
            result.append(value)
            seen.add(value)
    return result


def text_has(text: str, markers: set[str] | list[str]) -> bool:
    return any(marker in text for marker in markers)


def matching_rules(text: str, rules: list[tuple[str, str]]) -> list[str]:
    return unique([atom for marker, atom in rules if marker in text])


def residual_tags(tokens: list[str], label: str) -> tuple[list[str], list[str]]:
    markers = set(QUALITY_MARKERS) | set(NON_CONSENSUAL_MARKERS) | set(AGE_MARKERS)
    markers |= set(RESTRAINT_MARKERS) | set(PARTNER_MARKERS) | set(SELF_MARKERS)
    markers |= set(NONSEXUAL_MARKERS) | set(ADULT_ACTIVITY_MARKERS) | set(PROP_MARKERS) | set(PROP_FALLBACK_MARKERS)
    markers |= {marker for marker, _ in EXPRESSION_RULES + POSE_RULES + CAMERA_RULES + APPEARANCE_RULES + SETTING_RULES + MOTION_RULES + EFFECT_RULES + PHYSIOLOGY_RULES + PROP_RULES}
    unmapped: list[str] = []
    noise: list[str] = []
    for token in tokens:
        if token in SOURCE_NOISE_MARKERS or "lora:" in token or "<lora:" in token:
            noise.append(token)
        if re.fullmatch(r"(?:\d+|\d+girl|\d+girls|\d+boy|\d+boys|\d+man|\d+men|\d+woman|\d+women)", token):
            continue
        if token in {"solo", "solo focus", "hetero", "uncensored"}:
            continue
        if any(marker in token for marker in markers):
            continue
        if token and token != normalized_label(label):
            unmapped.append(token)
    return unique(unmapped), unique(noise)


def subject_info(tokens: list[str], text: str) -> dict[str, Any]:
    female = sum(int(m.group(1) or 1) for token in tokens for m in [
        re.fullmatch(r"(\d+)?\s*(?:girl|girls|woman|women|female)", token)
    ] if m)
    male = sum(int(m.group(1) or 1) for token in tokens for m in [
        re.fullmatch(r"(\d+)?\s*(?:boy|boys|man|men|male)", token)
    ] if m)
    other = sum(int(m.group(1) or 1) for token in tokens for m in [
        re.fullmatch(r"(\d+)?\s*(?:person|people|subject|character)", token)
    ] if m)
    count = female + male + other
    explicit_count = count > 0
    group = count > 2 or text_has(text, {"group sex", "threesome", "orgy", "multiple views"})
    partner = male > 0 or text_has(text, PARTNER_MARKERS - {"sex"})
    if not explicit_count:
        role = "unspecified_adult_subjects"
    elif group:
        role = "multiple_adult_subjects"
    elif partner:
        role = "adult_partner_pair"
    else:
        role = "one_adult_subject"
    return {
        "female_count": female,
        "male_count": male,
        "other_count": other,
        "explicit_subject_count": explicit_count,
        "group_variant": group,
        "partner_variant": partner,
        "role": role,
    }


def classify_action(label: str, text: str, subjects: dict[str, Any]) -> tuple[str, list[str]]:
    flags: list[str] = []
    if text_has(text, NON_CONSENSUAL_MARKERS) or text_has(clean_token(label), NON_CONSENSUAL_MARKERS):
        flags.append("non_consensual_source")
        return "action.review_required", flags
    if text_has(text, AGE_MARKERS) or text_has(clean_token(label), AGE_MARKERS):
        flags.append("age_ambiguity_source")
        return "action.review_required", flags
    if text_has(text, AFTERCARE_MARKERS) or "after" in normalized_label(label):
        return "action.aftercare", flags
    if text_has(text, SELF_MARKERS) or "masturb" in normalized_label(label):
        return "action.self_directed_intimacy", flags
    if text_has(text, PARTNER_MARKERS) or subjects["partner_variant"]:
        return "action.partner_intimacy", flags
    if text_has(text, NONSEXUAL_MARKERS):
        return "action.nonsexual_activity", flags
    if text_has(text, ADULT_ACTIVITY_MARKERS):
        flags.append("action_semantics_uncertain")
        return "action.review_required", flags
    flags.append("action_semantics_uncertain")
    return "action.review_required", flags


def classify_interaction(text: str, subjects: dict[str, Any], action: str) -> list[str]:
    result: list[str] = []
    if subjects["group_variant"]:
        result.append("interaction.group_contact")
    elif subjects["partner_variant"] or action == "action.partner_intimacy":
        result.append("interaction.partner_contact")
    else:
        result.append("interaction.solo_subject")
    if text_has(text, PROP_MARKERS) or any(marker in text for marker in PROP_FALLBACK_MARKERS):
        result.append("interaction.prop_contact")
    if text_has(text, RESTRAINT_MARKERS):
        result.append("interaction.restraint_roleplay")
    return result


def classify_dimensions(label: str, raw_value: str) -> dict[str, Any]:
    raw_tags = [item.strip() for item in raw_value.split(",") if item.strip()]
    normalized_tags = unique([clean_token(item) for item in raw_tags])
    label_norm = normalized_label(label)
    text = " ".join([label_norm, *normalized_tags])
    subjects = subject_info(normalized_tags, text)
    action, action_flags = classify_action(label, text, subjects)
    dimensions: dict[str, list[str]] = {
        "action": [action],
        "interaction": classify_interaction(text, subjects, action),
        "pose": matching_rules(text, POSE_RULES),
        "prop": matching_rules(text, PROP_RULES),
        "appearance": matching_rules(text, APPEARANCE_RULES),
        "expression": matching_rules(text, EXPRESSION_RULES),
        "physiology": matching_rules(text, PHYSIOLOGY_RULES),
        "camera": matching_rules(text, CAMERA_RULES),
        "setting": matching_rules(text, SETTING_RULES),
        "motion": matching_rules(text, MOTION_RULES),
        "effects": matching_rules(text, EFFECT_RULES),
        "audio": ["audio.silent"],
    }
    if not dimensions["pose"]:
        dimensions["pose"] = ["pose.unspecified"]
    if not dimensions["prop"] and any(marker in text for marker in PROP_FALLBACK_MARKERS):
        dimensions["prop"] = ["prop.household_object"]
    if not dimensions["motion"]:
        dimensions["motion"] = ["motion.static_hold"] if action == "action.aftercare" else ["motion.continuous_rhythm"]
    if "audio.dialogue" in dimensions["audio"]:
        dimensions["audio"] = ["audio.dialogue"]
    review_flags = list(action_flags)
    if text_has(text, RESTRAINT_MARKERS):
        review_flags.append("restraint_consent_review")
    if "lora:" in raw_value.casefold() or "<lora:" in raw_value.casefold():
        review_flags.append("third_party_lora_reference")
    if not subjects["explicit_subject_count"]:
        review_flags.append("subject_age_and_count_not_explicit")
    if not dimensions["expression"]:
        dimensions["expression"] = ["expression.neutral_composed"]
    if not dimensions["setting"]:
        dimensions["setting"] = ["setting.bedroom"] if "bed" in text else ["setting.desk_or_table"] if "desk" in text else []
    for key in dimensions:
        dimensions[key] = unique(dimensions[key])
    unmapped_tags, source_noise_tags = residual_tags(normalized_tags, label)
    if "action.review_required" in dimensions["action"]:
        review_status = "blocked" if "non_consensual_source" in review_flags else "manual_review"
    elif any(flag in review_flags for flag in {"restraint_consent_review", "third_party_lora_reference", "subject_age_and_count_not_explicit", "action_semantics_uncertain"}):
        review_status = "manual_review"
    else:
        review_status = "candidate"
    return {
        "subject": subjects,
        "dimensions": dimensions,
        "review": {"status": review_status, "flags": unique(review_flags)},
        "normalized_tags": normalized_tags,
        "unmapped_tags": unmapped_tags,
        "source_noise_tags": source_noise_tags,
        "label_family": label_norm,
    }


def semantic_fingerprint(atom: dict[str, Any]) -> str:
    dimensions = atom["dimensions"]
    keys = ["action", "interaction", "pose", "prop", "appearance", "expression", "physiology", "camera", "setting", "motion", "effects", "audio"]
    parts = []
    for key in keys:
        values = sorted(dimensions.get(key, []))
        if values:
            parts.append(f"{key}=" + "+".join(values))
    return "|".join(parts)


@lru_cache(maxsize=1)
def registry_phrases() -> dict[str, str]:
    registry = load_document(REGISTRY_PATH)
    return {str(item["id"]): str(item["h3_phrase"]) for item in registry["definitions"]}


def render_h3(atom: dict[str, Any]) -> str:
    dimensions = atom["dimensions"]
    phrases = registry_phrases()
    subject_roles = {
        "one_adult_subject": "one clearly adult fictional subject",
        "adult_partner_pair": "adult fictional subjects",
        "multiple_adult_subjects": "multiple clearly adult fictional subjects",
        "unspecified_adult_subjects": "clearly adult fictional subject(s)",
    }
    subjects = subject_roles.get(atom["subject"]["role"], "clearly adult fictional subject(s)")
    action = phrases.get(dimensions["action"][0], dimensions["action"][0].replace("_", " "))
    parts = [
        f"Generate one continuous 5-second H3 sequence for {subjects}.",
        f"Scene action: {action}.",
    ]
    for key in ("interaction", "pose", "prop", "appearance", "expression", "physiology", "camera", "setting", "motion", "effects", "audio"):
        values = dimensions.get(key) or []
        if values:
            rendered = "; ".join(phrases.get(value, value.replace("_", " ")) for value in values)
            parts.append(f"{key}: {rendered}.")
    parts.append(
        "Use natural language and preserve identity, anatomy, continuity, and reference semantics. "
        "This source is a compositional candidate, not a safety approval; enforce adult-only fictional "
        "subjects and explicit consent before generation."
    )
    if atom["review"]["status"] in {"blocked", "manual_review"}:
        parts.append("Manual review is required before generation; blocked sources must not be auto-run.")
    return " ".join(parts)


def compile_atom(label: str, raw_value: str) -> dict[str, Any]:
    classified = classify_dimensions(label, raw_value)
    atom = {
        "schema_version": 1,
        "id": "isekai.atom." + re.sub(r"[^a-z0-9]+", "_", label.casefold()).strip("_"),
        "label": label,
        "label_family": classified["label_family"],
        "source": {
            "file": "imports/action.json",
            "raw_value": raw_value,
            "raw_tags": [item.strip() for item in raw_value.split(",") if item.strip()],
        },
        "normalized_tags": classified["normalized_tags"],
        "unmapped_tags": classified["unmapped_tags"],
        "source_noise_tags": classified["source_noise_tags"],
        "subject": classified["subject"],
        "dimensions": classified["dimensions"],
        "review": classified["review"],
        "semantic_fingerprint": "",
        "h3": {"prompt_fragment": ""},
    }
    atom["semantic_fingerprint"] = semantic_fingerprint(atom)
    atom["h3"]["prompt_fragment"] = render_h3(atom)
    return atom


def build_audit(atoms: list[dict[str, Any]]) -> dict[str, Any]:
    raw_values = [atom["source"]["raw_value"] for atom in atoms]
    exact_counts = Counter(raw_values)
    normalized_counts = Counter(" ".join(atom["normalized_tags"]) for atom in atoms)
    fingerprints: dict[str, list[str]] = defaultdict(list)
    families: dict[str, list[str]] = defaultdict(list)
    for atom in atoms:
        fingerprints[atom["semantic_fingerprint"]].append(atom["label"])
        families[atom["label_family"]].append(atom["label"])
    duplicate_groups = [
        {"fingerprint": key, "count": len(labels), "labels": sorted(labels, key=str.casefold)}
        for key, labels in fingerprints.items() if len(labels) > 1
    ]
    duplicate_groups.sort(key=lambda item: (-item["count"], item["fingerprint"]))
    family_groups = [
        {"label_family": key, "count": len(labels), "labels": sorted(labels, key=str.casefold)}
        for key, labels in families.items() if len(labels) > 1
    ]
    family_groups.sort(key=lambda item: (-item["count"], item["label_family"]))
    dimension_counts = {
        dimension: dict(sorted(Counter(
            value
            for atom in atoms
            for value in (atom["dimensions"].get(dimension) or ["<none>"])
        ).items()))
        for dimension in ("action", "interaction", "pose", "prop", "appearance", "expression", "physiology", "camera", "setting", "motion", "effects", "audio")
    }
    review_counts = dict(sorted(Counter(atom["review"]["status"] for atom in atoms).items()))
    return {
        "schema_version": 1,
        "source": {
            "file": "imports/action.json",
            "entry_count": len(atoms),
            "unique_exact_values": len(exact_counts),
            "exact_duplicate_extra": sum(count - 1 for count in exact_counts.values() if count > 1),
            "unique_normalized_values": len(normalized_counts),
            "normalized_duplicate_extra": sum(count - 1 for count in normalized_counts.values() if count > 1),
        },
        "semantic": {
            "unique_fingerprints": len(fingerprints),
            "semantic_duplicate_extra": sum(len(labels) - 1 for labels in fingerprints.values() if len(labels) > 1),
            "duplicate_groups": duplicate_groups[:100],
            "label_family_groups": family_groups[:100],
        },
        "dimension_counts": dimension_counts,
        "review_counts": review_counts,
        "residual_tags": {
            "unique_unmapped_tag_count": len({tag for atom in atoms for tag in atom["unmapped_tags"]}),
            "top_unmapped_tags": [
                {"tag": tag, "count": count}
                for tag, count in Counter(tag for atom in atoms for tag in atom["unmapped_tags"]).most_common(100)
            ],
            "source_noise_occurrences": sum(len(atom["source_noise_tags"]) for atom in atoms),
        },
        "method": {
            "preserve_source": True,
            "split_into_dimensions": ["subject", "action", "interaction", "pose", "prop", "expression", "physiology", "camera", "setting", "motion", "effects", "audio"],
            "quality_and_lora_tokens_are_not_scene_atoms": True,
            "semantic_fingerprint_is_a_review_queue_not_a_claim_of_equivalence": True,
        },
    }


def load_source(path: Path) -> OrderedDict[str, str]:
    source_data = json.loads(path.read_text(encoding="utf-8-sig"), object_pairs_hook=OrderedDict)
    if not isinstance(source_data, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in source_data.items()):
        raise ValueError("source action library must be a JSON object with string keys and values")
    return source_data


def write_text_lf(path: Path, content: str) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(content)


def compile_library(source: Path = SOURCE_PATH, output: Path = OUTPUT_PATH, audit: Path = AUDIT_PATH) -> tuple[int, int]:
    source_data = load_source(source)
    atoms = [compile_atom(label, value) for label, value in source_data.items()]
    output.parent.mkdir(parents=True, exist_ok=True)
    write_text_lf(output, json.dumps(atoms, ensure_ascii=False, indent=2) + "\n")
    audit_data = build_audit(atoms)
    write_text_lf(audit, json.dumps(audit_data, ensure_ascii=False, indent=2) + "\n")
    return len(atoms), len(audit_data["semantic"]["duplicate_groups"])


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit and compile legacy tags into H3 compositional atoms")
    parser.add_argument("--source", type=Path, default=SOURCE_PATH)
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    parser.add_argument("--audit", type=Path, default=AUDIT_PATH)
    args = parser.parse_args()
    count, groups = compile_library(args.source, args.output, args.audit)
    print(f"compiled: {count} H3 compositional atom record(s)")
    print(f"semantic duplicate groups for review: {groups}")
    print(f"audit: {args.audit}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
