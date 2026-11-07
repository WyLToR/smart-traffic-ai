import os
from pathlib import Path

import pytest

from smarttraffic_ai.config import load_yaml, project_root
from smarttraffic_ai.detection import DetectionConfig, DetectionResult, detect_file
from smarttraffic_ai.profiles import DETECTION_PROFILES


@pytest.mark.vision
@pytest.mark.parametrize("profile_id", list(DETECTION_PROFILES))
@pytest.mark.parametrize("extension", ["jpg", "png"])
def test_local_model_on_explicitly_selected_traffic_image(profile_id, extension):
    image = os.environ.get("SMARTTRAFFIC_MODEL_TEST_IMAGE")
    if not image:
        pytest.skip("Set SMARTTRAFFIC_MODEL_TEST_IMAGE to opt in to real inference")
    pytest.importorskip("ultralytics")
    repository = Path(__file__).resolve().parents[2]
    config = load_yaml(repository / "config/detection.yaml", DetectionConfig)
    config = DETECTION_PROFILES[profile_id].apply(config)
    model = repository / config.model_path
    assert model.is_file(), "An existing local model is required; no download is performed"
    config = DetectionConfig.model_validate(
        {**config.model_dump(), "model_path": str(model), "diagnostics": True}
    )
    from PIL import Image

    path = project_root() / f"traffic.{extension}"
    with Image.open(image) as source:
        source.convert("RGB").save(path)
    result_path = detect_file(project_root(), path, config=config)
    result = DetectionResult.model_validate_json(result_path.read_text(encoding="utf-8"))
    assert result.source == "yolo" and result.objects
    assert (result_path.parent / "diagnostics.json").is_file()
    assert result.config.profile_id == profile_id
    assert all(0 <= obj.bbox[0] < obj.bbox[2] <= result.width for obj in result.objects)
    assert all(0 <= obj.bbox[1] < obj.bbox[3] <= result.height for obj in result.objects)
