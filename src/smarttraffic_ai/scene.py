from __future__ import annotations

import hashlib
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, model_validator

from smarttraffic_ai.config import Direction, Model, Rate, Scenario, SignalConfig, Window
from smarttraffic_ai.detection import (
    MOTOR_VEHICLES,
    TRAFFIC_CATEGORIES,
    Category,
    DetectionConfig,
    DetectionResult,
    Region,
)
from smarttraffic_ai.flow import FlowMeasurement, fingerprint
from smarttraffic_ai.flow_validation import ValidationReport

Count = Annotated[int, Field(ge=0, strict=True)]
MotorCategory = Literal["car", "bus", "truck", "motorcycle"]
DIRECTIONS = ("N", "E", "S", "W")
TURN_DESTINATIONS = {
    "N": {"straight": "S", "left": "E", "right": "W"},
    "E": {"straight": "W", "left": "S", "right": "N"},
    "S": {"straight": "N", "left": "W", "right": "E"},
    "W": {"straight": "E", "left": "N", "right": "S"},
}


class SceneSettings(Model):
    intersection_type: Literal["four_way", "t_junction"] = "four_way"
    missing_arm: Direction = "S"
    lanes: int = Field(default=1, ge=1, le=3)
    arm_length: float = Field(default=250, ge=50, le=2000)
    speed_kmh: float = Field(default=50, ge=10, le=70)
    signalized: bool = True
    simulation_seconds: int = Field(default=120, ge=1, le=3600)
    warmup_seconds: int = Field(default=5, ge=0, le=60)
    seed: int = Field(default=42, ge=0, le=2147483647)
    signals: SignalConfig = Field(default_factory=SignalConfig)
    turns: dict[Literal["straight", "left", "right"], float] = Field(
        default_factory=lambda: {"straight": 0.8, "left": 0.1, "right": 0.1}
    )
    regions: list[Region] = Field(default_factory=list)
    object_directions: dict[int, Direction | None] = Field(default_factory=dict)
    track_directions: dict[int, Direction | None] = Field(default_factory=dict)
    arrival_mode: Literal["configured", "occupancy-weighted", "measured"] = "configured"
    flow_measurement_path: str | None = None
    flow_validation_path: str | None = None
    allow_unvalidated_flow: bool = False
    arrival_rates: dict[Direction, Rate] = Field(
        default_factory=lambda: dict.fromkeys(DIRECTIONS, 0)
    )
    prior_rate: Rate = 300
    video_window_seconds: int = Field(default=10, ge=1, le=300)

    @property
    def approaches(self):
        return [
            d for d in DIRECTIONS if self.intersection_type == "four_way" or d != self.missing_arm
        ]

    @model_validator(mode="after")
    def validate_settings(self):
        DetectionConfig(regions=self.regions)  # Reuse the existing normalized-zone validation.
        if set(self.arrival_rates) != set(DIRECTIONS):
            raise ValueError("Mind a négy irány feltételezett intenzitását add meg.")
        if (
            set(self.turns) != {"straight", "left", "right"}
            or any(not math.isfinite(v) or v < 0 for v in self.turns.values())
            or not math.isclose(sum(self.turns.values()), 1, abs_tol=1e-6)
        ):
            raise ValueError("A kanyarodási arányok nemnegatívak legyenek, összegük 1.")
        mapped = [r.direction for r in self.regions] + [
            d for d in (*self.object_directions.values(), *self.track_directions.values()) if d
        ]
        if any(d not in self.approaches for d in mapped):
            raise ValueError("A megfeleltetés nem hivatkozhat a T-csomópont hiányzó ágára.")
        if any(self.arrival_rates[d] for d in DIRECTIONS if d not in self.approaches):
            raise ValueError("A hiányzó ágon nem lehet érkező forgalom.")
        for d in self.approaches:
            if not any(
                weight > 0 and TURN_DESTINATIONS[d][turn] in self.approaches
                for turn, weight in self.turns.items()
            ):
                raise ValueError(f"A(z) {d} irányból nincs megengedett célirány.")
        return self


class OccupancyWindow(Model):
    begin: float = Field(ge=0)
    end: float = Field(gt=0)
    mean_counts: dict[Direction, dict[Category, Annotated[float, Field(ge=0)]]]

    @model_validator(mode="after")
    def validate_interval(self):
        if self.end <= self.begin:
            raise ValueError("A megfigyelési időablak legyen pozitív.")
        return self


class ApproachScene(Model):
    id: Direction
    observed_counts: dict[Category, Count]
    observed_unique_tracks: Count | None = None
    estimated_queue_length: Count | None = None  # Occupancy does not establish a stopped queue.
    initial_vehicles: dict[MotorCategory, Count]
    vehicle_weights: dict[MotorCategory, Annotated[float, Field(ge=0)]]


class TrafficScene(Model):
    schema_version: Literal[1] = 1
    source_type: Literal["image", "video"]
    source_id: str
    recognition_source: Literal["yolo", "mock"]
    processing_seconds: float = Field(ge=0)
    observation_seconds: float | None = Field(default=None, gt=0)
    initial_observation_seconds: float = Field(default=0, ge=0)
    settings: SceneSettings
    approaches: list[ApproachScene]
    unassigned_counts: dict[Category, Count]
    occupancy_windows: list[OccupancyWindow] = Field(default_factory=list)
    estimated_arrivals: list[Window]
    provenance: dict[str, str]
    assumptions: list[str]
    measured_flow: FlowMeasurement | None = None
    flow_validation: ValidationReport | None = None

    @model_validator(mode="after")
    def validate_scene(self):
        if self.measured_flow is not None and self.settings.arrival_mode != "measured":
            raise ValueError("Mért események és konfigurált/Poisson-érkezések nem keverhetők.")
        if [a.id for a in self.approaches] != self.settings.approaches:
            raise ValueError("A forgalmi irányok és a hálózati sablon eltérnek.")
        self.scenario()  # Validate coverage, rates and the complete simulation horizon.
        for approach in self.approaches:
            if set(approach.observed_counts) != set(TRAFFIC_CATEGORIES):
                raise ValueError("Minden közlekedési kategória darabszáma szükséges.")
            if set(approach.initial_vehicles) != set(MOTOR_VEHICLES):
                raise ValueError("A négy gépjárműtípus kezdeti darabszáma szükséges.")
            if set(approach.vehicle_weights) != set(MOTOR_VEHICLES):
                raise ValueError("A négy gépjárműtípus megfigyelési súlya szükséges.")
        if set(self.unassigned_counts) != set(TRAFFIC_CATEGORIES):
            raise ValueError("Az irány nélküli találatok minden kategóriáját add meg.")
        if self.settings.arrival_mode == "measured":
            measurement = self.measured_flow
            if (
                measurement is None
                or self.source_type != "video"
                or measurement.source_sha256 != self.source_id
            ):
                raise ValueError(
                    "Mért érkezéshez az adott videóhoz tartozó forgalommérés szükséges."
                )
            if self.settings.simulation_seconds != math.ceil(measurement.duration_seconds):
                raise ValueError(
                    "A mért események időhorizontja nem nyújtható vagy extrapolálható."
                )
            report = self.flow_validation
            if report is not None and report.measurement_sha256 != fingerprint(measurement):
                raise ValueError("A pontossági riport másik méréshez tartozik.")
            if not self.settings.allow_unvalidated_flow and not (
                report and report.approved_for_arrivals
            ):
                raise ValueError(
                    "A mérés még nem igazolt beérkezésmérés. "
                    "Ellenőrzött referencia vagy kifejezett kísérleti mód szükséges."
                )
            expected = {d: Counter() for d in self.settings.approaches}
            for track in measurement.initial_tracks:
                if track.approach not in expected:
                    raise ValueError("A kameraág nincs jelen a kiválasztott SUMO-sablonban.")
                if track.vehicle_type in MOTOR_VEHICLES:
                    expected[track.approach][track.vehicle_type] += 1
            for approach in self.approaches:
                if any(
                    approach.initial_vehicles[c] != expected[approach.id][c] for c in MOTOR_VEHICLES
                ):
                    raise ValueError("A kezdeti terhelés és a mérés kezdeti ID-i eltérnek.")
        return self

    def scenario(self):
        return Scenario(
            id="reconstructed-scene",
            name="Képi megfigyelésből készített forgalmi helyzet",
            duration=self.settings.simulation_seconds + self.settings.warmup_seconds,
            seed=self.settings.seed,
            source="mock-estimate"
            if self.recognition_source == "mock"
            else (
                "video-measured"
                if self.settings.arrival_mode == "measured"
                else "video-estimate"
                if self.source_type == "video"
                else "image-estimate"
            ),
            assumptions=self.assumptions,
            windows=self.estimated_arrivals,
        )


def zone_direction(bbox, regions):
    x, y = (bbox[0] + bbox[2]) / 2, bbox[3]
    return next(
        (
            r.direction
            for r in regions
            if r.bounds[0] <= x <= r.bounds[2] and r.bounds[1] <= y <= r.bounds[3]
        ),
        None,
    )


def _counts():
    return {d: Counter(dict.fromkeys(TRAFFIC_CATEGORIES, 0)) for d in DIRECTIONS}


def _finish(
    source_type,
    source_id,
    recognition_source,
    processing_seconds,
    settings,
    initial,
    unassigned,
    weights,
    occupancy,
    duration=None,
    unique=None,
    initial_time=0,
):
    approaches = [
        ApproachScene(
            id=d,
            observed_counts=dict(initial[d]),
            observed_unique_tracks=len(unique[d]) if unique is not None else None,
            initial_vehicles={c: initial[d][c] for c in MOTOR_VEHICLES},
            vehicle_weights={c: weights[d][c] for c in MOTOR_VEHICLES},
        )
        for d in settings.approaches
    ]
    intervals = occupancy or [
        OccupancyWindow(begin=0, end=1, mean_counts={d: dict(initial[d]) for d in DIRECTIONS})
    ]
    # The per-approach prior applies to observed arms only; an arm outside the camera
    # view must not hand its share to the visible ones.
    observed_arms = {r.direction for r in settings.regions} | {
        d for d in (*settings.object_directions.values(), *settings.track_directions.values()) if d
    }
    windows = []
    warmup = settings.warmup_seconds
    if warmup:
        windows.append(Window(begin=0, end=warmup, rates=dict.fromkeys(DIRECTIONS, 0)))
    cursor = warmup
    for index, observed in enumerate(intervals):
        end = warmup + (
            round(observed.end / (duration or 1) * settings.simulation_seconds)
            if occupancy
            else settings.simulation_seconds
        )
        if index == len(intervals) - 1:
            end = warmup + settings.simulation_seconds
        if end <= cursor:
            continue
        if settings.arrival_mode == "configured":
            rates = settings.arrival_rates
        else:
            totals = {
                d: sum(observed.mean_counts[d][c] for c in MOTOR_VEHICLES)
                for d in settings.approaches
            }
            total = sum(totals.values())
            rates = {
                d: (
                    min(10000, settings.prior_rate * len(observed_arms) * totals.get(d, 0) / total)
                    if total
                    else 0
                )
                for d in DIRECTIONS
            }
        windows.append(Window(begin=cursor, end=end, rates=rates))
        cursor = end
    assumptions = [
        "A geometria, sávszám, sebesség és kanyarodás ellenőrzött sablonparaméter; nem YOLO-mérés.",
        "A kezdeti gépjárművek a kijelölt pillanatnyi terhelést követik; "
        "álló sorba helyezésük feltételezés.",
        "A parkoló és mozgó járművek nincsenek szétválasztva; "
        "a pontos pozíció és sorhossz nem mért.",
        "A gyalogosok és kerékpárok megfigyelése megmarad, de ebben a hálózatban nem szimuláltak.",
        "Az irány nélküli találatok kimaradnak a generált járműigényből.",
        "Az érkezések nem mért áthaladások: " + settings.arrival_mode + ".",
        "A videó időablakai a választott szimulációs időhorizontra arányosan átskálázódnak.",
        "A járműtípusok aránya megfigyelt; üres kategóriaeloszlásnál az új érkező személyautó.",
        "T-csomópontnál a nem létező célirányok kimaradnak, "
        "a többi kanyarodási súly újranormalizálódik.",
        "A jelzőlámpa programja feltételezett, nem a kamerán felismert program másolata.",
    ]
    return TrafficScene(
        source_type=source_type,
        source_id=source_id,
        recognition_source=recognition_source,
        processing_seconds=processing_seconds,
        observation_seconds=duration,
        initial_observation_seconds=initial_time,
        settings=settings,
        approaches=approaches,
        unassigned_counts=dict(unassigned),
        occupancy_windows=occupancy,
        estimated_arrivals=windows,
        assumptions=assumptions,
        provenance={
            "observed_counts": "YOLO-detektálás; kézi vagy ellenőrzött zóna-hozzárendelés",
            "initial_vehicles": "megfigyelt pillanatnyi gépjárműszám; helyzetük feltételezett",
            "estimated_queue_length": "ismeretlen; állóképből nem állapítható meg",
            "estimated_arrivals": "konfigurált intenzitás"
            if settings.arrival_mode == "configured"
            else "megfigyelt foglaltsággal súlyozott intenzitási feltételezés; nem érkezésmérés",
            "geometry_and_signals": "felhasználó által kiválasztott sablon és paraméterek",
        },
    )


def analyze_image(observation: DetectionResult, settings: SceneSettings) -> TrafficScene:
    if settings.arrival_mode == "measured":
        raise ValueError("Állóképből nem készíthető mért áthaladási igény.")
    initial = _counts()
    unassigned = Counter(dict.fromkeys(TRAFFIC_CATEGORIES, 0))
    for index, obj in enumerate(observation.objects):
        bbox = (
            obj.bbox[0] / observation.width,
            obj.bbox[1] / observation.height,
            obj.bbox[2] / observation.width,
            obj.bbox[3] / observation.height,
        )
        direction = settings.object_directions.get(index, zone_direction(bbox, settings.regions))
        if direction:
            initial[direction][obj.category] += 1
        else:
            unassigned[obj.category] += 1
    return _finish(
        "image",
        observation.source_id,
        observation.source,
        observation.processing_seconds,
        settings,
        initial,
        unassigned,
        initial,
        [],
    )


def analyze_video(path: Path, settings: SceneSettings) -> TrafficScene:
    data = json.loads(path.read_text(encoding="utf-8"))
    measurement = validation = None
    if settings.arrival_mode == "measured":
        if not settings.flow_measurement_path:
            raise ValueError("Előbb készíts forgalommérést a Forgalommérés lapon.")
        measurement = FlowMeasurement.model_validate_json(
            Path(settings.flow_measurement_path).read_text(encoding="utf-8")
        )
        if measurement.analysis_sha256 != hashlib.sha256(path.read_bytes()).hexdigest():
            raise ValueError("A forgalommérés másik felismerési eredményhez tartozik.")
        if settings.track_directions:
            raise ValueError(
                "Mért módnál a mentett kamerazónák adják az irányt; töröld a kézi ID-felülírásokat."
            )
        if settings.flow_validation_path:
            validation = ValidationReport.model_validate_json(
                Path(settings.flow_validation_path).read_text(encoding="utf-8")
            )
        settings = SceneSettings.model_validate(
            {
                **settings.model_dump(),
                "regions": [r.model_dump() for r in measurement.camera.zones],
                "simulation_seconds": math.ceil(measurement.duration_seconds),
                "arrival_rates": dict.fromkeys(DIRECTIONS, 0),
            }
        )
    observations = path.parent / "observations.jsonl"
    if not observations.is_file():
        raise ValueError("Ehhez a videóhoz nincs pozícióexport. Futtasd újra a videóelemzést.")
    confirmed = {int(track["track_id"]): track["category"] for track in data["tracks"]}
    totals = _counts()
    windows = defaultdict(_counts)
    window_times = Counter()
    unique = {d: set() for d in DIRECTIONS}
    initial, initial_time, unassigned = None, 0, Counter(dict.fromkeys(TRAFFIC_CATEGORIES, 0))
    previous = -1
    observation_digest = hashlib.sha256()
    duration = float(data["duration_seconds"])
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError("A videó időtartama legyen pozitív.")
    with observations.open("rb") as stream:
        for line in stream:
            observation_digest.update(line)
            frame = json.loads(line)
            seconds, exposure = float(frame["seconds"]), float(frame["duration"])
            if not (
                math.isfinite(seconds)
                and seconds >= 0
                and seconds > previous
                and math.isfinite(exposure)
                and exposure > 0
                and seconds + exposure <= duration + 1e-5
            ):
                raise ValueError("Hibás videó-időbélyeg vagy képkockaidő.")
            previous = seconds
            counts, missing = _counts(), Counter(dict.fromkeys(TRAFFIC_CATEGORIES, 0))
            seen = set()
            for obj in frame["objects"]:
                track_id = int(obj["track_id"])
                if track_id not in confirmed or track_id in seen:
                    continue
                seen.add(track_id)
                category = confirmed[track_id]
                if category not in TRAFFIC_CATEGORIES:
                    continue
                bbox = obj["bbox"]
                if len(bbox) != 4 or not all(math.isfinite(v) and 0 <= v <= 1 for v in bbox):
                    raise ValueError("Hibás normalizált videópozíció.")
                direction = settings.track_directions.get(
                    track_id, zone_direction(bbox, settings.regions)
                )
                if direction:
                    counts[direction][category] += 1
                    unique[direction].add(track_id)
                else:
                    missing[category] += 1
            if initial is None:
                initial, unassigned, initial_time = counts, missing, seconds
            # Split exposures at window boundaries, including empty frames.
            begin = seconds
            while begin < seconds + exposure - 1e-9:
                bucket = int(begin // settings.video_window_seconds)
                end = min(seconds + exposure, (bucket + 1) * settings.video_window_seconds)
                weight = end - begin
                window_times[bucket] += weight
                for d in DIRECTIONS:
                    for category in TRAFFIC_CATEGORIES:
                        windows[bucket][d][category] += counts[d][category] * weight
                        totals[d][category] += counts[d][category] * weight
                begin = end
    if initial is None:
        raise ValueError("A videó megfigyelési exportja üres.")
    if (
        measurement is not None
        and observation_digest.hexdigest() != measurement.observations_sha256
    ):
        raise ValueError("A mérés óta megváltozott a tracking-export. Készíts új forgalommérést.")
    occupancy = [
        OccupancyWindow(
            begin=bucket * settings.video_window_seconds,
            end=min(duration, (bucket + 1) * settings.video_window_seconds),
            mean_counts={
                d: {c: windows[bucket][d][c] / window_times[bucket] for c in TRAFFIC_CATEGORIES}
                for d in DIRECTIONS
            },
        )
        for bucket in sorted(windows)
    ]
    if measurement is None:
        scene = _finish(
            "video",
            data["input_sha256"],
            "yolo",
            data["processing_seconds"],
            settings,
            initial,
            unassigned,
            totals,
            occupancy,
            duration,
            unique,
            initial_time,
        )
        if data.get("source_kind") == "live":
            scene.provenance["source_kind"] = "live"
            scene.provenance["time_basis"] = data["time_basis"]
            scene.assumptions.append(
                "Élő videó mintavétele: az időalap az első elemzett képkocka; "
                "a hálózati kimaradás nem számít látható időnek."
            )
            if data.get("error"):
                scene.assumptions.append("Megszakadt élő vizsgálat részeredménye.")
        return _sampling_provenance(scene, data)
    # Reuse occupancy conversion for initial state, then attach exact measured events.
    temporary = settings.model_copy(update={"arrival_mode": "configured"})
    scene = _finish(
        "video",
        data["input_sha256"],
        "yolo",
        data["processing_seconds"],
        temporary,
        initial,
        unassigned,
        totals,
        occupancy,
        duration,
        unique,
        initial_time,
    )
    payload = scene.model_dump()
    payload.update(
        settings=settings.model_dump(),
        measured_flow=measurement.model_dump(),
        flow_validation=validation.model_dump() if validation else None,
    )
    payload["provenance"]["estimated_arrivals"] = (
        "Nincs Poisson-érkezés; az időbélyegzett entry eseményeket használjuk."
    )
    payload["provenance"]["measured_flow"] = (
        "Videóból követett vonalátlépések; a pontosságot a külön referenciariport írja le."
    )
    payload["assumptions"] = [
        a for a in scene.assumptions if not a.startswith(("Az érkezések nem", "A videó időablakai"))
    ] + [
        "A mért belépések a saját időbélyegükkel, a beállási idővel eltolva indulnak; "
        "nincs időnyújtás vagy extrapoláció.",
        "A már kezdetben jelen lévő ID-k, az ellenirány, a discharge "
        "és a bizonytalan ID-váltások nem adnak új érkezést.",
        "A mért szakasz helye és a további úthálózat geometriája "
        "továbbra is felhasználói megfeleltetés.",
    ]
    if settings.allow_unvalidated_flow:
        payload["assumptions"].append(
            "KÍSÉRLETI MÓD: a számlálási pontosság/beérkezési értelmezés még nem igazolt."
        )
    return _sampling_provenance(TrafficScene.model_validate(payload), data)


def _sampling_provenance(scene: TrafficScene, data: dict) -> TrafficScene:
    sampling = data.get("sampling", {})
    if sampling.get("resampled"):
        scene.provenance["temporal_sampling"] = (
            f"Kifejezetten választott {sampling['requested_fps']} FPS-es elemzési másolat; "
            "a videó ideje nem gyorsított."
        )
        scene.provenance["original_source_sha256"] = data["original_input_sha256"]
        scene.assumptions.append(
            "A ritkább időbeli mintavétel rövid észleléseket és lámpaváltásokat hagyhat ki; "
            "a tracking és az áthaladási mérés eltérhet a teljes képkockás feldolgozástól."
        )
    return scene
