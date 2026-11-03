from __future__ import annotations

import hashlib
import importlib.util
import math
import os
import shutil
import subprocess
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from smarttraffic_ai.config import load_yaml
from smarttraffic_ai.detection import (
    TRAFFIC_CATEGORIES,
    DetectionConfig,
    YoloDetector,
)
from smarttraffic_ai.simulation import output_directory, save_csv, save_json
from smarttraffic_ai.traffic_lights import (
    LightAnalyzer,
    LightRegion,
    annotate_lights,
    regions_for_video,
)


@dataclass(frozen=True)
class TrackedObject:
    track_id: int
    category: str
    confidence: float
    bbox: tuple[float, float, float, float]


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
            if obj.category not in TRAFFIC_CATEGORIES or obj.track_id < 1:
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
    result = detector.model.track(
        frame,
        persist=True,
        tracker=str(tracker_path),
        classes=detector.class_ids + detector.light_class_ids,
        conf=low_threshold,
        imgsz=detector.config.image_size,
        device=detector.config.device,
        agnostic_nms=True,
        verbose=False,
    )[0]
    boxes = result.boxes
    if boxes is None or not boxes.is_track:
        return []
    return [
        TrackedObject(int(track_id), result.names[int(category)], float(confidence), tuple(bbox))
        for bbox, track_id, category, confidence in zip(
            boxes.xyxy.cpu().tolist(),
            boxes.id.cpu().tolist(),
            boxes.cls.cpu().tolist(),
            boxes.conf.cpu().tolist(),
            strict=True,
        )
        if result.names[int(category)] in (*detector.config.classes, "traffic light")
    ]


def _annotate(frame, objects, counter):
    import cv2

    image = frame.copy()
    height, width = image.shape[:2]
    occupied = []
    for obj in objects:
        track = counter.tracks.get(obj.track_id)
        if track is None:
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
    cv2.rectangle(image, (0, 0), (width, min(height, 32)), (25, 25, 25), -1)
    cv2.putText(
        image,
        f"Most: {summary['current_total']} | Osszes ID: {summary['total_unique']}",
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
) -> dict:
    import cv2

    if path.suffix.lower() != ".mp4" or not path.is_file():
        raise ValueError("Adj meg egy létező MP4-videót.")
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise FileNotFoundError("A jelölt MP4 mentéséhez FFmpeg szükséges a PATH-ban.")
    if importlib.util.find_spec("lap") is None:
        raise ImportError("A követéshez telepítsd: uv pip install -e '.[vision]'.")
    config = load_yaml(root / "config/detection.yaml", DetectionConfig)
    input_sha = hashlib.sha256(path.read_bytes()).hexdigest()
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
        detector = YoloDetector(root, config)
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
        with (directory / "encoder.log").open("w", encoding="utf-8") as log:
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
                next_ok, next_frame = capture.read()
                next_seconds = capture.get(cv2.CAP_PROP_POS_MSEC) / 1000
                if not next_ok or not math.isfinite(next_seconds) or next_seconds <= seconds:
                    next_seconds = seconds + 1 / fps
                    fallback_timestamps += int(next_ok)
                duration = next_seconds - seconds
                objects = _objects(detector, frame, tracker_path, low_threshold)
                counter.update(seconds, duration, objects)
                image = _annotate(frame, objects, counter)
                light_readings = lights.update(frame, objects, seconds, duration)
                annotate_lights(image, light_readings)
                try:
                    encoder.stdin.write(image.tobytes())
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
                        **summary["current_by_category"],
                    }
                )
                now = time.perf_counter()
                if on_progress and (now - last_update >= 0.3 or not next_ok):
                    on_progress(
                        {
                            "frame": index,
                            "total_frames": total_frames,
                            "seconds": next_seconds,
                            "summary": summary,
                            "tracks": counter.rows(current_only=True),
                            "lights": light_readings,
                        },
                        image,
                    )
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
            "input_sha256": input_sha,
            "fps": fps,
            "width": width,
            "height": height,
            "frames": index,
            "duration_seconds": seconds,
            "processing_seconds": time.perf_counter() - started,
            "timestamp_fallback_frames": fallback_timestamps,
            "config": config.model_dump(),
            "tracker": tracker_config,
            "min_observations": counter.min_observations,
            "min_visible_seconds": counter.min_visible_seconds,
            "summary": counter.summary(),
            "tracks": counter.rows(),
            "traffic_lights": lights.summary(),
            "last_light_readings": light_readings,
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
