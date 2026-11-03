from __future__ import annotations

import os
from pathlib import Path
from typing import Annotated, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

Direction = Literal["N", "S", "E", "W"]
Rate = Annotated[float, Field(ge=0, le=10000, allow_inf_nan=False)]


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Window(Model):
    begin: int = Field(ge=0)
    end: int = Field(gt=0)
    rates: dict[Direction, Rate]

    @model_validator(mode="after")
    def check_window(self):
        if self.end <= self.begin or set(self.rates) != {"N", "S", "E", "W"}:
            raise ValueError("Az időablak legyen pozitív, mind a négy irány intenzitása szükséges.")
        return self


class Scenario(Model):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]*$")
    name: str
    duration: int = Field(ge=1, le=86400)
    seed: int = Field(default=42, ge=0, le=2147483647)
    source: Literal["synthetic", "image-estimate", "mock-estimate"] = "synthetic"
    assumptions: list[str] = Field(min_length=1)
    windows: list[Window] = Field(min_length=1)

    @model_validator(mode="after")
    def check_windows(self):
        cursor = 0
        for window in self.windows:
            if window.begin != cursor:
                raise ValueError("Az időablakok hézag és átfedés nélkül kövessék egymást.")
            cursor = window.end
        if cursor != self.duration:
            raise ValueError("Az időablakok fedjék le a teljes időtartamot.")
        return self


class SignalConfig(Model):
    min_green: int = Field(default=12, ge=1)
    max_green: int = Field(default=40, ge=1)
    ns_green: int = Field(default=25, ge=1)
    ew_green: int = Field(default=25, ge=1)
    yellow: int = Field(default=3, ge=1)
    all_red: int = Field(default=2, ge=1)

    @model_validator(mode="after")
    def check_green(self):
        if not self.min_green <= self.ns_green <= self.max_green:
            raise ValueError("Az észak–déli zöldidő a minimum és maximum közé essen.")
        if not self.min_green <= self.ew_green <= self.max_green:
            raise ValueError("A kelet–nyugati zöldidő a minimum és maximum közé essen.")
        return self


class SearchConfig(Model):
    green_candidates: list[Annotated[int, Field(gt=0)]] = Field(min_length=1)
    seeds: list[Annotated[int, Field(ge=0, le=2147483647)]] = Field(min_length=1)
    remaining_weight: float = Field(default=60, ge=0)
    max_wait_weight: float = Field(default=0.1, ge=0)


class AppConfig(Model):
    title: str = "SmartTraffic AI"
    output_dir: str = "outputs"


def project_root() -> Path:
    candidates = [Path(os.environ.get("SMARTTRAFFIC_ROOT", ".")), Path(__file__).parents[2]]
    for candidate in candidates:
        if (candidate / "config/simulation.yaml").is_file():
            return candidate.resolve()
    raise FileNotFoundError(
        "Indítsd a projekt gyökeréből, vagy állítsd be a SMARTTRAFFIC_ROOT értékét."
    )


def load_yaml(path: Path, schema):
    with path.open(encoding="utf-8") as stream:
        return schema.model_validate(yaml.safe_load(stream))


def load_scenario(root: Path, name: str) -> Scenario:
    path = Path(name)
    if not path.is_file():
        if not all(c.isalnum() or c == "-" for c in name):
            raise ValueError("Adj meg létező YAML-fájlt vagy forgatókönyv-azonosítót.")
        path = root / "data/scenarios" / f"{name}.yaml"
    return load_yaml(path, Scenario)
