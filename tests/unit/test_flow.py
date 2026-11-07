import pytest
from pydantic import ValidationError

from smarttraffic_ai.detection import Region
from smarttraffic_ai.flow import (
    CameraProfile,
    CountingLine,
    FlowFrame,
    FlowObject,
    TrafficFlowCounter,
    aggregate_events,
)


def camera():
    return CameraProfile(
        camera_id="unit-camera",
        fixed_view_confirmed=True,
        reference_size=(100, 100),
        zones=[Region(id="north", direction="N", bounds=(0, 0, 1, 1))],
        lines=[
            CountingLine(
                id="north-entry",
                zone_id="north",
                approach="N",
                start=(0.5, 0.2),
                end=(0.5, 0.8),
                inbound="positive_to_negative",
            )
        ],
    )


def frame(index, x, track_id=1, y=0.5, seconds=None):
    return FlowFrame(
        frame_index=index,
        seconds=index * 0.1 if seconds is None else seconds,
        duration=0.1,
        objects=[]
        if x is None
        else [
            FlowObject(track_id=track_id, category="car", bbox=(x - 0.01, y - 0.03, x + 0.01, y))
        ],
    )


def test_crossing_is_once_per_id_line_direction_with_interpolated_time():
    counter = TrafficFlowCounter(camera())
    for i, x in enumerate([0.4, 0.45, 0.55, 0.6, 0.55, 0.45, 0.4, 0.45, 0.55, 0.6]):
        counter.update(frame(i, x))
    inbound = [e for e in counter.events if e.direction == "inbound"]
    assert len(inbound) == 1
    assert inbound[0].timestamp_seconds == pytest.approx(0.15)
    assert inbound[0].frame_index == 2
    assert inbound[0].initial_present
    assert sum(e.direction == "outbound" for e in counter.events) == 1
    windows = aggregate_events(counter.events, 12.5, 10, ["north-entry"])
    assert sum(w.inbound_counts["N"] for w in windows) == 1
    assert windows[-1].end == 12.5


@pytest.mark.parametrize(
    "xs,y",
    [
        ([0.499, 0.501, 0.498, 0.502, 0.501], 0.5),
        ([0.4, 0.45, 0.55, 0.6], 0.95),
        ([0.1, 0.2, 0.8, 0.9], 0.5),
        ([0.4, 0.6, 0.4, 0.6], 0.5),
    ],
)
def test_jitter_extension_teleport_and_unconfirmed_movement_do_not_count(xs, y):
    counter = TrafficFlowCounter(camera())
    for i, x in enumerate(xs):
        counter.update(frame(i, x, y=y))
    assert not counter.events


def test_wrong_direction_is_recorded_as_outbound_not_inbound():
    counter = TrafficFlowCounter(camera())
    for i, x in enumerate([0.6, 0.55, 0.45, 0.4]):
        counter.update(frame(i, x))
    assert [e.direction for e in counter.events] == ["outbound"]


def test_long_gap_cannot_fabricate_a_crossing_and_new_video_has_clean_state():
    counter = TrafficFlowCounter(camera())
    counter.update(frame(0, 0.4))
    counter.update(frame(1, 0.45))
    counter.update(frame(2, 0.55, seconds=3))
    counter.update(frame(3, 0.6, seconds=3.1))
    assert not counter.events
    assert counter.diagnostics["trajectory_gaps_or_jumps"] == 1
    assert not TrafficFlowCounter(camera()).events


def test_possible_id_switch_is_flagged_instead_of_silently_becoming_another_arrival():
    counter = TrafficFlowCounter(camera())
    for i, (x, track) in enumerate(
        [(0.42, 1), (0.46, 1), (0.47, 2), (0.48, 2), (0.55, 2), (0.6, 2)]
    ):
        counter.update(frame(i, x, track_id=track))
    event = counter.events[0]
    assert event.quality_flags == ["possible_id_switch"]
    assert event.related_track_ids == [1]
    assert event.initial_present


def test_invalid_lines_profiles_and_repeated_frames_are_rejected():
    with pytest.raises(ValidationError):
        CountingLine(id="bad", zone_id="north", approach="N", start=(0.5, 0.5), end=(0.5, 0.5))
    payload = camera().model_dump()
    payload["lines"][0]["zone_id"] = "missing"
    with pytest.raises(ValidationError):
        CameraProfile.model_validate(payload)
    counter = TrafficFlowCounter(camera())
    counter.update(frame(0, 0.4))
    with pytest.raises(ValueError, match="időbélyeg"):
        counter.update(frame(0, 0.45))
