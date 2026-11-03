import pytest
from pydantic import ValidationError

from smarttraffic_ai.traffic_lights import LightAnalyzer, LightRegion, read_color
from smarttraffic_ai.video import TrackCounter, TrackedObject

cv2 = pytest.importorskip("cv2")
np = pytest.importorskip("numpy")


def signal(*colors):
    frame = np.zeros((90, 40, 3), dtype=np.uint8)
    for name in colors:
        position, color = {
            "red": (15, (0, 0, 255)),
            "yellow": (45, (0, 255, 255)),
            "green": (75, (0, 255, 0)),
        }[name]
        cv2.circle(frame, (20, position), 7, color, -1)
    return frame


@pytest.mark.parametrize(
    "colors,expected",
    [
        (("red",), "red"),
        (("green",), "green"),
        (("yellow",), "yellow"),
        (("red", "yellow"), "red-yellow"),
        (("red", "green"), "unknown"),
        ((), "unknown"),
    ],
)
def test_signal_colors_and_ambiguity(colors, expected):
    assert read_color(signal(*colors), (0, 0, 40, 90))[0] == expected


def test_color_is_only_read_inside_the_signal_region():
    frame = signal("red")
    assert read_color(frame, (0, 40, 40, 90))[0] == "unknown"
    assert read_color(frame, (0, 0, 4, 8))[0] == "unknown"


def test_two_state_pedestrian_profile_does_not_interpret_yellow_background_as_signal():
    assert read_color(signal("yellow"), (0, 0, 40, 90), "pedestrian")[0] == "unknown"
    assert read_color(signal("yellow", "green"), (0, 0, 40, 90), "pedestrian")[0] == "green"


def test_color_change_requires_confirmation_and_does_not_reuse_old_green():
    analyzer = LightAnalyzer([LightRegion(id="signal", kind="vehicle", bounds=(0, 0, 1, 1))])
    for index in range(3):
        readings = analyzer.update(signal("green"), [], index * 0.1, 0.1)
    assert readings[0]["state"] == "green"
    assert readings[0]["kind"] == "vehicle"
    assert analyzer.update(signal("red"), [], 0.3, 0.1)[0]["state"] == "unknown"
    analyzer.update(signal("red"), [], 0.4, 0.1)
    assert analyzer.update(signal("red"), [], 0.5, 0.1)[0]["state"] == "red"
    assert sum(analyzer.summary()[0]["state_seconds"].values()) == pytest.approx(0.6)


def test_automatic_signal_has_unknown_type_and_is_not_a_road_user():
    obj = TrackedObject(5, "traffic light", 0.9, (0, 0, 40, 90))
    analyzer = LightAnalyzer([])
    counter = TrackCounter(min_observations=1, min_visible_seconds=0)
    for index in range(3):
        rows = analyzer.update(signal("red"), [obj], index * 0.1, 0.1)
        counter.update(index * 0.1, 0.1, [obj])
    assert rows[0]["state"] == "red"
    assert rows[0]["kind"] == "unknown"
    assert counter.summary()["total_unique"] == 0
    assert analyzer.update(signal(), [], 0.3, 0.1) == []
    assert analyzer.rows[-1]["state"] == "unknown"
    assert analyzer.rows[-1]["visible"] is False
    assert analyzer.update(signal("red"), [obj], 0.4, 0.1)[0]["state"] == "unknown"


def test_configured_roi_prevents_duplicate_automatic_signal():
    analyzer = LightAnalyzer([LightRegion(id="ped", kind="pedestrian", bounds=(0, 0, 1, 1))])
    obj = TrackedObject(8, "traffic light", 0.9, (0, 0, 40, 90))
    assert len(analyzer.update(signal("red"), [obj], 0, 0.1)) == 1
    with pytest.raises(ValidationError):
        LightRegion(id="bad", kind="vehicle", bounds=(0.5, 0, 0.1, 1))
