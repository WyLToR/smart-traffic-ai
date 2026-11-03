from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from smarttraffic_ai.simulation import binary

DASHBOARD = Path(__file__).resolve().parents[2] / "src/smarttraffic_ai/dashboard.py"


def test_dashboard_starts_and_scenario_can_change():
    app = AppTest.from_file(str(DASHBOARD))
    app.run(timeout=20)
    assert not app.exception
    app.selectbox[0].set_value("variable").run()
    assert not app.exception
    assert app.selectbox[0].value == "variable"


def test_dashboard_can_simulate_and_reopen_same_result():
    try:
        binary("sumo")
    except FileNotFoundError:
        pytest.skip("SUMO nem érhető el")
    app = AppTest.from_file(str(DASHBOARD))
    app.run(timeout=20)
    app.button[0].click().run(timeout=30)
    assert not app.exception
    assert "run" in app.session_state
    # Reopening the same result must not produce duplicate widget IDs.
    next(
        button for button in app.button if button.label == "Mentett eredmény megnyitása"
    ).click().run()
    assert not app.exception
