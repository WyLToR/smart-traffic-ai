from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, model_validator

from smarttraffic_ai.config import Direction, Model
from smarttraffic_ai.detection import MOTOR_VEHICLES, Category, DetectionConfig, Region
from smarttraffic_ai.simulation import output_directory, save_csv, save_json

Coordinate = Annotated[float, Field(ge=0, le=1)]
Point = tuple[Coordinate, Coordinate]
SIDES = ("N", "E", "S", "W")


def fingerprint(model):
    return hashlib.sha256(
        json.dumps(model.model_dump(mode="json"), sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


class CountingLine(Model):
    id: str = Field(pattern=r"^[a-zA-Z0-9_-]+$")
    zone_id: str
    approach: Direction
    start: Point
    end: Point
    inbound: Literal["negative_to_positive", "positive_to_negative"] = "negative_to_positive"
    role: Literal["entry", "discharge"] = "entry"

    @model_validator(mode="after")
    def validate_line(self):
        if math.dist(self.start, self.end) < 0.01:
            raise ValueError("A számlálóvonal legyen legalább 0,01 normalizált egység hosszú.")
        return self

    def distance(self, point):
        dx, dy = self.end[0] - self.start[0], self.end[1] - self.start[1]
        return (dx * (point[1] - self.start[1]) - dy * (point[0] - self.start[0])) / math.hypot(
            dx, dy
        )


class CameraProfile(Model):
    camera_id: str = Field(pattern=r"^[a-zA-Z0-9_-]+$")
    fixed_view_confirmed: bool = False
    reference_size: tuple[Annotated[int, Field(gt=0)], Annotated[int, Field(gt=0)]]
    zones: list[Region] = Field(min_length=1)
    lines: list[CountingLine] = Field(min_length=1)
    window_seconds: Literal[10, 30, 60] = 30
    hysteresis: float = Field(default=0.005, gt=0, le=0.1)
    confirmations: int = Field(default=2, ge=2, le=10)
    max_gap_seconds: float = Field(default=1, gt=0, le=5)
    max_jump: float = Field(default=0.25, gt=0, le=1)
    max_crossing_interval: float = Field(default=0.25, gt=0, le=5)
    id_switch_distance: float = Field(default=0.04, gt=0, le=0.2)
    notes: str = ""

    @model_validator(mode="after")
    def validate_profile(self):
        DetectionConfig(regions=self.zones)
        zones = {zone.id: zone for zone in self.zones}
        if len({line.id for line in self.lines}) != len(self.lines):
            raise ValueError("A számlálóvonalak azonosítója legyen egyedi.")
        for line in self.lines:
            zone = zones.get(line.zone_id)
            if zone is None or zone.direction != line.approach:
                raise ValueError("A vonal meglévő, azonos SUMO-ághoz rendelt zónára hivatkozzon.")
            x1, y1, x2, y2 = zone.bounds
            if not all(x1 <= p[0] <= x2 and y1 <= p[1] <= y2 for p in (line.start, line.end)):
                raise ValueError("A vonal végpontjai legyenek a hozzárendelt zónában.")
        return self


class FlowObject(Model):
    track_id: int = Field(gt=0)
    category: Category
    bbox: tuple[Coordinate, Coordinate, Coordinate, Coordinate]

    @model_validator(mode="after")
    def validate_bbox(self):
        if self.bbox[0] >= self.bbox[2] or self.bbox[1] >= self.bbox[3]:
            raise ValueError("Érvénytelen követési téglalap.")
        return self

    @property
    def point(self):
        return ((self.bbox[0] + self.bbox[2]) / 2, self.bbox[3])


class FlowFrame(Model):
    seconds: float = Field(ge=0)
    duration: float = Field(gt=0)
    frame_index: int = Field(ge=0)
    objects: list[FlowObject]


class CrossingEvent(Model):
    camera_id: str
    track_id: int = Field(gt=0)
    vehicle_type: Category
    line_id: str
    approach: Direction
    direction: Literal["inbound", "outbound"]
    line_role: Literal["entry", "discharge"]
    timestamp_seconds: float = Field(ge=0)
    frame_index: int = Field(ge=0)
    initial_present: bool = False
    related_track_ids: list[int] = Field(default_factory=list)
    quality_flags: list[str] = Field(default_factory=list)


class InitialTrack(Model):
    track_id: int = Field(gt=0)
    approach: Direction
    vehicle_type: Category


class FlowWindow(Model):
    begin: float = Field(ge=0)
    end: float = Field(gt=0)
    inbound_counts: dict[Direction, int]
    outbound_counts: dict[Direction, int]
    by_line: dict[str, int]
    vehicles_per_minute: dict[Direction, float]


class FlowMeasurement(Model):
    camera: CameraProfile
    profile_sha256: str
    source_sha256: str
    analysis_sha256: str
    observations_sha256: str
    duration_seconds: float = Field(gt=0)
    frames: int = Field(gt=0)
    initial_tracks: list[InitialTrack]
    events: list[CrossingEvent]
    windows: list[FlowWindow]
    diagnostics: dict[str, int]
    notes: list[str]

    @model_validator(mode="after")
    def validate_measurement(self):
        if self.profile_sha256 != fingerprint(self.camera):
            raise ValueError("A mérés kamerakonfigurációja megváltozott.")
        if any(
            e.camera_id != self.camera.camera_id or e.timestamp_seconds >= self.duration_seconds
            for e in self.events
        ):
            raise ValueError("Az esemény kamerája vagy időbélyege eltér a méréstől.")
        lines = {line.id: line for line in self.camera.lines}
        if any(
            e.line_id not in lines
            or e.approach != lines[e.line_id].approach
            or e.line_role != lines[e.line_id].role
            for e in self.events
        ):
            raise ValueError(
                "Az esemény vonala, szerepe vagy SUMO-ága eltér a kamerakonfigurációtól."
            )
        cursor = 0.0
        for window in self.windows:
            if not math.isclose(window.begin, cursor, abs_tol=1e-6) or window.end <= window.begin:
                raise ValueError("A mérési időablakok hézag és átfedés nélkül fedjék a videót.")
            cursor = window.end
        if not math.isclose(cursor, self.duration_seconds, abs_tol=1e-6):
            raise ValueError("Az időablakok nem fedik le a teljes megfigyelési időt.")
        if sum(sum(w.inbound_counts.values()) for w in self.windows) != sum(
            e.direction == "inbound" for e in self.events
        ):
            raise ValueError("Az események és az időablakos számlálás eltérnek.")
        return self


def select_arrivals(measurement: FlowMeasurement):
    """Return each eligible new entry once, preserving measurement-time order."""
    initial = {track.track_id for track in measurement.initial_tracks}
    seen, selected, excluded = set(), [], Counter()
    for event in sorted(
        measurement.events, key=lambda e: (e.timestamp_seconds, e.line_id, e.track_id)
    ):
        if event.direction != "inbound":
            excluded["outbound"] += 1
        elif event.line_role != "entry":
            excluded["discharge"] += 1
        elif event.vehicle_type not in MOTOR_VEHICLES:
            excluded["non_motor_vehicle"] += 1
        elif event.initial_present or initial & {event.track_id, *event.related_track_ids}:
            excluded["already_initial"] += 1
        elif event.quality_flags:
            excluded["uncertain_id"] += 1
        elif seen & {event.track_id, *event.related_track_ids}:
            excluded["duplicate_entry"] += 1
        else:
            selected.append(event)
            seen.update({event.track_id, *event.related_track_ids})
    return selected, dict(excluded)


@dataclass
class _LineState:
    side: int
    pre_count: int
    anchor: tuple
    last: tuple
    pending: tuple | None = None
    post_count: int = 0
    crossing: tuple | None = None


class TrafficFlowCounter:
    """Count finite, directed crossings of existing tracking trajectories."""

    def __init__(self, camera: CameraProfile):
        self.camera = camera
        self.states = {}
        self.counted = set()
        self.events = []
        self.diagnostics = Counter()
        self.initial_tracks = []
        self.history = {}
        self.related = {}
        self.last_time = -1
        self.last_frame = -1

    def update(self, frame: FlowFrame):
        if frame.seconds <= self.last_time or frame.frame_index <= self.last_frame:
            raise ValueError("A mérési időbélyegek és képkockaszámok szigorúan növekedjenek.")
        current = {obj.track_id for obj in frame.objects}
        if len(current) != len(frame.objects):
            raise ValueError("Egy képkockán belül egy tracking-ID csak egyszer szerepelhet.")
        if self.last_frame == -1:
            for obj in frame.objects:
                zone = next(
                    (
                        z
                        for z in self.camera.zones
                        if z.bounds[0] <= obj.point[0] <= z.bounds[2]
                        and z.bounds[1] <= obj.point[1] <= z.bounds[3]
                    ),
                    None,
                )
                if zone and obj.category in MOTOR_VEHICLES:
                    self.initial_tracks.append(
                        InitialTrack(
                            track_id=obj.track_id,
                            approach=zone.direction,
                            vehicle_type=obj.category,
                        )
                    )
        for obj in frame.objects:
            if obj.category not in MOTOR_VEHICLES:
                continue
            point = obj.point
            previous = self.history.get(obj.track_id)
            if previous is None:
                candidates = [
                    track_id
                    for track_id, (seconds, old_point, category) in self.history.items()
                    if track_id not in current
                    and category == obj.category
                    and 0 < frame.seconds - seconds <= self.camera.max_gap_seconds
                    and math.dist(point, old_point) <= self.camera.id_switch_distance
                ]
                if candidates:
                    self.related[obj.track_id] = sorted(candidates)
                    self.diagnostics["possible_id_switches"] += 1
            for line in self.camera.lines:
                self._observe(line, obj, frame)
            self.history[obj.track_id] = (frame.seconds, point, obj.category)
        # Keep association evidence for the short gap only; completed-event keys remain.
        self.history = {
            k: v
            for k, v in self.history.items()
            if frame.seconds - v[0] <= self.camera.max_gap_seconds
        }
        self.last_time, self.last_frame = frame.seconds, frame.frame_index

    def _observe(self, line, obj, frame):
        point = obj.point
        distance = line.distance(point)
        side = (
            1
            if distance > self.camera.hysteresis
            else -1
            if distance < -self.camera.hysteresis
            else 0
        )
        key = (line.id, obj.track_id)
        now = (frame.seconds, frame.frame_index, point)
        state = self.states.get(key)
        if state and (
            frame.seconds - state.last[0] > self.camera.max_gap_seconds
            or math.dist(point, state.last[2]) > self.camera.max_jump
        ):
            self.diagnostics["trajectory_gaps_or_jumps"] += 1
            state = None
            self.states.pop(key, None)
        if state is None:
            if side:
                self.states[key] = _LineState(side, 1, now, now)
            return
        raw_before = state.last
        state.last = now
        raw_distance = line.distance(raw_before[2])
        if raw_distance != distance and raw_distance * distance <= 0:
            state.crossing = (raw_before, now)
        if side == 0:
            return
        if side == state.side:
            state.pre_count += 1
            state.anchor = now
            state.pending, state.post_count = None, 0
            state.crossing = None
            return
        if state.pending is None:
            state.pending = now
        state.post_count += 1
        if (
            state.pre_count < self.camera.confirmations
            or state.post_count < self.camera.confirmations
        ):
            if state.post_count >= self.camera.confirmations:
                self.states[key] = _LineState(side, state.post_count, now, now)
            return
        before, after = state.crossing or (state.anchor, state.pending)
        d0, d1 = line.distance(before[2]), line.distance(after[2])
        fraction = d0 / (d0 - d1)
        crossing = tuple(before[2][i] + fraction * (after[2][i] - before[2][i]) for i in (0, 1))
        dx, dy = line.end[0] - line.start[0], line.end[1] - line.start[1]
        projection = ((crossing[0] - line.start[0]) * dx + (crossing[1] - line.start[1]) * dy) / (
            dx * dx + dy * dy
        )
        inbound = (state.side < side) == (line.inbound == "negative_to_positive")
        direction = "inbound" if inbound else "outbound"
        event_key = (*key, direction)
        if 0 <= projection <= 1 and event_key not in self.counted:
            related = self.related.get(obj.track_id, [])
            initial_ids = {item.track_id for item in self.initial_tracks}
            flags = ["possible_id_switch"] if related else []
            if after[0] - before[0] > self.camera.max_crossing_interval:
                flags.append("crossing_across_gap")
                self.diagnostics["crossings_across_gap"] += 1
            self.events.append(
                CrossingEvent(
                    camera_id=self.camera.camera_id,
                    track_id=obj.track_id,
                    vehicle_type=obj.category,
                    line_id=line.id,
                    approach=line.approach,
                    direction=direction,
                    line_role=line.role,
                    timestamp_seconds=before[0] + fraction * (after[0] - before[0]),
                    frame_index=after[1],
                    initial_present=bool(initial_ids & {obj.track_id, *related}),
                    related_track_ids=related,
                    quality_flags=flags,
                )
            )
            self.counted.add(event_key)
        elif not 0 <= projection <= 1:
            self.diagnostics["crossings_outside_segment"] += 1
        self.states[key] = _LineState(side, state.post_count, now, now)


def aggregate_events(events, duration, window_seconds, line_ids):
    windows = []
    for index in range(math.ceil(duration / window_seconds)):
        begin, end = index * window_seconds, min(duration, (index + 1) * window_seconds)
        selected = [e for e in events if begin <= e.timestamp_seconds < end]
        inbound = {
            side: sum(e.direction == "inbound" and e.approach == side for e in selected)
            for side in SIDES
        }
        windows.append(
            FlowWindow(
                begin=begin,
                end=end,
                inbound_counts=inbound,
                outbound_counts={
                    side: sum(e.direction == "outbound" and e.approach == side for e in selected)
                    for side in SIDES
                },
                by_line={
                    line: sum(e.direction == "inbound" and e.line_id == line for e in selected)
                    for line in line_ids
                },
                vehicles_per_minute={
                    side: count * 60 / (end - begin) for side, count in inbound.items()
                },
            )
        )
    return windows


def measure_flow(root: Path, analysis: Path, camera: CameraProfile) -> Path:
    if not camera.fixed_view_confirmed:
        raise ValueError("A kameranézet rögzítettségét előbb ellenőrizd a videón.")
    data = json.loads(analysis.read_text(encoding="utf-8"))
    width, height = int(data["width"]), int(data["height"])
    if not math.isclose(
        width / height, camera.reference_size[0] / camera.reference_size[1], rel_tol=0.001
    ):
        raise ValueError("A kamera és a videó képaránya eltér; ellenőrizd újra a vonalakat.")
    duration = float(data["duration_seconds"])
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError("A videó időtartama legyen pozitív.")
    path = analysis.parent / "observations.jsonl"
    if not path.is_file():
        raise ValueError("Hiányzik a tracking-pozícióexport. Futtasd újra a videóelemzést.")
    confirmed = {int(track["track_id"]): track["category"] for track in data["tracks"]}
    counter = TrafficFlowCounter(camera)
    digest = hashlib.sha256()
    frames = 0
    with path.open("rb") as stream:
        for index, line in enumerate(stream):
            digest.update(line)
            row = json.loads(line)
            row["frame_index"] = row.get("frame_index", index)
            row["objects"] = [
                {**obj, "category": confirmed[int(obj["track_id"])]}
                for obj in row["objects"]
                if int(obj["track_id"]) in confirmed
            ]
            frame = FlowFrame.model_validate(row)
            if frame.frame_index != index:
                raise ValueError("A tracking-export képkockaszámozása nem folytonos.")
            if frame.seconds + frame.duration > duration + 1e-5:
                raise ValueError("A követési időbélyeg túlnyúlik a videón.")
            counter.update(frame)
            frames += 1
    if frames != int(data["frames"]):
        raise ValueError("A tracking-export nem fedi le a teljes videót.")
    events = sorted(counter.events, key=lambda e: (e.timestamp_seconds, e.line_id, e.track_id))
    result = FlowMeasurement(
        camera=camera,
        profile_sha256=fingerprint(camera),
        source_sha256=data["input_sha256"],
        analysis_sha256=hashlib.sha256(analysis.read_bytes()).hexdigest(),
        observations_sha256=digest.hexdigest(),
        duration_seconds=duration,
        frames=frames,
        initial_tracks=counter.initial_tracks,
        events=events,
        windows=aggregate_events(
            events, duration, camera.window_seconds, [line.id for line in camera.lines]
        ),
        diagnostics=dict(counter.diagnostics),
        notes=[
            "Az áthaladás a téglalap alsó középpontjának követett vonalkeresztezése.",
            "A percérték az adott rövid időablakra normalizált ráta, nem órás előrejelzés.",
            "Az entry vonal beérkezést, a discharge vonal helyi/stopvonali áthaladást jelöl.",
            "A lehetséges ID-váltás jelölt bizonytalanság; nem bizonyított újraazonosítás.",
        ],
    )
    directory = output_directory(root, "flow")
    save_json(directory / "measurement.json", result.model_dump(mode="json"))
    save_json(directory / "camera.json", camera.model_dump(mode="json"))
    save_csv(directory / "events.csv", [e.model_dump() for e in events])
    if not events:
        (directory / "events.csv").write_text(
            ",".join(CrossingEvent.model_fields) + "\n", encoding="utf-8-sig"
        )
    save_csv(
        directory / "windows.csv",
        [
            {
                "begin": w.begin,
                "end": w.end,
                **{f"count_{d}": w.inbound_counts[d] for d in SIDES},
                **{f"vehicles_per_minute_{d}": w.vehicles_per_minute[d] for d in SIDES},
            }
            for w in result.windows
        ],
    )
    return directory / "measurement.json"
