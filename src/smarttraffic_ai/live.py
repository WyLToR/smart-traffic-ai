from __future__ import annotations

import base64
import binascii
import hashlib
import json
import math
import threading
import time
from html.parser import HTMLParser
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit
from urllib.request import Request, urlopen

import yaml

from smarttraffic_ai.config import load_yaml
from smarttraffic_ai.detection import (
    TRAFFIC_CATEGORIES,
    DetectionConfig,
    YoloDetector,
    predict_frame,
)
from smarttraffic_ai.simulation import output_directory, save_json
from smarttraffic_ai.traffic_lights import LightAnalyzer, annotate_lights
from smarttraffic_ai.video import TrackCounter, TrackedObject, _annotate, _objects
from smarttraffic_ai.youtube_source import resolve_youtube, youtube_url


def validate_source(value: str) -> str:
    value = value.strip()
    youtube = youtube_url(value)
    if youtube is not None:
        return youtube
    if value.startswith("blob:"):
        raise ValueError(
            "A blob: cím csak a böngésződben létezik. Az Időkép kameraoldalának "
            "címét vagy a közvetlen HLS/RTSP videócímet illeszd be."
        )
    parts = urlsplit(value)
    if parts.scheme not in {"http", "https", "rtsp"} or not parts.hostname:
        raise ValueError("HTTP(S) vagy RTSP videócím szükséges.")
    return value


class _VideoSources(HTMLParser):
    def __init__(self):
        super().__init__()
        self.sources = []
        self.image = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "source" and ".m3u8" in attrs.get("src", ""):
            self.sources.append(attrs["src"])
        if tag == "img" and attrs.get("id") == "realcamimg":
            self.image = attrs.get("src")


def budapest_camera_id(value: str) -> str | None:
    parts = urlsplit(value)
    if parts.hostname != "kozutfigyelo.budapestkozut.hu":
        return None
    ids = [value for key, value in parse_qsl(parts.query) if key == "id"]
    if (
        parts.path.rstrip("/") != "/list/camerahistory"
        or len(ids) != 1
        or not ids[0].isascii()
        or not ids[0].isdigit()
        or len(ids[0]) > 10
    ):
        raise ValueError(
            "A Budapest Közút kameraoldalának címe szükséges, például camerahistory?id=10003."
        )
    return ids[0]


def fetch_budapest_image(camera_id: str) -> tuple[bytes, str | None]:
    request = Request(
        "https://kozutfigyelo-back.budapestkozut.hu/api/ikszr/cameraimage",
        data=json.dumps({"thumbnail": 0, "externalId": camera_id}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urlopen(request, timeout=10) as response:
        content = response.read(22_000_001)
    if len(content) > 22_000_000:
        raise ValueError("A Budapest Közút kameraválasza túl nagy.")
    try:
        result = json.loads(content)
        data = result.get("data") or {}
        image = data.get("image")
        if result.get("success") is not True or not isinstance(image, str) or not image:
            raise ValueError("A Budapest Közút kamerája jelenleg nem ad képet.")
        decoded = base64.b64decode(image, validate=True)
        created_at = data.get("createdAt")
        if not isinstance(created_at, str):
            created_at = None
        return decoded, created_at
    except (json.JSONDecodeError, binascii.Error, AttributeError, TypeError) as exc:
        raise ValueError("A Budapest Közút kameraválasza nem értelmezhető.") from exc


def resolve_source(value: str) -> str:
    value = validate_source(value)
    parts = urlsplit(value)
    if youtube_url(value) is not None:
        return resolve_youtube(value)
    if budapest_camera_id(value) is not None:
        # The reader requests the latest image through the site's public API.
        return value
    if parts.hostname in {"idokep.hu", "www.idokep.hu"} and parts.path.startswith("/webkamera/"):
        # Read the player's current URL on every start; stream paths can change.
        with urlopen(value, timeout=10) as response:
            parser = _VideoSources()
            parser.feed(response.read(2_000_000).decode("utf-8", errors="replace"))
            base = response.url
        if not parser.sources:
            if parser.image:
                return validate_source(urljoin(base, parser.image))
            raise ValueError("Ezen az Időkép-oldalon nem található HLS-videó vagy kamerakép.")
        return validate_source(urljoin(base, parser.sources[0]))
    return value


def observation_duration(seconds: float, previous: float | None, fps: float) -> float:
    # Sampling cannot establish visibility during a network or inference stall.
    interval = 1 / fps
    return interval if previous is None else min(interval, seconds - previous)


def analyze_snapshot(detector, frame, regions, seconds):
    """Independent image observations: no cross-image IDs or inferred durations."""
    import cv2

    _, selected = predict_frame(detector, frame, include_lights=True)
    objects = [
        TrackedObject(index, row["category"], row["confidence"], tuple(row["bbox"]))
        for index, row in enumerate(selected, start=1)
    ]
    counts = {name: sum(obj.category == name for obj in objects) for name in TRAFFIC_CATEGORIES}
    detector.last_diagnostics.update(
        displayed_count=sum(counts.values()), exported_count=sum(counts.values())
    )
    image = frame.copy()
    for obj in objects:
        if obj.category not in TRAFFIC_CATEGORIES:
            continue
        x1, y1, x2, y2 = map(int, obj.bbox)
        cv2.rectangle(image, (x1, y1), (x2, y2), (0, 210, 100), 2)
        cv2.putText(
            image,
            f"{obj.category} {obj.confidence:.2f}",
            (x1, max(15, y1 - 5)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            (0, 210, 100),
            1,
            cv2.LINE_AA,
        )
    readings = LightAnalyzer(regions).update(frame, objects, seconds, 1)
    # These are single-image color estimates, without temporal confirmation.
    readings = [{**row, "state": row["raw_state"]} for row in readings]
    return {
        "source_kind": "snapshot",
        "image": annotate_lights(image, readings),
        "counts": counts,
        "config": detector.config.model_dump() if hasattr(detector.config, "model_dump") else None,
        "runtime": detector.runtime_info() if hasattr(detector, "runtime_info") else {},
        "diagnostics": detector.last_diagnostics
        if getattr(detector.config, "diagnostics", False)
        else None,
        "lights": readings,
        "objects": [
            {"category": obj.category, "confidence": obj.confidence, "bbox": obj.bbox}
            for obj in objects
            if obj.category in TRAFFIC_CATEGORIES
        ],
    }


class _LatestFrame:
    """Decode continuously; inference consumes the newest frame, without a queue."""

    def __init__(self, source, stop):
        self.source = source
        self.stop = stop
        self.lock = threading.Lock()
        self.latest = None
        self.error = None
        parts = urlsplit(source)
        self.snapshot = (
            parts.path.lower().endswith((".jpg", ".jpeg", ".png"))
            or (parts.hostname == "cam.idokep.hu" and parts.path == "/kamera.php")
            or budapest_camera_id(source) is not None
        )
        self.thread = threading.Thread(target=self._read, daemon=True)

    def _read(self):
        try:
            if self.snapshot:
                self._read_images()
            elif urlsplit(self.source).path.lower().endswith(".m3u8"):
                self._read_hls()
            else:
                self._read_capture()
        except Exception as exc:
            self.error = str(exc)

    def _publish(self, frame, captured_at=None):
        with self.lock:
            self.latest = (time.monotonic(), frame, captured_at)

    def _read_images(self):
        import cv2
        import numpy as np

        previous = None
        camera_id = budapest_camera_id(self.source)
        while not self.stop.is_set():
            captured_at = None
            if camera_id is not None:
                content, captured_at = fetch_budapest_image(camera_id)
            else:
                parts = urlsplit(self.source)
                query = dict(parse_qsl(parts.query, keep_blank_values=True))
                query["t"] = str(int(time.time() * 1000))
                url = urlunsplit(parts._replace(query=urlencode(query)))
                with urlopen(url, timeout=10) as response:
                    content = response.read(16_000_001)
            if len(content) > 16_000_000:
                raise ValueError("A kamerakép túl nagy (legfeljebb 16 MB lehet).")
            digest = hashlib.sha256(content).digest()
            if digest != previous:
                frame = cv2.imdecode(np.frombuffer(content, dtype=np.uint8), cv2.IMREAD_COLOR)
                if frame is None:
                    raise ValueError("A kamerakép nem dekódolható.")
                if captured_at is None:
                    self._publish(frame)
                else:
                    self._publish(frame, captured_at)
                previous = digest
            self.stop.wait(30)

    def _read_hls(self):
        # Fetch HLS with Python's HTTPS stack, then decode local segments. This also
        # avoids platform-dependent FFmpeg TLS hangs and unpaced segment bursts.
        import cv2

        playlist_url = self.source
        sequence = None
        variants = 0
        due = None
        last_frame_at = time.monotonic()
        with TemporaryDirectory(prefix="smarttraffic-hls-") as temporary:
            segment_path = Path(temporary) / "segment.ts"
            while not self.stop.is_set():
                with urlopen(playlist_url, timeout=10) as response:
                    lines = response.read(2_000_000).decode("utf-8-sig").splitlines()
                    playlist_url = response.url
                if not lines or lines[0].strip() != "#EXTM3U":
                    raise ValueError("A forrás nem HLS lejátszási lista.")
                urls = [line.strip() for line in lines if line.strip() and not line.startswith("#")]
                if any(line.startswith("#EXT-X-STREAM-INF:") for line in lines):
                    variants += 1
                    if variants > 5:
                        raise ValueError("A HLS-listák túl sokszor hivatkoznak egymásra.")
                    if not urls:
                        raise ValueError("A HLS-lista üres.")
                    candidate = urljoin(playlist_url, urls[0])
                    if candidate == playlist_url:
                        raise ValueError("A HLS-lista önmagára hivatkozik.")
                    playlist_url = validate_source(candidate)
                    continue
                unsupported = ("#EXT-X-KEY:", "#EXT-X-MAP:", "#EXT-X-BYTERANGE:")
                if any(line.startswith(unsupported) for line in lines):
                    raise ValueError(
                        "Ez a HLS-forrás titkosított vagy nem támogatott szegmensformátumú."
                    )
                first = next(
                    (
                        int(line.split(":", 1)[1])
                        for line in lines
                        if line.startswith("#EXT-X-MEDIA-SEQUENCE:")
                    ),
                    0,
                )
                if sequence is None:
                    sequence = first + max(0, len(urls) - 1)
                if sequence < first:
                    raise ValueError(
                        "A HLS-forrásból képszakaszok maradtak ki. Indíts új elemzést."
                    )
                index = sequence - first
                if index >= len(urls):
                    if "#EXT-X-ENDLIST" in lines:
                        raise ValueError("A videó véget ért; ez nem folyamatos élő forrás.")
                    if time.monotonic() - last_frame_at > 20:
                        raise ValueError("A HLS-forrás több mint 20 másodperce nem frissül.")
                    self.stop.wait(0.5)
                    continue
                segment_url = validate_source(urljoin(playlist_url, urls[index]))
                with urlopen(segment_url, timeout=10) as response:
                    content = response.read(32_000_001)
                if len(content) > 32_000_000:
                    raise ValueError("A HLS-szegmens túl nagy (legfeljebb 32 MB lehet).")
                segment_path.write_bytes(content)
                capture = cv2.VideoCapture(str(segment_path))
                count = 0
                try:
                    fps = capture.get(cv2.CAP_PROP_FPS)
                    if not capture.isOpened() or not math.isfinite(fps) or fps <= 0:
                        raise ValueError("A HLS-szegmens nem dekódolható.")
                    if due is None:
                        due = time.monotonic()
                    while not self.stop.is_set():
                        ok, frame = capture.read()
                        if not ok:
                            break
                        if self.stop.wait(max(0, due - time.monotonic())):
                            break
                        self._publish(frame)
                        last_frame_at = time.monotonic()
                        count += 1
                        due += 1 / fps
                    if not count and not self.stop.is_set():
                        raise ValueError("A HLS-szegmens nem tartalmaz olvasható képet.")
                finally:
                    capture.release()
                sequence += 1

    def _read_capture(self):
        import cv2

        capture = None
        try:
            capture = cv2.VideoCapture(
                self.source,
                cv2.CAP_FFMPEG,
                [cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 8000, cv2.CAP_PROP_READ_TIMEOUT_MSEC, 8000],
            )
            if not capture.isOpened():
                raise ValueError("A videóforrás nem nyitható meg, vagy nem elérhető.")
            fps = capture.get(cv2.CAP_PROP_FPS)
            fps = fps if math.isfinite(fps) and fps > 0 else 25
            due = time.monotonic()
            while not self.stop.is_set():
                ok, frame = capture.read()
                if not ok:
                    raise ValueError("A videókapcsolat megszakadt vagy a videó véget ért.")
                if self.stop.wait(max(0, due - time.monotonic())):
                    break
                self._publish(frame)
                due += 1 / fps
        except Exception as exc:
            self.error = str(exc)
        finally:
            if capture is not None:
                capture.release()

    def get(self):
        with self.lock:
            return self.latest


class LiveSession:
    def __init__(self, root: Path, source: str, regions=(), max_seconds=120, fps=5, config=None):
        self.root = root
        self.source = validate_source(source)
        if not 1 <= max_seconds <= 600 or not 1 <= fps <= 10:
            raise ValueError("Az időtartam 1–600 s, a mintavétel 1–10 FPS lehet.")
        self.regions = list(regions)
        self.max_seconds = max_seconds
        self.fps = fps
        self.config = config
        self.stop_event = threading.Event()
        self.lock = threading.Lock()
        self.heartbeat = time.monotonic()
        self.event = None
        self.result = None
        self.status = "Kapcsolódás és modellbetöltés…"
        self.error = None
        self.thread = threading.Thread(target=self._run, daemon=True)

    @property
    def running(self):
        return self.thread.is_alive()

    def start(self):
        self.thread.start()
        return self

    def stop(self):
        self.stop_event.set()

    def snapshot(self):
        with self.lock:
            self.heartbeat = time.monotonic()
            return self.event, self.status, self.error

    def _run(self):
        reader = None
        observations = None
        detections = None
        directory = None
        origin = None
        analysis_started = time.monotonic()
        try:
            source = resolve_source(self.source)
            if self.stop_event.is_set():
                return
            config = self.config or load_yaml(self.root / "config/detection.yaml", DetectionConfig)
            detector = YoloDetector(self.root, config)
            started = time.monotonic()
            reader = _LatestFrame(source, self.stop_event)
            reader.thread.start()
            counter = TrackCounter()
            lights = LightAnalyzer(self.regions)
            high = max(0.1, config.confidence)
            low = min(0.1, high / 2)
            previous = None
            frames = 0
            with TemporaryDirectory(prefix="smarttraffic-live-") as temporary:
                tracker = Path(temporary) / "tracker.yaml"
                tracker.write_text(
                    yaml.safe_dump(
                        {
                            "tracker_type": "bytetrack",
                            "track_high_thresh": high,
                            "track_low_thresh": low,
                            "new_track_thresh": high,
                            "track_buffer": 30,
                            "match_thresh": 0.8,
                            "fuse_score": True,
                        }
                    ),
                    encoding="utf-8",
                )
                while not self.stop_event.is_set():
                    now = time.monotonic()
                    if now - started >= self.max_seconds or now - self.heartbeat > 30:
                        break
                    if reader.error:
                        raise ValueError(reader.error)
                    latest = reader.get()
                    if latest is None or (previous is not None and latest[0] <= previous):
                        self.stop_event.wait(0.02)
                        continue
                    stamp, frame = latest[:2]
                    if now - stamp > 20:
                        raise ValueError("Több mint 20 másodperce nem érkezett friss kép.")
                    seconds = stamp - started
                    if getattr(reader, "snapshot", False):
                        event = analyze_snapshot(detector, frame, self.regions, seconds)
                        frames += 1
                        event.update(received_at=stamp, seconds=seconds, frames=frames)
                        event["source_captured_at"] = latest[2] if len(latest) > 2 else None
                        with self.lock:
                            self.event = event
                            self.status = "Frissülő kamerakép elemzése (30 másodperces lekérés)"
                        previous = stamp
                        continue
                    duration = observation_duration(stamp, previous, self.fps)
                    if origin is None:
                        origin = stamp
                        directory = output_directory(self.root, "live")
                        observations = (directory / "observations.jsonl").open(
                            "w", encoding="utf-8"
                        )
                        detections = (directory / "detections.jsonl").open("w", encoding="utf-8")
                    seconds = stamp - origin
                    objects = _objects(detector, frame, tracker, low)
                    counter.update(seconds, duration, objects)
                    readings = lights.update(frame, objects, seconds, duration)
                    image = annotate_lights(_annotate(frame, objects, counter), readings)
                    height, width = frame.shape[:2]
                    observations.write(
                        json.dumps(
                            {
                                "seconds": seconds,
                                "duration": duration,
                                "frame_index": frames,
                                "objects": [
                                    {
                                        "track_id": obj.track_id,
                                        "category": obj.category,
                                        "bbox": [
                                            max(0.0, min(1.0, value / scale))
                                            for value, scale in zip(
                                                obj.bbox, (width, height, width, height)
                                            )
                                        ],
                                    }
                                    for obj in objects
                                    if obj.category in TRAFFIC_CATEGORIES
                                    and obj.track_id is not None
                                ],
                            }
                        )
                        + "\n"
                    )
                    current = [obj for obj in objects if obj.category in TRAFFIC_CATEGORIES]
                    diagnostic = getattr(detector, "last_diagnostics", {})
                    detections.write(
                        json.dumps(
                            {
                                "seconds": seconds,
                                "frame_index": frames,
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
                                        "diagnostics": diagnostic,
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
                    frames += 1
                    event = {
                        "image": image,
                        "received_at": stamp,
                        "seconds": seconds,
                        "frames": frames,
                        "sample_duration_seconds": duration,
                        "summary": counter.summary(),
                        "tracks": counter.rows(),
                        "lights": readings,
                        "traffic_lights": lights.summary(),
                        "detections_by_category": {
                            name: sum(
                                obj.category == name and obj.above_threshold for obj in current
                            )
                            for name in TRAFFIC_CATEGORIES
                        },
                        "diagnostics": diagnostic if config.diagnostics else None,
                        "config": getattr(detector, "config", config).model_dump(),
                        "runtime": detector.runtime_info()
                        if hasattr(detector, "runtime_info")
                        else {},
                    }
                    # Positions go to disk; only the latest preview remains in memory.
                    lights.rows.clear()
                    with self.lock:
                        self.event = event
                        self.status = "Élő elemzés"
                    previous = stamp
                    self.stop_event.wait(max(0, 1 / self.fps - (time.monotonic() - now)))
            self.status = "Az élő elemzés leállt."
        except Exception as exc:
            self.error = str(exc)
            self.status = "Az élő elemzés megszakadt."
        finally:
            self.stop_event.set()
            if observations is not None:
                observations.close()
            if detections is not None:
                detections.close()
            if directory is not None and self.event is not None:
                try:
                    import cv2

                    result = {
                        key: value
                        for key, value in self.event.items()
                        if key not in {"image", "received_at", "seconds"}
                    }
                    result.update(
                        input_name="Live " + (urlsplit(self.source).hostname or "camera"),
                        input_sha256=hashlib.sha256(directory.name.encode()).hexdigest(),
                        source_kind="live",
                        time_basis="monotonic seconds since first analyzed frame",
                        requested_seconds=self.max_seconds,
                        duration_seconds=(
                            self.event["seconds"] + self.event["sample_duration_seconds"]
                        ),
                        processing_seconds=time.monotonic() - analysis_started,
                        fps=self.fps,
                        width=width,
                        height=height,
                        config=getattr(detector, "config", config).model_dump(),
                        directory=str(directory),
                        error=self.error,
                    )
                    ok, preview = cv2.imencode(".jpg", self.event["image"])
                    if not ok:
                        raise ValueError("Could not save live preview")
                    (directory / "preview.jpg").write_bytes(preview.tobytes())
                    save_json(directory / "analysis.json", result)
                    self.result = result
                except Exception as exc:
                    self.error = str(exc)
            if reader is not None:
                reader.thread.join(timeout=11)
            if self.error is None:
                self.status = "Az élő elemzés leállt."


def fresh(event) -> bool:
    return (
        event is not None
        and math.isfinite(event["received_at"])
        and (time.monotonic() - event["received_at"] < 2)
    )
