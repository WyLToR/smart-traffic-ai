"""Local, opt-in measurements using the application's existing YOLO detector."""

import argparse
import hashlib
import json
import statistics
import time
from collections import Counter
from pathlib import Path

from PIL import Image, ImageDraw

from smarttraffic_ai.config import load_yaml, project_root
from smarttraffic_ai.detection import (
    MOTOR_VEHICLES,
    TRAFFIC_CATEGORIES,
    Detection,
    DetectionConfig,
    YoloDetector,
)
from smarttraffic_ai.profiles import DETECTION_PROFILES


def iou(first, second):
    area = max(0, min(first[2], second[2]) - max(first[0], second[0])) * max(
        0, min(first[3], second[3]) - max(first[1], second[1])
    )
    union = (
        (first[2] - first[0]) * (first[3] - first[1])
        + (second[2] - second[0]) * (second[3] - second[1])
        - area
    )
    return area / union if union > 0 else 0


def evaluate(objects, reference, threshold=0.5):
    """Match manual boxes one-to-one, only inside explicitly annotated areas."""

    def covered(obj):
        x = (obj["bbox"][0] + obj["bbox"][2]) / 2
        y = obj["bbox"][3]
        return any(
            obj["category"] in region["categories"]
            and region["bbox"][0] <= x <= region["bbox"][2]
            and region["bbox"][1] <= y <= region["bbox"][3]
            for region in reference["regions"]
        )

    predicted = [obj for obj in objects if covered(obj)]
    targets = reference["objects"]
    adjacency = [
        [
            j
            for j, target in enumerate(targets)
            if target["category"] == obj["category"]
            and iou(obj["bbox"], target["bbox"]) >= threshold
        ]
        for obj in predicted
    ]
    matched = {}

    def augment(index, seen):
        for target in adjacency[index]:
            if target in seen:
                continue
            seen.add(target)
            if target not in matched or augment(matched[target], seen):
                matched[target] = index
                return True
        return False

    for index in range(len(predicted)):
        augment(index, set())

    def scores(categories):
        tp = sum(targets[index]["category"] in categories for index in matched)
        actual = sum(obj["category"] in categories for obj in targets)
        detected = sum(obj["category"] in categories for obj in predicted)
        return {
            "tp": tp,
            "fp": detected - tp,
            "fn": actual - tp,
            "precision": tp / detected if detected else None,
            "recall": tp / actual if actual else None,
            "f1": 2 * tp / (actual + detected) if actual + detected else None,
            "count_error": detected - actual,
        }

    categories = sorted({obj["category"] for obj in [*targets, *predicted]})
    return {
        "iou_threshold": threshold,
        "human_reviewed": bool(reference.get("human_reviewed", False)),
        "categories": {category: scores({category}) for category in categories},
        "groups": {"vehicles": scores(set(MOTOR_VEHICLES)), "person": scores({"person"})},
    }


def draft(path, source_id, image, objects, config, output):
    """Model proposal for manual correction in the reference format; never a verified label."""
    preview = image.copy()
    draw = ImageDraw.Draw(preview)
    for number, obj in enumerate(objects):
        draw.rectangle(obj.bbox, outline="yellow", width=2)
        draw.text((obj.bbox[0] + 2, obj.bbox[1] + 2), f"{number} {obj.category}", fill="yellow")
    preview.save(output / f"draft-{path.parent.name}-{path.stem}.jpg")
    return {
        "input": str(path),
        "image_sha256": source_id,
        "annotator": f"VÁZLAT: {Path(config.model_path).name} találatai, emberi ellenőrzés nélkül",
        "human_reviewed": False,
        "notes": (
            "Javítandó: hiányzó objektumok felvétele, téves dobozok törlése, kategória és doboz "
            "igazítása. A régiót szűkítsd a megbízhatóan jelölhető területre. Csak teljes kézi "
            "ellenőrzés után állítható a human_reviewed igazra, az annotátor nevével."
        ),
        "regions": [
            {"categories": list(TRAFFIC_CATEGORIES), "bbox": [0, 0, image.width, image.height]}
        ],
        "objects": [
            {
                "number": number,
                "category": obj.category,
                "bbox": [round(value, 1) for value in obj.bbox],
                "confidence": round(obj.confidence, 3),
            }
            for number, obj in enumerate(objects)
        ],
    }


def sliced(detector, image):
    """Experiment only: original-resolution overlapping tiles plus a full-frame pass."""
    original = detector.config
    objects = detector.detect(image)
    tile, step = 640, 512
    detector.config = original.model_copy(update={"image_size": 640})
    try:

        def starts(length):
            return sorted({*range(0, max(1, length - tile), step), max(0, length - tile)})

        for y in starts(image.height):
            for x in starts(image.width):
                crop = image.crop((x, y, min(x + tile, image.width), min(y + tile, image.height)))
                for obj in detector.detect(crop):
                    a, b, c, d = obj.bbox
                    # Interior tile edges can truncate an object; a neighbouring tile covers it.
                    if (
                        (x > 0 and a < 2)
                        or (y > 0 and b < 2)
                        or (x + tile < image.width and c > crop.width - 2)
                        or (y + tile < image.height and d > crop.height - 2)
                    ):
                        continue
                    objects.append(
                        Detection(
                            category=obj.category,
                            confidence=obj.confidence,
                            bbox=(a + x, b + y, c + x, d + y),
                        )
                    )
    finally:
        detector.config = original
    merged = []
    for obj in sorted(objects, key=lambda row: row.confidence, reverse=True):
        if not any(
            other.category == obj.category and iou(other.bbox, obj.bbox) > 0.7 for other in merged
        ):
            merged.append(obj)
    return merged


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, nargs="+", required=True)
    parser.add_argument("--reference", type=Path)
    parser.add_argument("--models", nargs="+", default=["models/yolo11n.pt", "models/yolo26n.pt"])
    parser.add_argument("--profiles", nargs="+", choices=list(DETECTION_PROFILES))
    parser.add_argument("--sizes", type=int, nargs="+", default=[640, 960, 1280])
    parser.add_argument("--confidence", type=float, nargs="+", default=[0.1, 0.15, 0.25, 0.35])
    parser.add_argument("--repeats", type=int, default=2)
    parser.add_argument("--slicing", action="store_true")
    parser.add_argument("--output", type=Path, default=Path("outputs/detection-audit/comparison"))
    parser.add_argument("--draft-reference", type=Path, help="Write a reference draft to review")
    args = parser.parse_args()
    if args.repeats < 1:
        parser.error("repeats must be positive")
    if args.draft_reference and (not args.profiles or len(args.profiles) != 1):
        parser.error("--draft-reference needs exactly one --profiles value")
    drafts = {}
    root = project_root()
    config = load_yaml(root / "config/detection.yaml", DetectionConfig)
    references = json.loads(args.reference.read_text(encoding="utf-8")) if args.reference else {}
    output = args.output
    output.mkdir(parents=True, exist_ok=True)
    rows = []
    try:
        import psutil

        process = psutil.Process()
    except ImportError:
        process = None
    variants = (
        [
            (p.model_path, p.apply(config), [p.image_size], [p.confidence])
            for name in args.profiles
            for p in [DETECTION_PROFILES[name]]
        ]
        if args.profiles
        else [
            (
                model,
                config.model_copy(update={"profile_id": None, "model_path": model}),
                args.sizes,
                args.confidence,
            )
            for model in args.models
        ]
    )
    for model, base, sizes, confidences in variants:
        started = time.perf_counter()
        detector = YoloDetector(root, base)
        load_seconds = time.perf_counter() - started
        for path in args.input:
            with Image.open(path) as source:
                image = source.convert("RGB")
            source_id = hashlib.sha256(path.read_bytes()).hexdigest()
            reference = references.get(source_id)
            for size in sizes:
                for confidence in confidences:
                    modes = ["normal", "sliced"] if args.slicing else ["normal"]
                    for mode in modes:
                        detector.config = base.model_copy(
                            update={
                                "model_path": model,
                                "image_size": size,
                                "confidence": confidence,
                            }
                        )
                        infer = sliced if mode == "sliced" else lambda d, im: d.detect(im)
                        started = time.perf_counter()
                        infer(detector, image)
                        cold = time.perf_counter() - started
                        times = []
                        for _ in range(args.repeats):
                            started = time.perf_counter()
                            objects = infer(detector, image)
                            times.append(time.perf_counter() - started)
                        data = [obj.model_dump() for obj in objects]
                        name = (
                            f"{path.parent.name}-{path.stem}-{Path(model).stem}"
                            f"-{size}-{confidence}-{mode}"
                        )
                        preview = image.copy()
                        draw = ImageDraw.Draw(preview)
                        for obj in objects:
                            draw.rectangle(obj.bbox, outline="lime", width=2)
                            draw.text(
                                obj.bbox[:2], f"{obj.category} {obj.confidence:.2f}", fill="lime"
                            )
                        preview.save(output / f"{name}.jpg")
                        row = {
                            "input": str(path),
                            "input_sha256": source_id,
                            "model": model,
                            "profile_id": base.profile_id,
                            "cache_hit": detector.cache_hit,
                            "max_detections": base.max_detections,
                            "size": size,
                            "confidence": confidence,
                            "mode": mode,
                            "model_load_seconds": load_seconds,
                            "warmup_seconds": cold,
                            "mean_seconds": statistics.mean(times),
                            "times_seconds": times,
                            "rss_after_inference_bytes": process.memory_info().rss
                            if process
                            else None,
                            "counts": dict(Counter(obj.category for obj in objects)),
                            "objects": data,
                            "evaluation": evaluate(data, reference) if reference else None,
                        }
                        (output / f"{name}.json").write_text(
                            json.dumps(row, indent=2), encoding="utf-8"
                        )
                        rows.append(row)
                        (output / "comparison.json").write_text(
                            json.dumps(rows, indent=2), encoding="utf-8"
                        )
                        print(name, row["counts"], round(row["mean_seconds"], 3), flush=True)
                        if args.draft_reference:
                            drafts[source_id] = draft(path, source_id, image, objects, base, output)
    if args.draft_reference:
        args.draft_reference.write_text(
            json.dumps(drafts, indent=2, ensure_ascii=False), encoding="utf-8"
        )


if __name__ == "__main__":
    main()
