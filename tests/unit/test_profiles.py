import io
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from smarttraffic_ai import model_store
from smarttraffic_ai.detection import TRAFFIC_CATEGORIES, DetectionConfig, predict_frame
from smarttraffic_ai.profiles import DETECTION_PROFILES


@pytest.fixture(autouse=True)
def isolated_model_cache():
    model_store.clear_model_cache()
    yield
    model_store.clear_model_cache()


@pytest.mark.parametrize(
    "name,model,size,confidence,maximum",
    [
        ("fast", "yolo11n.pt", 640, 0.25, 300),
        ("balanced", "yolo26n.pt", 960, 0.20, 500),
        ("detailed", "yolo26l.pt", 1280, 0.15, 1000),
    ],
)
def test_profile_applies_parameters_and_preserves_camera_settings(
    name, model, size, confidence, maximum
):
    config = DETECTION_PROFILES[name].apply(DetectionConfig(classes=["car"], diagnostics=True))
    assert Path(config.model_path).name == model
    assert (config.image_size, config.confidence, config.max_detections) == (
        size,
        confidence,
        maximum,
    )
    assert config.classes == ["car"] and config.diagnostics
    assert config.device == "cpu" and config.processing_mode == "full-frame"
    with pytest.raises(ValidationError):
        DetectionConfig.model_validate({**config.model_dump(), "image_size": 0})


def test_profile_rejects_a_different_model():
    with pytest.raises(ValidationError, match="modell"):
        DetectionConfig(profile_id="fast", model_path="models/yolo26l.pt")


def test_cache_reuses_weights_and_invalidates_changed_files(tmp_path, monkeypatch):
    path = tmp_path / "model.pt"
    path.write_bytes(b"first")
    calls = []

    def load(path):
        calls.append(path)
        return object()

    monkeypatch.setattr(model_store, "_load_yolo", load)
    first, hit = model_store.load_model(path)
    second, second_hit = model_store.load_model(path)
    assert first is second and not hit and second_hit and len(calls) == 1
    path.write_bytes(b"changed weights")
    changed, hit = model_store.load_model(path)
    assert changed is not first and not hit and len(calls) == 2
    model_store.clear_model_cache()
    assert first.model is not None  # Active handles survive cache clearing.
    assert model_store.load_model(path)[0] is not changed


def test_missing_and_corrupt_models_are_reported_without_download(tmp_path, monkeypatch):
    with pytest.raises(FileNotFoundError, match="YOLO"):
        model_store.load_model(tmp_path / "missing.pt")

    def fail(*args):
        raise RuntimeError("invalid checkpoint")

    monkeypatch.setitem(sys.modules, "ultralytics", SimpleNamespace(YOLO=fail))
    path = tmp_path / "broken.pt"
    path.write_bytes(b"invalid")
    with pytest.raises(ValueError, match="broken.pt"):
        model_store.load_model(path)
    assert path.read_bytes() == b"invalid"


def test_official_download_is_validated_and_not_repeated(tmp_path, monkeypatch):
    requests = []

    def fetch(request, timeout):
        requests.append(request.full_url)
        return io.BytesIO(b"test checkpoint")

    monkeypatch.setattr(model_store, "urlopen", fetch)
    monkeypatch.setattr(
        model_store,
        "_load_yolo",
        lambda path: SimpleNamespace(names=dict(enumerate(TRAFFIC_CATEGORIES))),
    )
    path = model_store.download_model(tmp_path, "yolo26l.pt")
    assert path.read_bytes() == b"test checkpoint" and path.with_suffix(".sha256").is_file()
    assert model_store.download_model(tmp_path, "yolo26l.pt") == path
    assert requests == ["https://github.com/ultralytics/assets/releases/download/v8.4.0/yolo26l.pt"]
    with pytest.raises(ValueError):
        model_store.download_model(tmp_path, "unknown.pt")


def test_invalid_download_leaves_no_checkpoint(tmp_path, monkeypatch):
    monkeypatch.setattr(model_store, "urlopen", lambda *args, **kwargs: io.BytesIO(b"broken"))

    def fail(path):
        raise ValueError("corrupt model")

    monkeypatch.setattr(model_store, "_load_yolo", fail)
    with pytest.raises(ValueError):
        model_store.download_model(tmp_path, "yolo26l.pt")
    assert not list((tmp_path / "models").iterdir())


@pytest.mark.parametrize(
    "failure", [MemoryError(), RuntimeError("DefaultCPUAllocator: not enough memory")]
)
def test_detailed_memory_fallback_retries_the_same_frame(failure):
    np = pytest.importorskip("numpy")
    calls = []

    def predict(frame, **kwargs):
        calls.append(kwargs["imgsz"])
        if kwargs["imgsz"] > 640:
            raise failure
        return [SimpleNamespace(boxes=None, names={0: "person"})]

    detector = SimpleNamespace(
        config=DETECTION_PROFILES["detailed"].apply(DetectionConfig()),
        model=SimpleNamespace(predict=predict),
        class_ids=[0],
        light_class_ids=[],
    )
    predict_frame(detector, np.zeros((24, 32, 3), dtype=np.uint8))
    assert calls == [1280, 960, 640]
    assert detector.config.image_size == 640 and len(detector.fallbacks) == 2


def test_non_memory_failure_is_not_silently_retried():
    np = pytest.importorskip("numpy")

    def fail(*args, **kwargs):
        raise RuntimeError("inference bug")

    detector = SimpleNamespace(
        config=DETECTION_PROFILES["detailed"].apply(DetectionConfig()),
        model=SimpleNamespace(predict=fail),
        class_ids=[0],
        light_class_ids=[],
    )
    with pytest.raises(RuntimeError, match="inference bug"):
        predict_frame(detector, np.zeros((24, 32, 3), dtype=np.uint8))
    assert detector.config.image_size == 1280


def test_image_export_records_effective_fallback_size(tmp_path, monkeypatch):
    from PIL import Image

    from smarttraffic_ai import detection

    class Detector:
        def __init__(self, root, config):
            self.config = config

        def detect(self, image):
            self.config = self.config.model_copy(update={"image_size": 640})
            return []

        def runtime_info(self):
            return {
                "requested_image_size": 1280,
                "effective_image_size": 640,
                "warnings": ["memory fallback"],
            }

    monkeypatch.setattr(detection, "YoloDetector", Detector)
    (tmp_path / "config").mkdir()
    (tmp_path / "config/app.yaml").write_text("{}")
    path = tmp_path / "image.png"
    Image.new("RGB", (64, 64)).save(path)
    output = detection.detect_file(
        tmp_path, path, config=DETECTION_PROFILES["detailed"].apply(DetectionConfig())
    )
    result = detection.DetectionResult.model_validate_json(output.read_text(encoding="utf-8"))
    assert result.config.image_size == 640 and result.config.profile_id == "detailed"
    assert result.runtime["requested_image_size"] == 1280 and result.runtime["warnings"]
