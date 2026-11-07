from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import os
import shutil
import subprocess
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Callable

from smarttraffic_ai.config import load_yaml
from smarttraffic_ai.detection import (
    TRAFFIC_CATEGORIES,
    DetectionConfig,
    TrackedObject,
    YoloDetector,
    predict_frame,
)
from smarttraffic_ai.simulation import output_directory, save_csv, save_json
from smarttraffic_ai.traffic_lights import (
    LightAnalyzer,
    LightRegion,
    annotate_lights,
    regions_for_video,
)


@dataclass
class Track:
    track_id: int
    first_seen: float
    last_seen: float
    last_duration: float = 0
    visible_seconds: float = 0
    observations: int = 0
    votes: Counter = field(default_factory=Counter)

    @property
    def category(self):
        return self.votes.most_common(1)[0][0]

    def row(self):
        return {
            "track_id": self.track_id,
            "category": self.category,
            "first_seen_seconds": self.first_seen,
            "last_seen_seconds": self.last_seen,
            "visible_seconds": self.visible_seconds,
            "span_seconds": self.last_seen + self.last_duration - self.first_seen,
            "observations": self.observations,
        }


class TrackCounter:
    def __init__(self, min_observations: int = 3, min_visible_seconds: float = 0.5):
        if min_observations < 1 or min_visible_seconds < 0:
            raise ValueError("Legalább egy észlelés szükséges a megerősítéshez.")
        self.min_observations = min_observations
        self.min_visible_seconds = min_visible_seconds
        self.tracks: dict[int, Track] = {}
        self.current_ids: set[int] = set()
        self.last_time = -1.0

    def update(self, seconds: float, duration: float, objects: list[TrackedObject]):
        if (
            not math.isfinite(seconds)
            or seconds < 0
            or seconds <= self.last_time
            or not math.isfinite(duration)
            or duration <= 0
        ):
            raise ValueError("A videó időbélyegei növekedjenek, a képkockaidő legyen pozitív.")
        self.last_time = seconds
        # One ID contributes at most once per frame, even with duplicate boxes.
        unique = {}
        for obj in objects:
            if obj.category not in TRAFFIC_CATEGORIES or obj.track_id is None or obj.track_id < 1:
                continue
            if obj.track_id not in unique or unique[obj.track_id].confidence < obj.confidence:
                unique[obj.track_id] = obj
        self.current_ids = set(unique)
        for obj in unique.values():
            track = self.tracks.setdefault(obj.track_id, Track(obj.track_id, seconds, seconds))
            track.last_seen = seconds
            track.last_duration = duration
            track.visible_seconds += duration
            track.observations += 1
            track.votes[obj.category] += obj.confidence

    def is_confirmed(self, track):
        return (
            track.observations >= self.min_observations
            and track.visible_seconds + 1e-9 >= self.min_visible_seconds
        )

    def rows(self, current_only=False):
        return [
            track.row()
            for track in self.tracks.values()
            if self.is_confirmed(track) and (not current_only or track.track_id in self.current_ids)
        ]

    def summary(self):
        rows = self.rows()
        current = self.rows(current_only=True)
        return {
            "total_unique": len(rows),
            "current_total": len(current),
            "by_category": {
                name: sum(row["category"] == name for row in rows) for name in TRAFFIC_CATEGORIES
            },
            "current_by_category": {
                name: sum(row["category"] == name for row in current) for name in TRAFFIC_CATEGORIES
            },
        }


def _objects(detector, frame, tracker_path, low_threshold):
    import numpy as np
    import yaml
    from ultralytics.engine.results import Boxes
    from ultralytics.trackers.byte_tracker import BYTETracker

    result, selected = predict_frame(
        detector, frame, include_lights=True, low_threshold=low_threshold
    )
    if not hasattr(detector, "tracker"):
        settings = yaml.safe_load(Path(tracker_path).read_text(encoding="utf-8"))
        detector.tracker = BYTETracker(SimpleNamespace(**settings))
    ids = {name: key for key, name in result.names.items()}
    boxes = Boxes(
        np.asarray(
            [[*row["bbox"], row["confidence"], ids[row["category"]]] for row in selected],
            dtype=np.float32,
        ).reshape(-1, 6),
        frame.shape[:2],
    )
    started = time.perf_counter()
    tracks = detector.tracker.update(boxes, frame)
    tracking_seconds = time.perf_counter() - started
    height, width = frame.shape[:2]
    assigned = {}
    clipped_count = 0
    for row in tracks:
        index = int(row[-1])
        bbox = tuple(
            max(0.0, min(float(value), bound))
            for value, bound in zip(row[:4], (width, height, width, height), strict=True)
        )
        clipped_count += int(any(a != b for a, b in zip(bbox, row[:4], strict=True)))
        if not (bbox[0] < bbox[2] and bbox[1] < bbox[3]):
            bbox = tuple(selected[index]["bbox"])
        assigned[index] = (int(row[4]), bbox)
    objects = [
        TrackedObject(
            assigned[index][0] if index in assigned else None,
            row["category"],
            row["confidence"],
            assigned[index][1] if index in assigned else tuple(row["bbox"]),
            row["confidence"] >= detector.config.confidence,
        )
        for index, row in enumerate(selected)
        if row["confidence"] >= detector.config.confidence or index in assigned
    ]
    detector.last_diagnostics.update(
        tracking_id_count=sum(obj.track_id is not None for obj in objects),
        tracking_seconds=tracking_seconds,
        tracking_boxes_clipped=clipped_count,
        displayed_count=sum(obj.category in TRAFFIC_CATEGORIES for obj in objects),
        exported_count=sum(obj.category in TRAFFIC_CATEGORIES for obj in objects),
        threshold_detections_count=sum(
            obj.category in TRAFFIC_CATEGORIES and obj.above_threshold for obj in objects
        ),
    )
    return objects


def _annotate(frame, objects, counter):
    import cv2

    image = frame.copy()
    height, width = image.shape[:2]
    occupied = []
    for obj in objects:
        track = counter.tracks.get(obj.track_id)
        if track is None:
            if obj.category in TRAFFIC_CATEGORIES:
                x1, y1, x2, y2 = map(int, obj.bbox)
                cv2.rectangle(image, (x1, y1), (x2, y2), (255, 180, 0), 2)
                cv2.putText(
                    image,
                    f"{obj.category} {obj.confidence:.2f} (no ID)",
                    (x1, max(15, y1 - 4)),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.43,
                    (255, 180, 0),
                    1,
                )
            continue
        x1, y1, x2, y2 = (int(value) for value in obj.bbox)
        color = (0, 210, 100) if counter.is_confirmed(track) else (0, 180, 255)
        cv2.rectangle(image, (x1, y1), (x2, y2), color, 2)
        lines = [f"#{obj.track_id}", f"{track.visible_seconds:.1f}s"]
        label_width = (
            max(cv2.getTextSize(line, cv2.FONT_HERSHEY_SIMPLEX, 0.43, 1)[0][0] for line in lines)
            + 8
        )
        left = max(0, min(x1 + 2, width - label_width))
        top = max(33, y1 + 2)
        while top + 35 < height and any(
            left < right and left + label_width > x and top < bottom and top + 35 > y
            for x, y, right, bottom in occupied
        ):
            top += 36
        top = max(0, min(top, height - 35))
        occupied.append((left, top, left + label_width, top + 35))
        cv2.rectangle(image, (left, top), (left + label_width, top + 35), (20, 20, 20), -1)
        for line_number, line in enumerate(lines):
            cv2.putText(
                image,
                line,
                (left + 4, top + 14 + line_number * 16),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.43,
                color,
                1,
                cv2.LINE_AA,
            )
    summary = counter.summary()
    detected = sum(obj.category in TRAFFIC_CATEGORIES and obj.above_threshold for obj in objects)
    active = sum(obj.category in TRAFFIC_CATEGORIES and obj.track_id is not None for obj in objects)
    cv2.rectangle(image, (0, 0), (width, min(height, 32)), (25, 25, 25), -1)
    cv2.putText(
        image,
        f"Det: {detected} | ID: {active} | Megerositett: {summary['current_total']} "
        f"| Osszes ID: {summary['total_unique']}",
        (8, 23),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.6,
        (255, 255, 255),
        2,
        cv2.LINE_AA,
    )
    return image


def process_video(
    root: Path,
    path: Path,
    on_progress: Callable | None = None,
    light_regions: list[LightRegion] | None = None,
    config: DetectionConfig | None = None,
) -> dict:
    import cv2

    if path.suffix.lower() != ".mp4" or not path.is_file():
        raise ValueError("Adj meg egy létező MP4-videót.")
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise FileNotFoundError("A jelölt MP4 mentéséhez FFmpeg szükséges a PATH-ban.")
    if importlib.util.find_spec("lap") is None:
        raise ImportError("A követéshez telepítsd: uv pip install -e '.[vision]'.")
    config = config or load_yaml(root / "config/detection.yaml", DetectionConfig)
    with path.open("rb") as stream:
        input_sha = hashlib.file_digest(stream, "sha256").hexdigest()
    lights = LightAnalyzer(
        regions_for_video(root, input_sha) if light_regions is None else light_regions
    )
    capture = cv2.VideoCapture(str(path))
    encoder = None
    started = time.perf_counter()
    try:
        fps = capture.get(cv2.CAP_PROP_FPS)
        if not capture.isOpened() or not math.isfinite(fps) or fps <= 0:
            raise ValueError("A videó nem olvasható, vagy nem ismert az FPS értéke.")
        total_frames = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
        ok, frame = capture.read()
        if not ok:
            raise ValueError("A videóban nincs dekódolható képkocka.")
        width, height = frame.shape[1], frame.shape[0]
        loading_started = time.perf_counter()
        detector = YoloDetector(root, config)
        timings = {
            "model_load_seconds": time.perf_counter() - loading_started,
            "decode_seconds": 0.0,
            "inference_seconds": 0.0,
            "tracking_seconds": 0.0,
            "annotation_seconds": 0.0,
            "encoder_write_seconds": 0.0,
            "preview_seconds": 0.0,
        }
        directory = output_directory(root, "video")
        # Low-confidence matches preserve existing IDs, but cannot open new tracks.
        import yaml

        high_threshold = max(0.1, config.confidence)
        low_threshold = min(0.1, high_threshold / 2)
        tracker_config = {
            "tracker_type": "bytetrack",
            "track_high_thresh": high_threshold,
            "track_low_thresh": low_threshold,
            "new_track_thresh": high_threshold,
            "track_buffer": 30,
            "match_thresh": 0.8,
            "fuse_score": True,
        }
        tracker_path = directory / "tracker.yaml"
        tracker_path.write_text(yaml.safe_dump(tracker_config), encoding="utf-8")
        partial = directory / "annotated.partial.mp4"
        counter = TrackCounter()
        rows = []
        last_update = 0.0
        fallback_timestamps = 0
        seconds = max(0.0, capture.get(cv2.CAP_PROP_POS_MSEC) / 1000)
        index = 0
        with (
            (directory / "encoder.log").open("w", encoding="utf-8") as log,
            (directory / "observations.jsonl").open("w", encoding="utf-8") as observations,
            (directory / "detections.jsonl").open("w", encoding="utf-8") as detections,
        ):
            encoder = subprocess.Popen(
                [
                    ffmpeg,
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-y",
                    "-f",
                    "rawvideo",
                    "-pix_fmt",
                    "bgr24",
                    "-s",
                    f"{width}x{height}",
                    "-r",
                    str(fps),
                    "-i",
                    "pipe:0",
                    "-an",
                    "-c:v",
                    "libx264",
                    "-preset",
                    "veryfast",
                    "-crf",
                    "23",
                    "-pix_fmt",
                    "yuv420p",
                    "-vf",
                    "pad=ceil(iw/2)*2:ceil(ih/2)*2",
                    "-movflags",
                    "+faststart",
                    str(partial),
                ],
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=log,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            while ok:
                if frame.shape[:2] != (height, width):
                    raise ValueError("A videó képmérete feldolgozás közben megváltozott.")
                decoding_started = time.perf_counter()
                next_ok, next_frame = capture.read()
                timings["decode_seconds"] += time.perf_counter() - decoding_started
                next_seconds = capture.get(cv2.CAP_PROP_POS_MSEC) / 1000
                if not next_ok or not math.isfinite(next_seconds) or next_seconds <= seconds:
                    next_seconds = seconds + 1 / fps
                    fallback_timestamps += int(next_ok)
                duration = next_seconds - seconds
                objects = _objects(detector, frame, tracker_path, low_threshold)
                counter.update(seconds, duration, objects)
                current = [obj for obj in objects if obj.category in TRAFFIC_CATEGORIES]
                detector_diagnostics = getattr(detector, "last_diagnostics", {})
                timings["inference_seconds"] += detector_diagnostics.get("inference_seconds", 0)
                timings["tracking_seconds"] += detector_diagnostics.get("tracking_seconds", 0)
                detected_counts = {
                    name: sum(obj.category == name and obj.above_threshold for obj in current)
                    for name in TRAFFIC_CATEGORIES
                }
                detections.write(
                    json.dumps(
                        {
                            "seconds": seconds,
                            "frame_index": index,
                            "objects": [
                                {
                                    "track_id": obj.track_id,
                                    "category": obj.category,
                                    "confidence": obj.confidence,
                                    "above_threshold": obj.above_threshold,
                                    "bbox": list(obj.bbox),
                                }
                                for obj in current
                            ],
                            **(
                                {
                                    "diagnostics": detector_diagnostics,
                                    "raw_detections": getattr(detector, "last_raw", []),
                                }
                                if config.diagnostics
                                else {}
                            ),
                        },
                        allow_nan=False,
                    )
                    + "\n"
                )
                observations.write(
                    json.dumps(
                        {
                            "seconds": seconds,
                            "frame_index": index,
                            "duration": duration,
                            "objects": [
                                {
                                    "track_id": obj.track_id,
                                    "category": obj.category,
                                    "bbox": [
                                        obj.bbox[0] / width,
                                        obj.bbox[1] / height,
                                        obj.bbox[2] / width,
                                        obj.bbox[3] / height,
                                    ],
                                }
                                for obj in objects
                                if obj.category in TRAFFIC_CATEGORIES and obj.track_id is not None
                            ],
                        },
                        allow_nan=False,
                    )
                    + "\n"
                )
                drawing_started = time.perf_counter()
                image = _annotate(frame, objects, counter)
                light_readings = lights.update(frame, objects, seconds, duration)
                annotate_lights(image, light_readings)
                timings["annotation_seconds"] += time.perf_counter() - drawing_started
                try:
                    encoding_started = time.perf_counter()
                    encoder.stdin.write(image.tobytes())
                    timings["encoder_write_seconds"] += time.perf_counter() - encoding_started
                except BrokenPipeError as exc:
                    raise RuntimeError(
                        "Az FFmpeg nem tudta menteni a videót; lásd encoder.log."
                    ) from exc
                index += 1
                summary = counter.summary()
                rows.append(
                    {
                        "frame": index - 1,
                        "seconds": seconds,
                        "current_total": summary["current_total"],
                        "total_unique": summary["total_unique"],
                        "detections": sum(obj.above_threshold for obj in current),
                        "active_tracks": sum(obj.track_id is not None for obj in current),
                        **summary["current_by_category"],
                    }
                )
                now = time.perf_counter()
                if on_progress and (now - last_update >= 0.3 or not next_ok):
                    preview_started = time.perf_counter()
                    on_progress(
                        {
                            "frame": index,
                            "total_frames": total_frames,
                            "seconds": next_seconds,
                            "summary": summary,
                            "tracks": counter.rows(current_only=True),
                            "lights": light_readings,
                            "detections_by_category": detected_counts,
                            "diagnostics": detector_diagnostics,
                            "runtime": detector.runtime_info()
                            if hasattr(detector, "runtime_info")
                            else {},
                        },
                        image,
                    )
                    timings["preview_seconds"] += time.perf_counter() - preview_started
                    last_update = now
                frame, ok, seconds = next_frame, next_ok, next_seconds
            encoder.stdin.close()
            if encoder.wait(timeout=60) != 0:
                raise RuntimeError("Az FFmpeg hibával állt le; lásd encoder.log.")
        if total_frames > 0 and index != total_frames:
            raise ValueError(f"Hiányos dekódolás: {index}/{total_frames} képkocka olvasható.")
        final_path = partial.replace(directory / "annotated.mp4")
        result = {
            "input_name": path.name,
            "input_path": str(path.resolve()),
            "input_sha256": input_sha,
            "fps": fps,
            "width": width,
            "height": height,
            "frames": index,
            "duration_seconds": seconds,
            "processing_seconds": time.perf_counter() - started,
            "timings": timings,
            "timestamp_fallback_frames": fallback_timestamps,
            "config": getattr(detector, "config", config).model_dump(),
            "runtime": detector.runtime_info() if hasattr(detector, "runtime_info") else {},
            "processing_fps": index / max(time.perf_counter() - started, 1e-9),
            "tracker": tracker_config,
            "min_observations": counter.min_observations,
            "min_visible_seconds": counter.min_visible_seconds,
            "summary": counter.summary(),
            "tracks": counter.rows(),
            "traffic_lights": lights.summary(),
            "last_light_readings": light_readings,
            "last_detections_by_category": detected_counts,
            "diagnostics": detector_diagnostics if config.diagnostics else None,
            "light_regions": [r.model_dump() for r in lights.regions],
            "directory": str(directory),
            "video_path": str(final_path),
        }
        save_csv(directory / "tracks.csv", result["tracks"])
        if not result["tracks"]:
            (directory / "tracks.csv").write_text(
                "track_id,category,first_seen_seconds,last_seen_seconds,visible_seconds,"
                "span_seconds,observations\n",
                encoding="utf-8-sig",
            )
        save_csv(directory / "timeline.csv", rows)
        save_csv(directory / "traffic-lights.csv", lights.rows)
        if not lights.rows:
            (directory / "traffic-lights.csv").write_text(
                "seconds,light_id,kind,kind_source,state,raw_state,visible,"
                "red_pixels,yellow_pixels,green_pixels\n",
                encoding="utf-8-sig",
            )
        save_json(directory / "analysis.json", result)
        return result
    finally:
        capture.release()
        if encoder is not None and encoder.poll() is None:
            if encoder.stdin and not encoder.stdin.closed:
                encoder.stdin.close()
            encoder.terminate()
            encoder.wait(timeout=10)
