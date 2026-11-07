from __future__ import annotations

import hashlib
import time
from contextlib import nullcontext
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, Protocol

from PIL import Image, ImageDraw, ImageOps
from pydantic import Field, model_validator

from smarttraffic_ai.config import Direction, Model, load_yaml
from smarttraffic_ai.simulation import output_directory, save_json

Category = Literal["car", "bus", "truck", "motorcycle", "bicycle", "person"]
MOTOR_VEHICLES = ("car", "bus", "truck", "motorcycle")
TRAFFIC_CATEGORIES = (*MOTOR_VEHICLES, "bicycle", "person")
CATEGORY_LABELS = {
    "car": "Személyautó",
    "bus": "Busz",
    "truck": "Teherautó",
    "motorcycle": "Motorkerékpár",
    "bicycle": "Kerékpár",
    "person": "Gyalogos",
}


class Region(Model):
    id: str
    direction: Direction
    bounds: tuple[float, float, float, float]

    @model_validator(mode="after")
    def check_bounds(self):
        x1, y1, x2, y2 = self.bounds
        if not (0 <= x1 < x2 <= 1 and 0 <= y1 < y2 <= 1):
            raise ValueError("A régió normalizált, pozitív területű téglalap legyen.")
        return self


class DetectionConfig(Model):
    profile_id: Literal["fast", "balanced", "detailed"] | None = None
    processing_mode: Literal["full-frame"] = "full-frame"
    model_path: str = "models/yolo26n.pt"
    confidence: float = Field(default=0.25, ge=0, le=1)
    image_size: int = Field(default=960, ge=32, le=4096)
    device: str = "cpu"
    iou: float = Field(default=0.7, gt=0, le=1)
    max_detections: int = Field(default=300, ge=1, le=3000)
    half: bool = False
    diagnostics: bool = False
    classes: list[Category] = Field(default_factory=lambda: list(TRAFFIC_CATEGORIES), min_length=1)
    regions: list[Region] = Field(default_factory=list)

    @model_validator(mode="after")
    def check_regions(self):
        model_names = {"fast": "yolo11n.pt", "balanced": "yolo26n.pt", "detailed": "yolo26l.pt"}
        if self.profile_id and Path(self.model_path).name.lower() != model_names[self.profile_id]:
            raise ValueError("A profilhoz rendelt modell nem egyezik a modellfájl nevével.")
        if self.half and self.device == "cpu":
            raise ValueError("A félpontosságú inferencia CPU-n nem támogatott.")
        if len({r.id for r in self.regions}) != len(self.regions):
            raise ValueError("A régióazonosítók legyenek egyediek.")
        for i, first in enumerate(self.regions):
            for second in self.regions[i + 1 :]:
                a, b = first.bounds, second.bounds
                if max(a[0], b[0]) < min(a[2], b[2]) and max(a[1], b[1]) < min(a[3], b[3]):
                    raise ValueError("A megfigyelési régiók nem fedhetik egymást.")
        return self


class Detection(Model):
    category: Category
    bbox: tuple[float, float, float, float]
    confidence: float = Field(ge=0, le=1)
    region: str | None = None
    direction: Direction | None = None

    @model_validator(mode="after")
    def check_bbox(self):
        x1, y1, x2, y2 = self.bbox
        if not (0 <= x1 < x2 and 0 <= y1 < y2):
            raise ValueError("Érvénytelen befoglaló téglalap.")
        if (self.region is None) != (self.direction is None):
            raise ValueError("A régiót és az irányt együtt kell megadni.")
        return self


class DetectionResult(Model):
    source_id: str
    timestamp: datetime
    timestamp_source: Literal["user", "file-mtime"]
    source: Literal["yolo", "mock"]
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    processing_seconds: float = Field(ge=0)
    model_path: str | None
    objects: list[Detection]
    config: DetectionConfig | None = None
    runtime: dict = Field(default_factory=dict)

    @model_validator(mode="after")
    def check_result(self):
        if self.timestamp.tzinfo is None:
            raise ValueError("Az időbélyeghez időzóna szükséges.")
        for obj in self.objects:
            if obj.bbox[2] > self.width or obj.bbox[3] > self.height:
                raise ValueError("A befoglaló téglalap túlnyúlik a képen.")
        return self

    def summary(self) -> dict:
        return {
            "total": len(self.objects),
            "by_category": {
                name: sum(o.category == name for o in self.objects) for name in TRAFFIC_CATEGORIES
            },
            "by_direction": {
                name: sum(
                    o.direction == name and o.category in MOTOR_VEHICLES for o in self.objects
                )
                for name in ("N", "S", "E", "W")
            },
            "unassigned": sum(o.direction is None for o in self.objects),
            "source": self.source,
        }


class Detector(Protocol):
    def detect(self, image: Image.Image) -> list[Detection]: ...


@dataclass(frozen=True)
class TrackedObject:
    # A detection is still visible before ByteTrack assigns a stable ID.
    track_id: int | None
    category: str
    confidence: float
    bbox: tuple[float, float, float, float]
    above_threshold: bool = True


def predict_frame(detector, frame, include_lights=False, low_threshold=None):
    """One BGR inference, shared by images, video tracking and live snapshots."""
    config = detector.config
    allowed = [*detector.class_ids, *(detector.light_class_ids if include_lights else [])]
    threshold = config.confidence if low_threshold is None else low_threshold
    diagnostic = getattr(config, "diagnostics", False)
    started = time.perf_counter()
    arguments = dict(
        conf=min(threshold, 0.1) if diagnostic else threshold,
        imgsz=config.image_size,
        device=config.device,
        classes=None if diagnostic else allowed,
        iou=getattr(config, "iou", 0.7),
        max_det=getattr(config, "max_detections", 300),
        **(
            {"quantize": "fp16" if config.half else "fp32"}
            if getattr(detector, "precision_key", "half") == "quantize"
            else {"half": getattr(config, "half", False)}
        ),
        agnostic_nms=False,
        verbose=False,
    )
    while True:
        try:
            with getattr(detector, "model_lock", nullcontext()):
                result = detector.model.predict(frame, **arguments)[0]
            break
        except (MemoryError, RuntimeError) as exc:
            memory_messages = (
                "out of memory",
                "not enough memory",
                "can't allocate memory",
                "cannot allocate memory",
            )
            if not isinstance(exc, MemoryError) and not any(
                message in str(exc).lower() for message in memory_messages
            ):
                raise
            sizes = [size for size in (960, 640) if size < detector.config.image_size]
            if getattr(config, "profile_id", None) != "detailed" or not sizes:
                raise RuntimeError(
                    "Nincs elég memória az inferenciához. Válassz kisebb modellt vagy képméretet."
                ) from exc
            previous = detector.config.image_size
            config = detector.config = detector.config.model_copy(update={"image_size": sizes[0]})
            arguments["imgsz"] = sizes[0]
            detector.fallbacks = [
                *getattr(detector, "fallbacks", []),
                f"Memóriahiány miatt a képméret {previous}-ról {sizes[0]}-ra csökkent.",
            ]
            import gc

            gc.collect()
            try:
                import torch

                if torch.cuda.is_initialized():
                    torch.cuda.empty_cache()
            except ImportError:
                pass
    inference_seconds = time.perf_counter() - started
    calls = getattr(detector, "inference_calls", 0)
    detector.inference_calls = calls + 1
    if calls == 0:
        detector.first_inference_seconds = inference_seconds
    else:
        detector.warm_inference_seconds = (
            getattr(detector, "warm_inference_seconds", 0) + inference_seconds
        )
    raw = []
    if result.boxes is not None:
        for box in result.boxes:
            raw.append(
                {
                    "category": result.names[int(box.cls.item())],
                    "confidence": float(box.conf.item()),
                    "bbox": box.xyxy[0].tolist(),
                }
            )
    categories = (*config.classes, "traffic light") if include_lights else config.classes
    selected = [
        row for row in raw if row["category"] in categories and row["confidence"] >= threshold
    ]
    high = [row for row in raw if row["confidence"] >= config.confidence]
    relevant = [row for row in high if row["category"] in categories]
    detector.last_diagnostics = {
        "model_output_count": len(raw),
        "confidence_count": len(high),
        "category_count": len(relevant),
        "traffic_threshold_count": sum(row["category"] in TRAFFIC_CATEGORIES for row in relevant),
        "light_threshold_count": sum(row["category"] == "traffic light" for row in relevant),
        "tracking_candidates_count": len(selected) if low_threshold is not None else 0,
        "hit_max_detections": len(raw) >= getattr(config, "max_detections", 300),
        "zone_retained_count": len(relevant),
        "zone_filter_applied": False,
        "tracking_id_count": 0,
        "inference_seconds": inference_seconds,
        "input_size": [int(frame.shape[1]), int(frame.shape[0])],
        "model_output_scope": "post-Ultralytics confidence/class/NMS/max_det; not raw tensor",
        "all_classes_probed": diagnostic,
        "end_to_end": getattr(getattr(detector.model, "model", None), "end2end", None),
        "agnostic_nms": False,
        "probe_confidence": min(threshold, 0.1) if diagnostic else threshold,
        "speed_ms": getattr(result, "speed", {}),
    }
    detector.last_raw = raw if diagnostic else []
    return result, selected


class YoloDetector:
    def __init__(self, root: Path, config: DetectionConfig):
        from smarttraffic_ai.model_store import load_model

        started = time.perf_counter()
        self.handle, self.cache_hit = load_model(
            root / config.model_path, config.device, config.half
        )
        self.model = self.handle.model
        self.model_lock = self.handle.lock
        self.model_load_seconds = time.perf_counter() - started
        self.requested_image_size = config.image_size
        self.fallbacks = []
        from ultralytics.cfg import DEFAULT_CFG_DICT

        self.precision_key = "quantize" if "quantize" in DEFAULT_CFG_DICT else "half"
        self.config = config
        self.class_ids = [
            int(key) for key, name in self.model.names.items() if name in config.classes
        ]
        self.light_class_ids = [
            int(key) for key, name in self.model.names.items() if name == "traffic light"
        ]
        if not self.class_ids:
            raise ValueError("A modellben nincs a beállított közlekedési kategóriákból.")
        missing = set(config.classes) - set(self.model.names.values())
        if missing:
            raise ValueError(f"A modellből hiányzó kategóriák: {', '.join(sorted(missing))}")

    def runtime_info(self):
        calls = getattr(self, "inference_calls", 0)
        return {
            "profile_id": self.config.profile_id,
            "cache_hit": self.cache_hit,
            "model_load_seconds": self.model_load_seconds,
            "first_inference_seconds": getattr(self, "first_inference_seconds", None),
            "warm_inference_mean_seconds": (
                getattr(self, "warm_inference_seconds", 0) / (calls - 1) if calls > 1 else None
            ),
            "inference_calls": calls,
            "requested_image_size": self.requested_image_size,
            "effective_image_size": self.config.image_size,
            "warnings": self.fallbacks,
        }

    def detect(self, image: Image.Image) -> list[Detection]:
        import cv2
        import numpy as np

        # PIL handles Unicode file paths; OpenCV prepares the BGR frame.
        frame = cv2.cvtColor(np.asarray(image.convert("RGB")), cv2.COLOR_RGB2BGR)
        _, selected = predict_frame(self, frame)
        objects = [Detection(**row) for row in selected]
        self.last_diagnostics.update(displayed_count=len(objects), exported_count=len(objects))
        return objects


class MockDetector:
    def detect(self, image: Image.Image) -> list[Detection]:
        width, height = image.size
        return [
            Detection(
                category="car",
                bbox=(width * 0.4, height * 0.1, width * 0.5, height * 0.25),
                confidence=1,
            ),
            Detection(
                category="bus",
                bbox=(width * 0.1, height * 0.4, width * 0.2, height * 0.6),
                confidence=1,
            ),
        ]


def assign_regions(objects: list[Detection], config: DetectionConfig, width: int, height: int):
    assigned = []
    for obj in objects:
        x = (obj.bbox[0] + obj.bbox[2]) / (2 * width)
        y = obj.bbox[3] / height  # bottom-center: approximate road contact point
        region = next(
            (
                r
                for r in config.regions
                if r.bounds[0] <= x <= r.bounds[2] and r.bounds[1] <= y <= r.bounds[3]
            ),
            None,
        )
        assigned.append(
            obj.model_copy(
                update={
                    "region": region.id if region else None,
                    "direction": region.direction if region else None,
                }
            )
        )
    return assigned


def annotate(image: Image.Image, result: DetectionResult, config: DetectionConfig) -> Image.Image:
    image = image.convert("RGB").copy()
    draw = ImageDraw.Draw(image)
    for region in config.regions:
        x1, y1, x2, y2 = region.bounds
        draw.rectangle(
            (x1 * image.width, y1 * image.height, x2 * image.width, y2 * image.height),
            outline="cyan",
            width=2,
        )
        draw.text((x1 * image.width, y1 * image.height), region.id, fill="cyan")
    for obj in result.objects:
        draw.rectangle(obj.bbox, outline="lime", width=2)
        draw.text(obj.bbox[:2], f"{obj.category} {obj.confidence:.2f}", fill="lime")
    if result.source == "mock":
        draw.text((5, 5), "MOCK / SZINTETIKUS TESZTADAT", fill="red")
    return image


def detect_file(
    root: Path,
    path: Path,
    mock: bool = False,
    timestamp: str | None = None,
    config: DetectionConfig | None = None,
) -> Path:
    started = time.perf_counter()
    if path.suffix.lower() not in {".jpg", ".jpeg", ".png"}:
        raise ValueError("Csak JPG- és PNG-képek támogatottak.")
    config = config or load_yaml(root / "config/detection.yaml", DetectionConfig)
    capture_time = (
        datetime.fromisoformat(timestamp)
        if timestamp
        else datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
    )
    with Image.open(path) as source:
        image = ImageOps.exif_transpose(source).convert("RGB")
    decode_seconds = time.perf_counter() - started
    # Decode first: corrupt input must not trigger an expensive model load.
    loaded = time.perf_counter()
    detector: Detector = MockDetector() if mock else YoloDetector(root, config)
    model_load_seconds = time.perf_counter() - loaded
    objects = assign_regions(detector.detect(image), config, image.width, image.height)
    if not mock:
        config = detector.config
    result = DetectionResult(
        source_id=hashlib.sha256(path.read_bytes()).hexdigest(),
        timestamp=capture_time,
        timestamp_source="user" if timestamp else "file-mtime",
        source="mock" if mock else "yolo",
        width=image.width,
        height=image.height,
        processing_seconds=time.perf_counter() - started,
        model_path=None if mock else config.model_path,
        objects=objects,
        config=config,
        runtime={} if mock else detector.runtime_info(),
    )
    directory = output_directory(root, "detection")
    save_json(directory / "config.json", config.model_dump())
    drawing_started = time.perf_counter()
    annotate(image, result, config).save(directory / "annotated.png")
    annotation_and_save_seconds = time.perf_counter() - drawing_started
    if config.diagnostics and not mock:
        raw_preview = image.copy()
        draw = ImageDraw.Draw(raw_preview)
        for row in detector.last_raw:
            draw.rectangle(row["bbox"], outline="orange", width=1)
            draw.text(row["bbox"][:2], f"{row['category']} {row['confidence']:.2f}", fill="orange")
        raw_preview.save(directory / "raw.png")
        diagnostics = {
            **detector.last_diagnostics,
            "model_load_seconds": model_load_seconds,
            "decode_seconds": decode_seconds,
            "annotation_and_save_seconds": annotation_and_save_seconds,
            "total_seconds": time.perf_counter() - started,
            "model_classes": detector.model.names,
            "raw_detections": detector.last_raw,
            "final_detections": [obj.model_dump() for obj in objects],
            "config": config.model_dump(),
        }
        save_json(directory / "diagnostics.json", diagnostics)
    result.processing_seconds = time.perf_counter() - started
    save_json(directory / "detection.json", result.model_dump(mode="json"))
    save_json(directory / "summary.json", result.summary())
    return directory / "detection.json"
