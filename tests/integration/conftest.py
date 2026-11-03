import shutil
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def isolated_project(tmp_path, monkeypatch):
    root = Path(__file__).resolve().parents[2]
    for directory in ("config", "data/scenarios", "sumo"):
        shutil.copytree(root / directory, tmp_path / directory)
    monkeypatch.setenv("SMARTTRAFFIC_ROOT", str(tmp_path))
