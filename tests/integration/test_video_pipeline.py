import hashlib
import importlib.util
import json
import shutil

import pytest
import yaml

from smarttraffic_ai import video
from smarttraffic_ai.config import project_root
from smarttraffic_ai.video import TrackedObject, process_video

cv2 = pytest.importorskip("cv2")
np = pytest.importorskip("numpy")

pytestmark = pytest.mark.skipif(
    not shutil.which("ffmpeg") or importlib.util.find_spec("lap") is None,
    reason="FFmpeg és a vision függőségek szükségesek",
)


@pytest.fixture
def sample_video(monkeypatch):
    root = project_root()
    path = root / "outputs/video-validation/videos/sample.mp4"
    path.parent.mkdir(parents=True)
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), 10, (64, 64))
    assert writer.isOpened()
    for _ in range(8):
        writer.write(np.zeros((64, 64, 3), dtype=np.uint8))
    writer.release()
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    (root / "config/traffic-lights.yaml").write_text(
        yaml.safe_dump(
            {
                "profiles": {
                    digest: [{"id": "test-signal", "kind": "vehicle", "bounds": [0, 0, 0.5, 0.5]}]
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(video, "YoloDetector", lambda *_: object())
    monkeypatch.setattr(
        video,
        "_objects",
        lambda *_: [
            TrackedObject(1, "car", 0.9, (5, 5, 30, 30)),
            TrackedObject(2, "handbag", 0.9, (35, 35, 50, 50)),
        ],
    )
    return path


def test_video_export_and_progress(sample_video):
    updates = []
    result = process_video(
        project_root(), sample_video, on_progress=lambda event, image: updates.append(event)
    )
    assert result["frames"] == 8
    assert result["duration_seconds"] == pytest.approx(0.8)
    assert result["summary"]["total_unique"] == 1
    assert result["tracks"][0]["visible_seconds"] == pytest.approx(0.8)
    assert all(track["category"] == "car" for track in result["tracks"])
    assert result["traffic_lights"][0]["kind"] == "vehicle"
    assert result["traffic_lights"][0]["state_seconds"]["unknown"] == pytest.approx(0.8)
    assert updates[0]["summary"]["total_unique"] == 0
    assert updates[-1]["summary"]["total_unique"] == 1
    capture = cv2.VideoCapture(result["video_path"])
    assert capture.isOpened()
    assert int(capture.get(cv2.CAP_PROP_FRAME_COUNT)) == 8
    capture.release()
    from pathlib import Path

    directory = Path(result["directory"])
    assert json.loads((directory / "analysis.json").read_text(encoding="utf-8"))["frames"] == 8
    assert "handbag" not in (directory / "tracks.csv").read_text(encoding="utf-8-sig")
    assert (directory / "traffic-lights.csv").is_file()


def test_dashboard_can_process_a_video_sample(sample_video):
    from streamlit.testing.v1 import AppTest

    app = AppTest.from_string(
        "from smarttraffic_ai.config import project_root\n"
        "from smarttraffic_ai.dashboard_video import render_video_tab\n"
        "render_video_tab(project_root(), True)\n"
    ).run()
    assert not app.exception
    app.radio[0].set_value("Mintavideó").run()
    assert not app.exception
    app.button[0].click().run(timeout=20)
    assert not app.exception
    assert app.session_state["video_result"]["frames"] == 8
    assert app.session_state["video_result"]["summary"]["total_unique"] == 1
    assert app.session_state["video_result"]["traffic_lights"][0]["kind"] == "vehicle"


def test_failed_inference_closes_encoder(sample_video, monkeypatch):
    encoders = []
    original_popen = video.subprocess.Popen

    def remember(*args, **kwargs):
        encoder = original_popen(*args, **kwargs)
        encoders.append(encoder)
        return encoder

    def fail(*args):
        raise RuntimeError("inference failed")

    monkeypatch.setattr(video.subprocess, "Popen", remember)
    monkeypatch.setattr(video, "_objects", fail)
    with pytest.raises(RuntimeError, match="inference failed"):
        process_video(project_root(), sample_video)
    assert len(encoders) == 1 and encoders[0].poll() is not None
    assert not list((project_root() / "outputs").glob("video-*/analysis.json"))
