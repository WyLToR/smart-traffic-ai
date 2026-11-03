from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from smarttraffic_ai.config import Model, load_yaml

KIND_LABELS = {"vehicle": "Járműjelző", "pedestrian": "Gyalogosjelző", "unknown": "Ismeretlen"}
STATE_LABELS = {
    "red": "Piros",
    "yellow": "Sárga",
    "green": "Zöld",
    "red-yellow": "Piros+sárga",
    "unknown": "Nem állapítható meg",
}


class LightRegion(Model):
    id: str = Field(min_length=1, pattern=r"^[a-zA-Z0-9_-]+$")
    kind: Literal["vehicle", "pedestrian", "unknown"] = "unknown"
    bounds: tuple[float, float, float, float]

    @model_validator(mode="after")
    def check_bounds(self):
        x1, y1, x2, y2 = self.bounds
        if not (0 <= x1 < x2 <= 1 and 0 <= y1 < y2 <= 1):
            raise ValueError("A lámpa téglalapja 0–1 közötti, pozitív területű legyen.")
        return self


class LightConfig(Model):
    profiles: dict[str, list[LightRegion]] = Field(default_factory=dict)


def regions_for_video(root: Path, source_sha256: str) -> list[LightRegion]:
    path = root / "config/traffic-lights.yaml"
    return load_yaml(path, LightConfig).profiles.get(source_sha256, []) if path.is_file() else []


def read_color(frame, bbox, kind="unknown") -> tuple[str, dict]:
    """HSV evidence inside an already located signal; no type inference from color."""
    import cv2
    import numpy as np

    height, width = frame.shape[:2]
    x1, y1, x2, y2 = bbox
    crop = frame[max(0, int(y1)) : min(height, int(y2)), max(0, int(x1)) : min(width, int(x2))]
    empty = {"red": 0, "yellow": 0, "green": 0}
    if crop.shape[0] < 12 or crop.shape[1] < 6:
        return "unknown", empty
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    hue, sat, value = cv2.split(hsv)
    bright = (sat >= 100) & (value >= 100)
    masks = {
        "red": ((hue <= 12) | (hue >= 170)) & bright,
        "yellow": (hue >= 15) & (hue <= 37) & bright,
        "green": (hue >= 38) & (hue <= 95) & bright,
    }
    sizes, centers = {}, {}
    for name, mask in masks.items():
        count, _, stats, centroids = cv2.connectedComponentsWithStats(mask.astype(np.uint8), 8)
        if count < 2:
            sizes[name], centers[name] = 0, (0, 0)
        else:
            largest = 1 + int(stats[1:, cv2.CC_STAT_AREA].argmax())
            sizes[name] = int(stats[largest, cv2.CC_STAT_AREA])
            centers[name] = centroids[largest]
    minimum = max(6, int(crop.shape[0] * crop.shape[1] * 0.001))
    scores = {
        name: size for name, size in sizes.items() if kind != "pedestrian" or name != "yellow"
    }
    strongest = max(scores, key=scores.get)
    if sizes[strongest] < minimum:
        return "unknown", sizes
    active = {
        name for name, size in scores.items() if size >= minimum and size >= sizes[strongest] * 0.35
    }
    if {"red", "green"} <= active:
        return "unknown", sizes
    if {"red", "yellow"} <= active:
        distance = float(np.linalg.norm(centers["red"] - centers["yellow"]))
        if distance >= max(crop.shape[:2]) * 0.15:
            return "red-yellow", sizes
    return strongest, sizes


class LightAnalyzer:
    def __init__(self, regions: list[LightRegion]):
        if len({r.id for r in regions}) != len(regions):
            raise ValueError("A lámpaazonosítók legyenek egyediek.")
        self.regions = regions
        self.records = {}
        self.rows = []

    def update(self, frame, objects, seconds: float, duration: float) -> list[dict]:
        height, width = frame.shape[:2]
        candidates = [
            {
                "light_id": r.id,
                "kind": r.kind,
                "kind_source": "camera-config",
                "bbox": (
                    r.bounds[0] * width,
                    r.bounds[1] * height,
                    r.bounds[2] * width,
                    r.bounds[3] * height,
                ),
            }
            for r in self.regions
        ]
        for obj in objects:
            if obj.category != "traffic light":
                continue
            x = (obj.bbox[0] + obj.bbox[2]) / (2 * width)
            y = (obj.bbox[1] + obj.bbox[3]) / (2 * height)
            if any(
                r.bounds[0] <= x <= r.bounds[2] and r.bounds[1] <= y <= r.bounds[3]
                for r in self.regions
            ):
                continue
            candidates.append(
                {
                    "light_id": f"auto-{obj.track_id}",
                    "kind": "unknown",
                    "kind_source": "unknown",
                    "bbox": obj.bbox,
                }
            )
        current = []
        seen = set()
        for candidate in candidates:
            key = candidate["light_id"]
            seen.add(key)
            record = self.records.setdefault(
                key,
                {
                    "light_id": key,
                    "kind": candidate["kind"],
                    "kind_source": candidate["kind_source"],
                    "candidate": "unknown",
                    "streak": 0,
                    "durations": Counter(),
                    "first_seen_seconds": seconds,
                    "last_seen_seconds": seconds,
                },
            )
            raw_state, pixels = read_color(frame, candidate["bbox"], candidate["kind"])
            record["streak"] = record["streak"] + 1 if raw_state == record["candidate"] else 1
            record["candidate"] = raw_state
            record["last_seen_seconds"] = seconds
            state = raw_state if record["streak"] >= 3 else "unknown"
            record["durations"][state] += duration
            row = {
                "seconds": seconds,
                "light_id": key,
                "kind": record["kind"],
                "kind_source": record["kind_source"],
                "state": state,
                "raw_state": raw_state,
                "visible": True,
                "red_pixels": pixels["red"],
                "yellow_pixels": pixels["yellow"],
                "green_pixels": pixels["green"],
            }
            self.rows.append(row)
            current.append({**row, "bbox": list(candidate["bbox"])})
        for key, record in self.records.items():
            if key not in seen:
                record["candidate"], record["streak"] = "unknown", 0
                record["durations"]["unknown"] += duration
                self.rows.append(
                    {
                        "seconds": seconds,
                        "light_id": key,
                        "kind": record["kind"],
                        "kind_source": record["kind_source"],
                        "state": "unknown",
                        "raw_state": "unknown",
                        "visible": False,
                        "red_pixels": 0,
                        "yellow_pixels": 0,
                        "green_pixels": 0,
                    }
                )
        return current

    def summary(self):
        return [
            {
                "light_id": key,
                "kind": record["kind"],
                "kind_source": record["kind_source"],
                "first_seen_seconds": record["first_seen_seconds"],
                "last_seen_seconds": record["last_seen_seconds"],
                "state_seconds": {state: record["durations"][state] for state in STATE_LABELS},
            }
            for key, record in self.records.items()
        ]


def annotate_lights(image, lights):
    import cv2

    colors = {
        "red": (40, 40, 255),
        "green": (40, 230, 40),
        "yellow": (0, 220, 255),
        "red-yellow": (0, 150, 255),
        "unknown": (190, 190, 190),
    }
    types = {"vehicle": "JARMU", "pedestrian": "GYALOGOS", "unknown": "TIPUS ?"}
    states = {
        "red": "PIROS",
        "green": "ZOLD",
        "yellow": "SARGA",
        "red-yellow": "PIROS+SARGA",
        "unknown": "SZIN ?",
    }
    for light in lights:
        x1, y1, x2, y2 = map(int, light["bbox"])
        color = colors[light["state"]]
        label = f"{light['light_id']} {types[light['kind']]} {states[light['state']]}"
        cv2.rectangle(image, (x1, y1), (x2, y2), color, 2)
        left, top = max(0, x1), max(46, y1 - 7)
        cv2.putText(
            image, label, (left, top), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (0, 0, 0), 3, cv2.LINE_AA
        )
        cv2.putText(
            image, label, (left, top), cv2.FONT_HERSHEY_SIMPLEX, 0.42, color, 1, cv2.LINE_AA
        )
    return image
