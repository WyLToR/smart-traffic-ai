from __future__ import annotations

import math
import os
import shutil
import subprocess
from pathlib import Path

from smarttraffic_ai.flow import CameraProfile, FlowMeasurement


def draw_flow_frame(frame, camera: CameraProfile, events=(), frame_index=-1):
    import cv2

    image = frame.copy()
    height, width = image.shape[:2]

    def pixel(point):
        return round(point[0] * width), round(point[1] * height)

    for zone in camera.zones:
        a, b, c, d = zone.bounds
        cv2.rectangle(image, pixel((a, b)), pixel((c, d)), (180, 180, 180), 1)
    for index, line in enumerate(camera.lines):
        color = (50, 230, 50) if line.role == "entry" else (0, 170, 255)
        cv2.line(image, pixel(line.start), pixel(line.end), color, 3)
        dx, dy = line.end[0] - line.start[0], line.end[1] - line.start[1]
        length = math.hypot(dx, dy)
        sign = 1 if line.inbound == "negative_to_positive" else -1
        midpoint = ((line.start[0] + line.end[0]) / 2, (line.start[1] + line.end[1]) / 2)
        step = (-dy / length * sign * 0.04, dx / length * sign * 0.04)
        cv2.arrowedLine(
            image,
            pixel((midpoint[0] - step[0], midpoint[1] - step[1])),
            pixel((midpoint[0] + step[0], midpoint[1] + step[1])),
            color,
            2,
        )
        selected = [e for e in events if e.line_id == line.id and e.frame_index <= frame_index]
        inbound = sum(e.direction == "inbound" for e in selected)
        outbound = sum(e.direction == "outbound" for e in selected)
        label = f"{line.id} [{line.approach}/{line.role}] IN:{inbound} OUT:{outbound}"
        cv2.rectangle(image, (0, index * 25), (min(width, 650), (index + 1) * 25), (20, 20, 20), -1)
        cv2.putText(
            image, label, (5, 19 + index * 25), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1, cv2.LINE_AA
        )
    return image


def render_flow_video(analysis: Path, measurement_path: Path) -> Path:
    import cv2

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise FileNotFoundError("A jelölt mérési videó mentéséhez FFmpeg szükséges.")
    measurement = FlowMeasurement.model_validate_json(measurement_path.read_text(encoding="utf-8"))
    directory = measurement_path.parent
    partial = directory / "flow-temporary.mp4"
    output = directory / "flow-annotated.mp4"
    capture = cv2.VideoCapture(str(analysis.parent / "annotated.mp4"))
    writer = None
    try:
        if not capture.isOpened():
            raise ValueError("A korábbi jelölt videó nem nyitható meg.")
        fps = capture.get(cv2.CAP_PROP_FPS)
        width, height = (
            int(capture.get(cv2.CAP_PROP_FRAME_WIDTH)),
            int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT)),
        )
        writer = cv2.VideoWriter(
            str(partial), cv2.VideoWriter_fourcc(*"mp4v"), fps, (width, height)
        )
        if not writer.isOpened():
            raise ValueError("A mérési előnézet nem írható.")
        index = 0
        while True:
            ok, frame = capture.read()
            if not ok:
                break
            writer.write(draw_flow_frame(frame, measurement.camera, measurement.events, index))
            index += 1
        if index != measurement.frames:
            raise ValueError("A mérési előnézet és a követési export képkockaszáma eltér.")
    finally:
        capture.release()
        if writer is not None:
            writer.release()
    try:
        subprocess.run(
            [
                ffmpeg,
                "-y",
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                str(partial),
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
                str(output),
            ],
            check=True,
            capture_output=True,
            timeout=max(60, measurement.duration_seconds * 2),
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
    finally:
        partial.unlink(missing_ok=True)
    return output
