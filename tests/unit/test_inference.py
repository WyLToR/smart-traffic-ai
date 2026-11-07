from types import SimpleNamespace

import pytest
from PIL import Image

from smarttraffic_ai.detection import DetectionConfig, YoloDetector, detect_file
from smarttraffic_ai.video import TrackCounter, _annotate, _objects

np = pytest.importorskip("numpy")
torch = pytest.importorskip("torch")
Results = pytest.importorskip("ultralytics.engine.results").Results


def detector_for(rows, **settings):
    calls = []

    def predict(frame, **kwargs):
        calls.append((frame.copy(), kwargs))
        return [
            Results(
                frame,
                path="frame",
                names={0: "person", 1: "bicycle", 2: "car", 9: "traffic light", 26: "handbag"},
                boxes=torch.tensor(rows, dtype=torch.float32).reshape(-1, 6),
            )
        ]

    detector = YoloDetector.__new__(YoloDetector)
    detector.model = SimpleNamespace(predict=predict)
    detector.config = DetectionConfig(**settings)
    detector.class_ids = [0, 1, 2]
    detector.light_class_ids = [9]
    return detector, calls


def test_diagnostics_separates_confidence_category_and_preserves_person_bicycle_overlap():
    detector, calls = detector_for(
        [
            [2, 2, 22, 30, 0.9, 0],
            [2, 2, 22, 30, 0.8, 1],
            [30, 2, 50, 30, 0.15, 2],
            [40, 40, 60, 60, 0.9, 26],
        ],
        diagnostics=True,
    )
    objects = detector.detect(Image.new("RGB", (64, 64), "red"))
    assert [obj.category for obj in objects] == ["person", "bicycle"]
    assert list(calls[0][0][0, 0]) == [0, 0, 255]  # PIL RGB -> OpenCV BGR, once.
    assert calls[0][1]["agnostic_nms"] is False
    assert calls[0][1]["classes"] is None
    assert detector.last_diagnostics["model_output_count"] == 4
    assert detector.last_diagnostics["confidence_count"] == 3
    assert detector.last_diagnostics["category_count"] == 2
    assert detector.last_diagnostics["displayed_count"] == 2
    assert detector.last_diagnostics["exported_count"] == 2


@pytest.mark.parametrize("size", [(32, 24), (3840, 2160)])
def test_original_pixel_coordinates_and_empty_result_are_kept(size):
    width, height = size
    detector, calls = detector_for([[1, 2, width - 1, height - 1, 0.9, 0]])
    objects = detector.detect(Image.new("RGB", size))
    assert objects[0].bbox == (1, 2, width - 1, height - 1)
    assert calls[0][0].shape[:2] == (height, width)
    assert calls[0][1]["imgsz"] == 960
    empty, _ = detector_for([])
    assert empty.detect(Image.new("RGB", size)) == []


def test_unconfirmed_detection_survives_tracking_and_does_not_increment_unique_ids(tmp_path):
    import yaml

    detector, calls = detector_for([])
    tracker = tmp_path / "tracker.yaml"
    tracker.write_text(
        yaml.safe_dump(
            {
                "track_high_thresh": 0.25,
                "track_low_thresh": 0.1,
                "new_track_thresh": 0.25,
                "track_buffer": 30,
                "match_thresh": 0.8,
                "fuse_score": True,
            }
        )
    )
    frame = np.zeros((64, 64, 3), dtype=np.uint8)
    assert _objects(detector, frame, tracker, 0.1) == []
    # An object entering after frame 1 has no activated ByteTrack ID on its first observation.
    row = [5, 5, 30, 40, 0.9, 0]
    detector.model = detector_for([row])[0].model
    objects = _objects(detector, frame, tracker, 0.1)
    assert len(objects) == 1 and objects[0].track_id is None
    counter = TrackCounter()
    counter.update(0.1, 0.1, objects)
    assert counter.summary()["total_unique"] == 0
    assert np.any(_annotate(frame, objects, counter)[35:41, 5:31])
    objects = _objects(detector, frame, tracker, 0.1)
    track_id = objects[0].track_id
    assert track_id is not None
    # Occlusion, then reappearance: one persistent ID, not a second unique vehicle.
    detector.model = detector_for([])[0].model
    assert _objects(detector, frame, tracker, 0.1) == []
    detector.model = detector_for([row])[0].model
    assert _objects(detector, frame, tracker, 0.1)[0].track_id == track_id
    detector.model = detector_for([[5, 5, 30, 40, 0.15, 0]])[0].model
    weak_match = _objects(detector, frame, tracker, 0.1)[0]
    assert weak_match.track_id == track_id and not weak_match.above_threshold
    assert len(calls) == 1


def test_corrupt_image_is_rejected_before_model_load(tmp_path, monkeypatch):
    from smarttraffic_ai import detection

    (tmp_path / "config").mkdir()
    (tmp_path / "config/detection.yaml").write_text("{}")
    path = tmp_path / "broken.jpg"
    path.write_bytes(b"not an image")
    monkeypatch.setattr(detection, "YoloDetector", lambda *_: pytest.fail("model loaded"))
    with pytest.raises(OSError):
        detect_file(tmp_path, path)


def test_tracker_coordinates_are_clipped_before_normalized_export():
    detector, _ = detector_for([[1, 1, 60, 60, 0.9, 0]])
    detector.tracker = SimpleNamespace(
        update=lambda *_: np.array(
            [
                [-0.5, -1, 65, 67, 1, 0.9, 0, 0],
            ]
        )
    )
    objects = _objects(detector, np.zeros((64, 64, 3), dtype=np.uint8), None, 0.1)
    assert objects[0].bbox == (0, 0, 64, 64)
    assert detector.last_diagnostics["tracking_boxes_clipped"] == 1


def test_exif_orientation_is_applied_before_inference(tmp_path):
    (tmp_path / "config").mkdir()
    (tmp_path / "config/detection.yaml").write_text("{}")
    (tmp_path / "config/app.yaml").write_text("{}")
    image = Image.new("RGB", (60, 40))
    exif = image.getexif()
    exif[274] = 6
    path = tmp_path / "rotated.jpg"
    image.save(path, exif=exif)
    import json

    result = json.loads(detect_file(tmp_path, path, mock=True).read_text())
    assert (result["width"], result["height"]) == (40, 60)
