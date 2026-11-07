from pathlib import Path

from streamlit.testing.v1 import AppTest

from smarttraffic_ai.config import project_root


def test_profile_switch_resets_profile_parameters_and_handles_missing_model():
    app = AppTest.from_string(
        "from smarttraffic_ai.config import project_root\n"
        "from smarttraffic_ai.dashboard_detection import detection_settings\n"
        "import streamlit as st\n"
        "config = detection_settings(project_root(), 'test')\n"
        "st.session_state['selected'] = config.model_dump()\n"
    ).run()
    assert not app.exception
    assert app.session_state["selected"]["profile_id"] == "balanced"
    app.selectbox[0].set_value("fast").run()
    assert not app.exception
    assert app.session_state["selected"]["image_size"] == 640
    app.selectbox[0].set_value("detailed").run()
    assert app.session_state["selected"]["confidence"] == 0.15
    assert Path(app.session_state["selected"]["model_path"]).name == "yolo26l.pt"
    assert any(b.label == "Modell letöltése" for b in app.button)
    (project_root() / "models").mkdir()
    (project_root() / "models/yolo26l.pt").touch()
    app.run()
    assert not any(b.label == "Modell letöltése" for b in app.button)
    app.selectbox[0].set_value("balanced").run()
    assert app.session_state["selected"]["image_size"] == 960
    assert app.session_state["selected"]["max_detections"] == 500
