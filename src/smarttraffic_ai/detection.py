from __future__ import annotations

import hashlib
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, Protocol

from PIL import Image, ImageDraw
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
    model_path: str = "models/yolo11n.pt"
    confidence: float = Field(default=0.35, ge=0, le=1)
    image_size: int = Field(default=640, ge=32, le=4096)
    device: str = "cpu"
    classes: list[Category] = Field(default_factory=lambda: list(TRAFFIC_CATEGORIES), min_length=1)
    regions: list[Region] = Field(default_factory=list)

    @model_validator(mode="after")
    def check_regions(self):
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


class YoloDetector:
    def __init__(self, root: Path, config: DetectionConfig):
        model_path = root / config.model_path
        if not model_path.is_file():
            raise FileNotFoundError(
                f"Nincs YOLO-modell: {model_path}. Lásd docs/ai-model.md; "
                "tesztadatokhoz válaszd a kifejezett mock módot."
            )
        try:
            from ultralytics import YOLO
        except ImportError as exc:
            raise ImportError("A képfeldolgozáshoz telepítsd: pip install -e '.[vision]'.") from exc
        self.model = YOLO(str(model_path))
        self.config = config
        self.class_ids = [
            int(key) for key, name in self.model.names.items() if name in config.classes
        ]
        self.light_class_ids = [
            int(key) for key, name in self.model.names.items() if name == "traffic light"
        ]
        if not self.class_ids:
            raise ValueError("A modellben nincs a beállított közlekedési kategóriákból.")

    def detect(self, image: Image.Image) -> list[Detection]:
        import cv2
        import numpy as np

        # PIL handles Unicode file paths; OpenCV prepares the BGR frame.
        frame = cv2.cvtColor(np.asarray(image.convert("RGB")), cv2.COLOR_RGB2BGR)
        results = self.model.predict(
            frame,
            conf=self.config.confidence,
            imgsz=self.config.image_size,
            device=self.config.device,
            classes=self.class_ids,
            agnostic_nms=True,
            verbose=False,
        )
        objects = []
        for result in results:
            for box in result.boxes:
                name = result.names[int(box.cls.item())]
                if name in self.config.classes:
                    objects.append(
                        Detection(
                            category=name,
                            bbox=box.xyxy[0].tolist(),
                            confidence=float(box.conf.item()),
                        )
                    )
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


def detect_file(root: Path, path: Path, mock: bool = False, timestamp: str | None = None) -> Path:
    started = time.perf_counter()
    if path.suffix.lower() not in {".jpg", ".jpeg", ".png"}:
        raise ValueError("Csak JPG- és PNG-képek támogatottak.")
    config = load_yaml(root / "config/detection.yaml", DetectionConfig)
    detector: Detector = MockDetector() if mock else YoloDetector(root, config)
    capture_time = (
        datetime.fromisoformat(timestamp)
        if timestamp
        else datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
    )
    with Image.open(path) as source:
        image = source.convert("RGB")
    objects = assign_regions(detector.detect(image), config, image.width, image.height)
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
    )
    directory = output_directory(root, "detection")
    save_json(directory / "detection.json", result.model_dump(mode="json"))
    save_json(directory / "summary.json", result.summary())
    save_json(directory / "config.json", config.model_dump())
    annotate(image, result, config).save(directory / "annotated.png")
    return directory / "detection.json"
