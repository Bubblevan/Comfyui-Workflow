"""Compile a legacy action/tag dictionary into natural-language MiniMax H3 cards."""

from __future__ import annotations

import argparse
import json
import re
from collections import OrderedDict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SOURCE_PATH = ROOT / "library" / "nsfw" / "imports" / "action.json"
OUTPUT_PATH = ROOT / "library" / "nsfw" / "compiled" / "action_cards_h3.json"

QUALITY_PREFIXES = (
    "hda_",
    "masterpiece",
    "best quality",
    "good quality",
    "ultra",
    "raw photo",
    "8k",
    "highres",
    "absurdres",
    "uncensored",
)

ACTION_PHRASES = {
    "sex": "engaging in explicit sexual intercourse with the other adult character",
    "anal sex": "engaging in explicit anal intercourse with the other adult character",
    "doggy style": "holding a rear-entry sexual pose with the other adult character",
    "fellatio": "performing explicit oral sexual activity with the other adult character",
    "oral sex": "performing explicit oral sexual activity with the other adult character",
    "foot job": "using the feet in explicit sexual activity with the other adult character",
    "hand job": "using the hand in explicit sexual activity with the other adult character",
    "masturbation": "performing explicit self-stimulation",
    "girl on top": "taking the top position in explicit sexual activity",
    "paizuri": "using the chest in explicit sexual activity with the other adult character",
    "after sex": "resting in an aftercare state following explicit sexual activity",
    "after anal sex": "resting in an aftercare state following explicit anal activity",
    "wake up": "waking up and transitioning from rest to an alert expression",
    "sleep": "resting in a quiet sleeping pose",
    "showering": "washing in a shower while maintaining the described pose",
    "washing body": "washing the body with a sponge",
    "bath": "resting in a bath with wet skin and a calm expression",
    "massage": "receiving or giving a massage in the described position",
    "hug": "holding a close embrace with the other adult character",
    "kiss": "sharing a kiss with the other adult character",
    "bondage": "holding a restrained roleplay pose",
    "submissive pose": "holding a submissive roleplay pose",
    "pet play": "holding a consensual pet-play roleplay pose",
    "ponyplay": "holding a consensual pony-play roleplay pose",
    "stripper": "performing a striptease-style dance while maintaining the described framing",
    "exhibitionism": "holding a staged exhibitionist pose for the camera",
}

POSE_PHRASES = {
    "lying": "lying down",
    "on back": "on the back",
    "on stomach": "on the stomach",
    "on bed": "on a bed",
    "standing": "standing",
    "sitting": "sitting",
    "kneeling": "kneeling",
    "squatting": "squatting",
    "all fours": "on all fours",
    "legs up": "with the legs raised",
    "leg up": "with one leg raised",
    "spread legs": "with the legs spread in the described pose",
    "bent over": "bent forward",
    "straddling": "straddling the other adult character",
    "girl on top": "in a top-position pose",
    "upright straddle": "in an upright straddle pose",
    "reverse upright straddle": "in a reverse upright straddle pose",
}

CAMERA_PHRASES = {
    "pov": "a point-of-view camera",
    "looking at viewer": "direct eye contact with the camera",
    "looking at another": "eye contact with the other character",
    "looking back": "a glance back toward the camera",
    "from above": "a high-angle view",
    "from below": "a low-angle view",
    "from behind": "a rear three-quarter view",
    "from side": "a side view",
    "close-up": "a close-up framing",
    "full body": "a full-body framing",
    "upper body": "an upper-body framing",
    "cowboy shot": "a medium-full framing",
    "ass focus": "a framing that emphasizes the rear pose",
}

SETTING_PHRASES = {
    "indoors": "an indoor setting",
    "bedroom": "a bedroom",
    "bathroom": "a bathroom",
    "shower": "a shower room",
    "bed": "a bed",
    "car": "a car interior",
    "in the car": "a car interior",
    "outdoors": "an outdoor setting",
    "park": "a park",
    "window": "a room with a window",
    "table": "a table or desk",
    "chair": "a chair",
    "mirror": "a mirror in the scene",
}

APPEARANCE_PHRASES = {
    "breasts": "visible breasts",
    "large breasts": "large breasts",
    "huge breasts": "very large breasts",
    "cleavage": "visible cleavage",
    "nipples": "visible nipples",
    "pubic hair": "visible pubic hair",
    "pussy": "visible vulva",
    "anus": "visible anus",
    "penis": "a visible penis",
    "huge penis": "a very large penis",
    "testicles": "visible testicles",
    "nude": "nudity",
    "completely nude": "complete nudity",
    "bottomless": "an exposed lower body",
    "panties": "panties",
    "thighhighs": "thigh-high stockings",
    "pantyhose": "pantyhose",
    "collarbone": "a visible collarbone",
}

EXPRESSION_PHRASES = {
    "blush": "a flushed, embarrassed expression",
    "open mouth": "an open-mouth expression",
    "closed mouth": "a closed-mouth expression",
    "ahegao": "an exaggerated ecstatic facial expression",
    "smile": "a smile",
    "closed eyes": "closed eyes",
    "rolling eyes": "rolled-up eyes",
    "tongue out": "the tongue slightly extended",
    "drooling": "visible saliva",
    "sweat": "visible perspiration",
    "trembling": "subtle trembling",
    "orgasm": "an explicit orgasmic expression",
    "empty eyes": "a vacant gaze",
}

NON_CONSENSUAL_MARKERS = {
    "rape",
    "after rape",
    "chikan",
    "molestation",
    "forced",
    "unconscious",
    "sleeping sex",
    "asphyxia",
    "drowning",
}

AGE_REVIEW_MARKERS = {
    "school",
    "school uniform",
    "young",
    "teen",
    "teenage",
    "child",
    "diaper",
    "nursing",
    "oyakodon",
}

RESTRAINT_REVIEW_MARKERS = {
    "bondage",
    "restrained",
    "hogtied",
    "gag",
    "choke",
    "choking",
    "leash",
    "shackles",
}


def normalize_token(token: str) -> str:
    token = token.strip()
    token = re.sub(r"<lora:[^>]+>", "", token, flags=re.IGNORECASE)
    token = re.sub(r"\(([^()]+):[0-9.]+\)", r"\1", token)
    token = token.strip("()[]+").replace("_", " ")
    token = re.sub(r"\s+", " ", token).strip(" ,")
    return token.lower()


def humanize(value: str) -> str:
    value = re.sub(r"\s+\d+$", "", value.strip())
    value = value.replace("_", " ")
    value = re.sub(r"\s+", " ", value).strip()
    return value[:1].lower() + value[1:] if value else "the described action"


def unique(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value and value not in seen:
            result.append(value)
            seen.add(value)
    return result


def contains_marker(tokens: set[str], markers: set[str]) -> bool:
    return any(marker in tokens or any(marker in token for token in tokens) for marker in markers)


def subject_description(tokens: set[str]) -> tuple[str, list[str]]:
    female_count = 0
    male_count = 0
    for token in tokens:
        match = re.fullmatch(r"(\d+)\s*(girl|girls|woman|women|female)", token)
        if match:
            female_count += int(match.group(1))
        match = re.fullmatch(r"(\d+)\s*(boy|boys|man|men|male)", token)
        if match:
            male_count += int(match.group(1))
        if token in {"girl", "woman", "female"}:
            female_count += 1
        if token in {"boy", "man", "male"}:
            male_count += 1
    if female_count and male_count:
        description = "adult fictional female and male characters"
    elif female_count > 1:
        description = f"{female_count} adult fictional female characters"
    elif female_count == 1:
        description = "one adult fictional female character"
    elif male_count > 1:
        description = f"{male_count} adult fictional male characters"
    elif male_count == 1:
        description = "one adult fictional male character"
    else:
        description = "the adult fictional subject or subjects"
    flags = []
    if contains_marker(tokens, AGE_REVIEW_MARKERS):
        flags.append("age_review_required")
    return description, flags


def phrases(tokens: set[str], mapping: dict[str, str]) -> list[str]:
    return unique([phrase for token, phrase in mapping.items() if token in tokens])


def action_phrase(label: str, tokens: set[str]) -> str:
    base = humanize(label)
    if base in ACTION_PHRASES:
        return ACTION_PHRASES[base]
    for key, phrase in ACTION_PHRASES.items():
        if key in base:
            return phrase
    if "penetration" in base or "insertion" in base:
        return f"performs the explicit insertion action described as {base}"
    if "sex" in base or "sexual" in base:
        return f"performs the explicit adult sexual action described as {base}"
    if "pose" in base or any(token in tokens for token in POSE_PHRASES):
        return f"holds the {base} pose"
    return f"performs the described action, {base}"


def category_for(label: str, tokens: set[str], flags: list[str]) -> str:
    base = humanize(label)
    if "non_consensual_review_required" in flags:
        return "review_required"
    if "after" in base or "after sex" in tokens:
        return "aftercare"
    if "sex" in base or any(token in tokens for token in {"sex", "anal", "vaginal", "fellatio", "oral", "oral sex", "foot job", "hand job", "masturbation", "paizuri", "dildo", "blowjob", "cum"}):
        return "sexual_activity"
    if any(token in tokens for token in APPEARANCE_PHRASES):
        return "body_detail"
    if any(token in tokens for token in POSE_PHRASES):
        return "pose"
    return "action"


def compile_card(label: str, raw_value: str) -> dict[str, Any]:
    raw_tags = [item.strip() for item in raw_value.split(",") if item.strip()]
    normalized = unique([normalize_token(item) for item in raw_tags])
    tokens = set(normalized)
    subject, flags = subject_description(tokens)

    if contains_marker(tokens, NON_CONSENSUAL_MARKERS) or any(marker in label.lower() for marker in NON_CONSENSUAL_MARKERS):
        flags.append("non_consensual_review_required")
    if contains_marker(tokens, RESTRAINT_REVIEW_MARKERS):
        flags.append("restraint_consent_review")
    if any("lora:" in item.lower() for item in raw_tags):
        flags.append("third_party_lora_reference")
    if any(
        "multiple" in token
        or token in {"2girls", "2boys", "3girls", "3boys", "group sex", "gangbang", "threesome", "orgy", "mmf threesome"}
        for token in tokens
    ):
        flags.append("multi_subject_or_variant")
    flags = unique(flags)

    action = action_phrase(label, tokens)
    pose = phrases(tokens, POSE_PHRASES)
    camera = phrases(tokens, CAMERA_PHRASES)
    setting = phrases(tokens, SETTING_PHRASES)
    appearance = phrases(tokens, APPEARANCE_PHRASES)
    expression = phrases(tokens, EXPRESSION_PHRASES)
    ignored = set(QUALITY_PREFIXES) | set(ACTION_PHRASES) | set(POSE_PHRASES) | set(CAMERA_PHRASES) | set(SETTING_PHRASES) | set(APPEARANCE_PHRASES) | set(EXPRESSION_PHRASES)
    ignored |= {"1girl", "1boy", "2girls", "2boys", "3girls", "3boys", "1man", "1woman", "solo", "solo focus", "hetero", "uncensored"}
    unmapped = [token for token in normalized if token not in ignored and not re.fullmatch(r"\d+", token)]
    extras = [humanize(token) for token in unmapped if not any(token.startswith(prefix) for prefix in QUALITY_PREFIXES)]

    setting_text = ", ".join(setting) if setting else "a simple neutral environment"
    camera_text = ", ".join(camera) if camera else "a stable medium framing"
    pose_text = ", ".join(pose) if pose else "a stable, readable pose"
    appearance_text = ", ".join(appearance) if appearance else "the character's preserved appearance"
    expression_text = ", ".join(expression) if expression else "a clearly readable expression"
    extra_text = ", ".join(unique(extras)[:12])

    opening = f"Open on {subject} in {setting_text}, using {camera_text}. Establish {pose_text}, {appearance_text}, and {expression_text}."
    transition = f"The shot then shows the subjects {action}. Keep the movement continuous and readable, with the described pose and camera relationship preserved."
    if extra_text:
        transition += f" Additional visual details from the source reference are {extra_text}."
    ending = f"Hold the final state of {subject} in {setting_text}; preserve the established pose, framing, appearance, and expression until the end."
    if "non_consensual_review_required" in flags:
        transition = "The source label describes a coercive or non-consensual scenario. Keep this card review-only and do not auto-run it; rewrite the action as explicit consensual adult roleplay before generation."

    constraints = [
        "use adult fictional characters only",
        "preserve character identity, face, body proportions, clothing, and reference semantics",
        "make the requested action observable through continuous motion rather than keyword flashes",
        "no scene cuts, random extra characters, text, subtitles, or watermark",
    ]
    if "non_consensual_review_required" in flags:
        constraints.append("review and rewrite the source scenario as consensual adult roleplay before generation")
    if "age_review_required" in flags:
        constraints.append("confirm every subject is unambiguously adult before generation")

    subject_definition = f"<Subject 1> refers to {subject}. Preserve identity, stable facial proportions, clothing, colors, and body proportions."
    prompt = "\n\n".join(
        [
            f"subject_definitions:\n{subject_definition}",
            f"summary:\n[reference generation] Generate one continuous 5-second single-shot sequence for {subject}. Use references for identity and appearance, not as forced keyframes.",
            "retention_analysis:\nPreserve the selected subject references and keep their semantic roles consistent throughout the shot.",
            f"detailed_description:\n0.0-1.2s: {opening}\n1.2-3.8s: {transition}\n3.8-5.0s: {ending}\nConstraints: {'; '.join(constraints)}.",
            "overall_soundscape:\nN/A. Do not generate dialogue, singing, or extra ambience unless a shot explicitly supplies audio.",
            "non_diegetic_music:\nN/A. Do not generate non-diegetic music.",
        ]
    )

    return {
        "id": f"isekai.action.{re.sub(r'[^a-z0-9]+', '_', label.lower()).strip('_')}",
        "label": label,
        "category": category_for(label, tokens, flags),
        "source": {"file": "imports/action.json", "raw_value": raw_value, "raw_tags": raw_tags},
        "normalized_tags": normalized,
        "unmapped_tags": unique(unmapped),
        "review_flags": flags,
        "h3": {
            "subject_definitions": subject_definition,
            "summary": f"[reference generation] Generate one continuous 5-second single-shot sequence for {subject}. Use references for identity and appearance, not as forced keyframes.",
            "retention_analysis": "Preserve the selected subject references and keep their semantic roles consistent throughout the shot.",
            "detailed_description": f"0.0-1.2s: {opening}\n1.2-3.8s: {transition}\n3.8-5.0s: {ending}\nConstraints: {'; '.join(constraints)}.",
            "overall_soundscape": "N/A. Do not generate dialogue, singing, or extra ambience unless a shot explicitly supplies audio.",
            "non_diegetic_music": "N/A. Do not generate non-diegetic music.",
            "prompt": prompt,
        },
        "shot_fragment": {
            "reference_mode": "reference_generation",
            "duration": 5,
            "opening": {"framing": "medium_close_up", "view": "three_quarter_front", "description": opening},
            "beats": [
                {"start": 0.0, "end": 1.2, "description": opening},
                {"start": 1.2, "end": 3.8, "description": transition},
                {"start": 3.8, "end": 5.0, "description": ending},
            ],
            "ending": {"description": ending},
            "camera": {"framing": "medium_close_up", "type": "slow_push_in", "amplitude": "small", "speed": "slow"},
            "audio": {"policy": "silent"},
            "constraints": constraints,
        },
    }


def compile_library(source: Path = SOURCE_PATH, output: Path = OUTPUT_PATH) -> int:
    source_data = json.loads(source.read_text(encoding="utf-8-sig"), object_pairs_hook=OrderedDict)
    if not isinstance(source_data, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in source_data.items()):
        raise ValueError("source action library must be a JSON object with string keys and values")
    cards = [compile_card(label, value) for label, value in source_data.items()]
    id_counts: dict[str, int] = {}
    for card in cards:
        base_id = card["id"]
        id_counts[base_id] = id_counts.get(base_id, 0) + 1
        if id_counts[base_id] > 1:
            card["id"] = f"{base_id}_{id_counts[base_id]}"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(cards, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return len(cards)


def main() -> int:
    parser = argparse.ArgumentParser(description="Compile action tags into MiniMax H3 natural-language cards")
    parser.add_argument("--source", type=Path, default=SOURCE_PATH)
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    args = parser.parse_args()
    count = compile_library(args.source, args.output)
    print(f"compiled: {count} H3 action card(s) -> {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
