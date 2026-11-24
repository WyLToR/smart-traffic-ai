"""Explicit, cached temporal resampling; the detector still processes every input frame."""

import json
import math
import os
import shutil
import subprocess
import time
from pathlib import Path
from tempfile import NamedTemporaryFile

from smarttraffic_ai.config import AppConfig, load_yaml
from smarttraffic_ai.samples import video_digest


def prepare_analysis_video(root: Path, source: Path, digest: str, fps_limit: int | None):
    if fps_limit not in {None, 15, 30}:
        raise ValueError("Az elemzési korlát 15 vagy 30 FPS lehet, vagy minden képkocka.")
    info = {"requested_fps": fps_limit, "resampled": False}
    if fps_limit is None:
        return source, info
    import cv2

    capture = cv2.VideoCapture(str(source))
    try:
        if not capture.isOpened():
            raise ValueError("Az eredeti videó nem olvasható.")
        source_fps = capture.get(cv2.CAP_PROP_FPS)
    finally:
        capture.release()
    if not math.isfinite(source_fps) or source_fps <= 0:
        raise ValueError("Az eredeti videó FPS-e nem ismert.")
    info.update(source_fps=source_fps)
    if source_fps <= fps_limit:
        return source, info
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise FileNotFoundError("Az elemzési videóváltozathoz FFmpeg szükséges.")
    outputs = root / load_yaml(root / "config/app.yaml", AppConfig).output_dir
    directory = outputs / f"video-proxy-{digest[:16]}-{fps_limit}"
    directory.mkdir(parents=True, exist_ok=True)
    destination, metadata = directory / "analysis-input.mp4", directory / "source.json"
    identity = {"source_sha256": digest, "fps_limit": fps_limit, "version": 1}
    try:
        cached = json.loads(metadata.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        cached = None
    if (
        destination.is_file()
        and isinstance(cached, dict)
        and cached.get("identity") == identity
        and cached.get("proxy_sha256") == video_digest(destination)
    ):
        info.update(resampled=True, cache_hit=True)
        return destination, info
    temporary = None
    started = time.perf_counter()
    try:
        with NamedTemporaryFile(dir=directory, suffix=".mp4", delete=False) as stream:
            temporary = Path(stream.name)
        result = subprocess.run(
            [
                ffmpeg,
                "-hide_banner",
                "-loglevel",
                "error",
                "-nostdin",
                "-xerror",
                "-y",
                "-i",
                str(source),
                "-map",
                "0:v:0",
                "-an",
                "-vf",
                f"fps=fps={fps_limit}:round=near",
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-crf",
                "18",
                "-pix_fmt",
                "yuv420p",
                "-fps_mode",
                "cfr",
                "-movflags",
                "+faststart",
                str(temporary),
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        if result.returncode:
            raise RuntimeError(
                "Az elemzési videóváltozat nem készíthető el: "
                + result.stderr.decode(errors="replace")[-1500:]
            )
        capture = cv2.VideoCapture(str(temporary))
        try:
            if not capture.isOpened() or not capture.read()[0]:
                raise ValueError("Az előkészített videó nem dekódolható.")
            if abs(capture.get(cv2.CAP_PROP_FPS) - fps_limit) > 0.01:
                raise ValueError("Az előkészített videó FPS-e nem egyezik a választott értékkel.")
        finally:
            capture.release()
        temporary.replace(destination)
        metadata.write_text(
            json.dumps({"identity": identity, "proxy_sha256": video_digest(destination)}),
            encoding="utf-8",
        )
        info.update(
            resampled=True, cache_hit=False, conversion_seconds=time.perf_counter() - started
        )
        return destination, info
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
