"""Three-stage keyframe screening for H3 synthetic videos.

Stage A checks corruption, blur, and brightness. Stage B uses dHash and SSIM
to avoid near-duplicate candidates. Stage C is an advisory reference-similarity
score only; it never promotes a frame into a dataset automatically.
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

try:
    import cv2
    import numpy as np
except ImportError:  # pragma: no cover - video extraction needs the runtime bundle
    cv2 = None
    np = None

VIDEO_SUFFIXES = {".mp4", ".mov", ".mkv", ".webm", ".avi"}


def _require_cv2() -> None:
    if cv2 is None or np is None:
        raise RuntimeError("extract requires OpenCV and NumPy; use runtime/python/python.exe")


def sharpness_score(image: Any) -> float:
    _require_cv2()
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    value = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    brightness = float(np.mean(gray))
    if brightness < 35 or brightness > 225:
        value *= 0.65
    return value


def _gray_small(image: Any, size: int = 32) -> Any:
    _require_cv2()
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    return cv2.resize(gray, (size, size), interpolation=cv2.INTER_AREA)


def dhash(image: Any, size: int = 16) -> Any:
    small = _gray_small(image, size + 1)
    return small[:, 1:] > small[:, :-1]


def dhash_similarity(left: Any, right: Any) -> float:
    return 1.0 - float(np.mean(dhash(left) != dhash(right)))


def ssim_similarity(left: Any, right: Any) -> float:
    """Small dependency-free SSIM approximation over normalized grayscale frames."""
    a = _gray_small(left, 64).astype(np.float32) / 255.0
    b = _gray_small(right, 64).astype(np.float32) / 255.0
    mean_a, mean_b = float(a.mean()), float(b.mean())
    var_a, var_b = float(a.var()), float(b.var())
    covariance = float(((a - mean_a) * (b - mean_b)).mean())
    c1, c2 = 0.0001, 0.0009
    return ((2 * mean_a * mean_b + c1) * (2 * covariance + c2)) / ((mean_a**2 + mean_b**2 + c1) * (var_a + var_b + c2))


def duplicate_score(left: Any, right: Any) -> float:
    return max(dhash_similarity(left, right), ssim_similarity(left, right))


def filter_duplicate_candidates(candidates: list[dict[str, Any]], threshold: float = 0.92) -> list[dict[str, Any]]:
    """Keep the sharpest temporally diverse candidates and annotate duplicate score."""
    selected: list[dict[str, Any]] = []
    for candidate in sorted(candidates, key=lambda item: item["sharpness"], reverse=True):
        score = max((duplicate_score(candidate["image"], chosen["image"]) for chosen in selected), default=0.0)
        candidate["duplicate_score"] = round(score, 5)
        if score < threshold:
            selected.append(candidate)
    return sorted(selected, key=lambda item: item["frame"])


def reference_similarity(image: Any, references: list[Any]) -> float | None:
    """Advisory visual consistency score; semantic identity models remain optional."""
    if not references:
        return None
    return round(max(dhash_similarity(image, ref) for ref in references), 5)


def read_image(path: Path) -> Any:
    _require_cv2()
    buffer = np.fromfile(str(path), dtype=np.uint8)
    return cv2.imdecode(buffer, cv2.IMREAD_COLOR)


def write_png(image: Any, path: Path) -> None:
    _require_cv2()
    ok, buffer = cv2.imencode(".png", image)
    if not ok:
        raise OSError(f"could not encode frame: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    buffer.tofile(str(path))


def read_video_candidates(video_path: Path, sample_rate: float = 3.0) -> tuple[list[dict[str, Any]], float, int, int]:
    _require_cv2()
    capture = cv2.VideoCapture(str(video_path))
    if not capture.isOpened():
        raise OSError(f"could not open video: {video_path}")
    fps = float(capture.get(cv2.CAP_PROP_FPS) or 24.0)
    width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
    height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
    interval = max(1, int(round(fps / max(0.1, sample_rate))))
    candidates = []
    frame_number = 0
    while True:
        ok, image = capture.read()
        if not ok:
            break
        if frame_number % interval == 0 and image is not None and image.size and image.shape[0] > 8 and image.shape[1] > 8:
            candidates.append({"frame": frame_number, "time": frame_number / fps, "sharpness": sharpness_score(image), "image": image.copy()})
        frame_number += 1
    capture.release()
    return candidates, fps, width, height


def _select_quality(candidates: list[dict[str, Any]], keep: int, minimum_sharpness: float) -> list[dict[str, Any]]:
    quality = [item for item in candidates if item["sharpness"] >= minimum_sharpness]
    if not quality:
        return []
    return filter_duplicate_candidates(quality)[: max(1, keep)]


def _resolve_video(root: Path, relative: str) -> Path:
    path = (root / relative).resolve()
    try:
        path.relative_to((root / "output").resolve())
    except ValueError as exc:
        raise OSError(f"output video is outside output/: {relative}") from exc
    if not path.is_file():
        raise FileNotFoundError(path)
    return path


def create_contact_sheet(root: Path, run_id: str, references: list[Path], candidates: list[dict[str, Any]]) -> Path:
    _require_cv2()
    qc_dir = root / "output" / "qc" / run_id
    qc_dir.mkdir(parents=True, exist_ok=True)
    columns, cell_w, cell_h = 3, 360, 245
    rows = max(1, (len(references) + len(candidates) + columns - 1) // columns)
    sheet = np.full((rows * cell_h, columns * cell_w, 3), 245, dtype=np.uint8)
    items: list[tuple[str, Any, str]] = []
    for index, path in enumerate(references, 1):
        image = read_image(path) if path.is_file() else None
        items.append((f"Reference {index}", image, path.name))
    for candidate in candidates:
        items.append((candidate["path"].stem, candidate["image"], f"t={candidate['time']:.3f}s sharp={candidate['sharpness']:.1f} dup={candidate.get('duplicate_score', 0):.3f}"))
    for index, (_, image, caption) in enumerate(items):
        if image is None:
            continue
        row, col = divmod(index, columns)
        thumb = image.copy()
        scale = min((cell_w - 20) / thumb.shape[1], (cell_h - 65) / thumb.shape[0])
        thumb = cv2.resize(thumb, (max(1, int(thumb.shape[1] * scale)), max(1, int(thumb.shape[0] * scale))))
        y, x = row * cell_h + 10, col * cell_w + 10
        sheet[y:y + thumb.shape[0], x:x + thumb.shape[1]] = thumb
        cv2.putText(sheet, caption[:52], (x, row * cell_h + cell_h - 30), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (20, 20, 20), 1, cv2.LINE_AA)
    output = qc_dir / "contact_sheet.jpg"
    cv2.imwrite(str(output), sheet, [int(cv2.IMWRITE_JPEG_QUALITY), 92])
    return output


def extract_run(root: Path, run: dict[str, Any], sample_rate: float = 3.0, keep_per_video: int = 5, minimum_sharpness: float = 35.0) -> list[Path]:
    run_id = run["run_id"]
    videos = [_resolve_video(root, item) for item in run.get("output_video", [])]
    if not videos:
        raise OSError("run has no completed output_video; extract only completed runs")
    pending_dir = root / "output" / "frames" / "pending" / run_id
    pending_dir.mkdir(parents=True, exist_ok=True)
    reference_paths = [root / item["file"] for item in run.get("references", [])]
    reference_images = [read_image(path) for path in reference_paths if path.is_file()]
    all_rows: list[dict[str, Any]] = []
    output_paths: list[Path] = []
    sequence = 0
    for video in videos:
        candidates, _, width, height = read_video_candidates(video, sample_rate)
        selected = _select_quality(candidates, keep_per_video, minimum_sharpness)
        for candidate in selected:
            sequence += 1
            frame_name = f"frame_{sequence:03d}.png"
            frame_path = pending_dir / frame_name
            write_png(candidate["image"], frame_path)
            candidate["path"] = frame_path
            candidate["identity_similarity"] = reference_similarity(candidate["image"], reference_images)
            output_paths.append(frame_path)
            all_rows.append({
                "frame": frame_name,
                "source_video": video.relative_to(root).as_posix(),
                "frame_number": candidate["frame"],
                "time": f"{candidate['time']:.3f}",
                "sharpness": f"{candidate['sharpness']:.3f}",
                "duplicate_score": f"{candidate.get('duplicate_score', 0):.5f}",
                "identity_similarity": "" if candidate["identity_similarity"] is None else f"{candidate['identity_similarity']:.5f}",
                "width": width,
                "height": height,
                "status": "pending_manual_review",
            })
    csv_path = pending_dir / "frames.csv"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(all_rows[0]) if all_rows else ["frame", "status"])
        writer.writeheader()
        writer.writerows(all_rows)
    contact_candidates = []
    for row, path in zip(all_rows, output_paths):
        contact_candidates.append({"path": path, "image": read_image(path), "time": float(row["time"]), "sharpness": float(row["sharpness"]), "duplicate_score": float(row["duplicate_score"])})
    create_contact_sheet(root, run_id, reference_paths, contact_candidates)
    return output_paths


if __name__ == "__main__":
    raise SystemExit("Use python scripts/h3.py extract RUN_ID")
