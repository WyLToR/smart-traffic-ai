import pytest
from pydantic import ValidationError

from smarttraffic_ai.detection import DetectionConfig
from smarttraffic_ai.video import TrackCounter, TrackedObject


def observed(track_id=1, category="car", confidence=0.9):
    return TrackedObject(track_id, category, confidence, (0, 0, 20, 20))


def test_confirmation_and_whitelist():
    counter = TrackCounter()
    for time in (0, 0.1, 0.2, 0.3):
        counter.update(time, 0.1, [observed(), observed(2, "handbag")])
    assert counter.summary()["total_unique"] == 0
    counter.update(0.4, 0.1, [observed(), observed(2, "handbag")])
    assert counter.summary()["total_unique"] == 1
    assert set(counter.tracks) == {1}
    with pytest.raises(ValidationError):
        DetectionConfig(classes=["car", "handbag"])


def test_gaps_are_not_visible_time_and_reappearance_is_not_counted_twice():
    counter = TrackCounter(min_observations=1, min_visible_seconds=0)
    counter.update(0, 0.1, [observed()])
    counter.update(0.1, 0.1, [])
    assert counter.summary()["current_total"] == 0
    assert counter.summary()["total_unique"] == 1
    counter.update(1.0, 0.1, [observed()])
    row = counter.rows()[0]
    assert row["visible_seconds"] == pytest.approx(0.2)
    assert row["span_seconds"] == pytest.approx(1.1)
    assert row["first_seen_seconds"] == 0
    assert row["last_seen_seconds"] == 1
    assert counter.summary()["total_unique"] == 1


def test_duplicate_id_and_category_change_still_count_as_one():
    counter = TrackCounter(min_observations=1, min_visible_seconds=0)
    counter.update(0, 0.1, [observed(), observed(confidence=0.5)])
    counter.update(0.1, 0.1, [observed(category="truck", confidence=0.6)])
    assert counter.rows()[0]["observations"] == 2
    assert counter.rows()[0]["visible_seconds"] == pytest.approx(0.2)
    assert counter.summary()["total_unique"] == 1
    assert counter.summary()["by_category"]["car"] == 1
    assert counter.summary()["by_category"]["truck"] == 0


def test_counter_state_does_not_leak_between_videos():
    first = TrackCounter(min_observations=1, min_visible_seconds=0)
    first.update(0, 0.1, [observed()])
    assert TrackCounter().summary()["total_unique"] == 0


@pytest.mark.parametrize(
    "seconds,duration", [(-0.1, 0.1), (0, 0), (0, -1), (float("nan"), 0.1), (0, float("inf"))]
)
def test_invalid_video_times(seconds, duration):
    with pytest.raises(ValueError):
        TrackCounter().update(seconds, duration, [])


def test_repeated_timestamp_is_rejected():
    counter = TrackCounter()
    counter.update(0, 0.1, [])
    with pytest.raises(ValueError):
        counter.update(0, 0.1, [])
