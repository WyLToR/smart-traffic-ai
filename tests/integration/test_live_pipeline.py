import io
import threading
import time
from types import SimpleNamespace

import pytest

from smarttraffic_ai import live
from smarttraffic_ai.config import project_root
from smarttraffic_ai.video import TrackedObject

cv2 = pytest.importorskip("cv2")
np = pytest.importorskip("numpy")


def test_snapshot_counts_are_per_image_without_track_ids_or_durations():
    def box(category):
        return SimpleNamespace(
            cls=np.array(category), conf=np.array(0.9), xyxy=np.array([[5, 5, 30, 30]])
        )

    result = SimpleNamespace(boxes=[box(0), box(0), box(1)], names={0: "car", 1: "handbag"})
    detector = SimpleNamespace(
        model=SimpleNamespace(predict=lambda *args, **kwargs: [result]),
        config=SimpleNamespace(confidence=0.35, image_size=640, device="cpu"),
        class_ids=[0],
        light_class_ids=[],
    )
    frame = np.zeros((64, 64, 3), dtype=np.uint8)
    first = live.analyze_snapshot(detector, frame, [], 1)
    second = live.analyze_snapshot(detector, frame, [], 31)
    assert first["counts"]["car"] == second["counts"]["car"] == 2
    assert first["source_kind"] == "snapshot"
    assert len(first["objects"]) == 2
    assert "tracks" not in first and "summary" not in first
    assert all(set(obj) == {"category", "confidence", "bbox"} for obj in first["objects"])


def test_identical_snapshot_is_not_reprocessed_and_polling_waits(monkeypatch):
    content = cv2.imencode(".jpg", np.zeros((64, 64, 3), dtype=np.uint8))[1].tobytes()
    monkeypatch.setattr(live, "urlopen", lambda *args, **kwargs: io.BytesIO(content))

    class Stop:
        waits = []

        def is_set(self):
            return len(self.waits) == 2

        def wait(self, seconds):
            self.waits.append(seconds)

    stop = Stop()
    reader = live._LatestFrame("https://cam.idokep.hu/kamera.php?user=kevenet", stop)
    frames = []
    monkeypatch.setattr(reader, "_publish", frames.append)
    reader._read_images()
    assert reader.snapshot
    assert len(frames) == 1
    assert stop.waits == [30, 30]


def test_budapest_reader_preserves_source_timestamp(monkeypatch):
    content = cv2.imencode(".jpg", np.zeros((64, 64, 3), dtype=np.uint8))[1].tobytes()
    monkeypatch.setattr(
        live, "fetch_budapest_image", lambda camera_id: (content, "2026-11-03 11:10:25")
    )
    stop = threading.Event()
    reader = live._LatestFrame(
        "https://kozutfigyelo.budapestkozut.hu/list/camerahistory?id=10003", stop
    )
    reader.thread.start()
    try:
        deadline = time.monotonic() + 2
        while reader.get() is None and time.monotonic() < deadline:
            time.sleep(0.01)
        assert reader.snapshot
        assert reader.get()[2] == "2026-11-03 11:10:25"
    finally:
        stop.set()
        reader.thread.join(2)
    assert not reader.thread.is_alive()


def test_hls_segment_delivery_is_paced_and_stoppable(tmp_path, monkeypatch):
    path = tmp_path / "sample.mp4"
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), 10, (64, 64))
    for _ in range(20):
        writer.write(np.zeros((64, 64, 3), dtype=np.uint8))
    writer.release()
    requests = []

    def fetch(url, timeout):
        requests.append(url)
        if url.endswith(".m3u8"):
            content = b"#EXTM3U\n#EXT-X-MEDIA-SEQUENCE:42\n#EXTINF:2,\nsegment.ts\n"
        else:
            content = path.read_bytes()
        response = io.BytesIO(content)
        response.url = url
        return response

    monkeypatch.setattr(live, "urlopen", fetch)
    stop = threading.Event()
    reader = live._LatestFrame("https://camera/live.m3u8", stop)
    reader.thread.start()
    try:
        deadline = time.monotonic() + 3
        while reader.get() is None and time.monotonic() < deadline:
            time.sleep(0.01)
        first = reader.get()
        assert first is not None, reader.error
        time.sleep(0.25)
        assert reader.get()[0] > first[0]
        assert reader.error is None
        # An entire segment was not consumed instantly or downloaded repeatedly.
        assert requests == ["https://camera/live.m3u8", "https://camera/segment.ts"]
    finally:
        stop.set()
        reader.thread.join(2)
    assert not reader.thread.is_alive()


@pytest.fixture
def fake_live_source(monkeypatch):
    class Reader:
        def __init__(self, source, stop):
            self.stop = stop
            self.error = None
            self.thread = threading.Thread(target=lambda: stop.wait(5), daemon=True)

        def get(self):
            return time.monotonic(), np.zeros((64, 64, 3), dtype=np.uint8)

    monkeypatch.setattr(live, "_LatestFrame", Reader)
    monkeypatch.setattr(live, "resolve_source", lambda url: url)
    monkeypatch.setattr(live, "YoloDetector", lambda *args: object())
    monkeypatch.setattr(
        live,
        "_objects",
        lambda *args: [
            TrackedObject(1, "car", 0.9, (5, 5, 30, 30)),
            TrackedObject(2, "handbag", 0.9, (35, 35, 50, 50)),
        ],
    )


def test_live_counts_stop_and_restart_without_id_leaks(fake_live_source):
    for _ in range(2):
        session = live.LiveSession(project_root(), "https://camera/live", max_seconds=1).start()
        session.thread.join(4)
        event, status, error = session.snapshot()
        assert not session.running
        assert error is None
        assert event["frames"] >= 3
        assert event["summary"]["total_unique"] == 1
        assert [track["category"] for track in event["tracks"]] == ["car"]
        assert event["tracks"][0]["visible_seconds"] <= 1.01
        assert session.stop_event.is_set()


def test_live_failure_stops_reader(fake_live_source, monkeypatch):
    def fail(*args):
        raise RuntimeError("inference failed")

    monkeypatch.setattr(live, "_objects", fail)
    session = live.LiveSession(project_root(), "https://camera/live").start()
    session.thread.join(3)
    assert not session.running
    assert session.error == "inference failed"
    assert session.stop_event.is_set()


def test_dashboard_live_start_stop_and_blob_error(fake_live_source):
    from streamlit.testing.v1 import AppTest

    app = AppTest.from_string(
        "from smarttraffic_ai.config import project_root\n"
        "from smarttraffic_ai.dashboard_video import render_video_tab\n"
        "render_video_tab(project_root(), True)\n"
    ).run()
    app.radio[0].set_value("Élő forrás").run()
    assert not app.exception
    app.button[0].click().run()
    session = app.session_state["live_session"]
    try:
        assert session.running
        time.sleep(0.7)
        app.run()
        assert not app.exception
        assert len(app.dataframe) >= 2
        app.button[1].click().run()
        session.thread.join(3)
        assert not session.running
        app.run()
        assert not app.exception
        app.text_input[0].set_value("blob:https://camera/123").run()
        assert app.error
        assert app.button[0].disabled
    finally:
        session.stop()
        session.thread.join(3)


def test_dashboard_snapshot_has_per_image_counts(fake_live_source, monkeypatch):
    from streamlit.testing.v1 import AppTest

    live._LatestFrame.snapshot = True
    counts = {name: int(name == "car") for name in live.TRAFFIC_CATEGORIES}
    monkeypatch.setattr(
        live,
        "analyze_snapshot",
        lambda detector, frame, regions, seconds: {
            "source_kind": "snapshot",
            "image": frame,
            "counts": counts,
            "lights": [],
            "objects": [],
        },
    )
    app = AppTest.from_string(
        "from smarttraffic_ai.config import project_root\n"
        "from smarttraffic_ai.dashboard_video import render_video_tab\n"
        "render_video_tab(project_root(), True)\n"
    ).run()
    app.radio[0].set_value("Élő forrás").run()
    app.button[0].click().run()
    session = app.session_state["live_session"]
    try:
        time.sleep(0.1)
        app.run()
        assert not app.exception
        assert session.event["counts"]["car"] == 1
        assert any("Ezen a képen" in table.value.columns for table in app.dataframe)
        assert any("nincs folyamatos videó" in info.value for info in app.info)
    finally:
        session.stop()
        session.thread.join(3)
