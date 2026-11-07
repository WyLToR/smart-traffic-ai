from __future__ import annotations

from collections import Counter, defaultdict
from typing import Literal

from pydantic import Field, model_validator

from smarttraffic_ai.config import Direction, Model
from smarttraffic_ai.flow import FlowMeasurement, fingerprint


class ReferenceEvent(Model):
    timestamp_seconds: float = Field(ge=0)
    line_id: str
    vehicle_type: Literal["car", "bus", "truck", "motorcycle"]
    direction: Literal["inbound", "outbound"] = "inbound"


class ReferenceSegment(Model):
    begin: float = Field(ge=0)
    end: float = Field(gt=0)
    events: list[ReferenceEvent]

    @model_validator(mode="after")
    def validate_segment(self):
        if self.end <= self.begin or any(
            not self.begin <= e.timestamp_seconds < self.end for e in self.events
        ):
            raise ValueError("A referenciaesemények a saját, pozitív időablakukba essenek.")
        return self


class ManualReference(Model):
    camera_id: str
    source_sha256: str
    profile_sha256: str
    annotator: str = Field(min_length=1)
    human_reviewed: bool = False
    directions: list[Literal["inbound", "outbound"]] = Field(
        default_factory=lambda: ["inbound"], min_length=1
    )
    segments: list[ReferenceSegment] = Field(min_length=1)
    notes: str = ""

    @model_validator(mode="after")
    def validate_segments(self):
        ordered = sorted(self.segments, key=lambda segment: segment.begin)
        if any(a.end > b.begin for a, b in zip(ordered, ordered[1:])):
            raise ValueError("A referencia-időablakok nem fedhetik egymást.")
        keys = [
            (e.line_id, e.direction, e.vehicle_type, e.timestamp_seconds)
            for s in self.segments
            for e in s.events
        ]
        if len(set(keys)) != len(keys):
            raise ValueError("A kézi referencia ismételt eseményt tartalmaz.")
        return self


class ValidationReport(Model):
    measurement_sha256: str
    reference_sha256: str
    human_reviewed: bool
    segments: int
    reference_events: int
    predicted_events: int
    true_positives: int
    false_positives: int
    false_negatives: int
    precision: float | None
    recall: float | None
    f1: float | None
    by_approach: dict[Direction, dict]
    time_tolerance_seconds: float
    accuracy_targets_met: bool
    sufficient_sample: bool
    approved_for_arrivals: bool
    notes: list[str]


def _match(reference, predicted, tolerance):
    # Maximum one-to-one matching: duplicates remain false positives. Matching is
    # grouped by line, category and direction by the caller, independently of IDs.
    candidates = [
        [
            j
            for j, p in sorted(
                enumerate(predicted),
                key=lambda pair: abs(pair[1].timestamp_seconds - r.timestamp_seconds),
            )
            if abs(p.timestamp_seconds - r.timestamp_seconds) <= tolerance
        ]
        for r in reference
    ]
    owners = {}

    def assign(i, seen):
        for j in candidates[i]:
            if j in seen:
                continue
            seen.add(j)
            if j not in owners or assign(owners[j], seen):
                owners[j] = i
                return True
        return False

    for i in range(len(reference)):
        assign(i, set())
    return len(owners)


def evaluate_flow(
    measurement: FlowMeasurement, reference: ManualReference, time_tolerance_seconds: float = 1.0
) -> ValidationReport:
    if not 0 < time_tolerance_seconds <= 5:
        raise ValueError("Az időtolerancia 0 és 5 másodperc közé essen.")
    if (
        reference.camera_id != measurement.camera.camera_id
        or reference.source_sha256 != measurement.source_sha256
        or reference.profile_sha256 != measurement.profile_sha256
    ):
        raise ValueError("A referencia másik kamerához, videóhoz vagy vonalbeállításhoz tartozik.")
    lines = {line.id: line for line in measurement.camera.lines}
    if any(segment.end > measurement.duration_seconds + 1e-6 for segment in reference.segments):
        raise ValueError("A referencia túlnyúlik a videó időtartamán.")
    refs, predictions = defaultdict(list), defaultdict(list)
    for index, segment in enumerate(reference.segments):
        for event in segment.events:
            if event.line_id not in lines:
                raise ValueError("Ismeretlen referenciavonal.")
            if event.direction not in reference.directions:
                continue
            refs[(index, event.line_id, event.vehicle_type, event.direction)].append(event)
        for event in measurement.events:
            if (
                segment.begin <= event.timestamp_seconds < segment.end
                and event.direction in reference.directions
            ):
                predictions[(index, event.line_id, event.vehicle_type, event.direction)].append(
                    event
                )
    totals = Counter()
    by_approach = defaultdict(Counter)
    for key in refs.keys() | predictions.keys():
        expected, actual = refs[key], predictions[key]
        tp = _match(expected, actual, time_tolerance_seconds)
        values = {
            "reference": len(expected),
            "predicted": len(actual),
            "tp": tp,
            "fp": len(actual) - tp,
            "fn": len(expected) - tp,
        }
        totals.update(values)
        by_approach[lines[key[1]].approach].update(values)
    tp, fp, fn = totals["tp"], totals["fp"], totals["fn"]
    precision = tp / (tp + fp) if tp + fp else None
    recall = tp / (tp + fn) if tp + fn else None
    f1 = 2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else None
    details = {}
    for approach, counts in by_approach.items():
        error = abs(counts["predicted"] - counts["reference"])
        details[approach] = {
            **counts,
            "absolute_count_error": error,
            "relative_count_error": error / counts["reference"] if counts["reference"] else None,
        }
    sufficient = (
        len(reference.segments) >= 2
        and totals["reference"] >= 20
        and (len(details) >= 2 and all(c["reference"] >= 10 for c in details.values()))
    )
    accuracy = (
        f1 is not None
        and f1 >= 0.9
        and all(
            c["absolute_count_error"] == 0
            if c["reference"] < 10
            else c["relative_count_error"] <= 0.1
            for c in details.values()
        )
    )
    entry_approaches = {line.approach for line in lines.values() if line.role == "entry"}
    approved = bool(
        reference.human_reviewed
        and sufficient
        and accuracy
        and len(entry_approaches) >= 2
        and set(details) == entry_approaches
        and not any(
            e.quality_flags
            for e in measurement.events
            if e.direction == "inbound" and e.line_role == "entry" and not e.initial_present
        )
        and set(reference.directions) == {"inbound"}
    )
    return ValidationReport(
        measurement_sha256=fingerprint(measurement),
        reference_sha256=fingerprint(reference),
        human_reviewed=reference.human_reviewed,
        segments=len(reference.segments),
        reference_events=totals["reference"],
        predicted_events=totals["predicted"],
        true_positives=tp,
        false_positives=fp,
        false_negatives=fn,
        precision=precision,
        recall=recall,
        f1=f1,
        by_approach=details,
        time_tolerance_seconds=time_tolerance_seconds,
        accuracy_targets_met=bool(accuracy),
        sufficient_sample=bool(sufficient),
        approved_for_arrivals=approved,
        notes=[
            "Eseményszintű, egy-egy értelmű egyeztetés vonal, kategória, irány és idő alapján; "
            "az ID nem referencia.",
            "Cél: F1 ≥ 0,90; legalább 10 referenciaesemény/irány és 20 összesen, "
            "két külön időablakban.",
            "Kis mintán abszolút hiba is szerepel. Üres referencia és üres predikció "
            "nem igazol 100% pontosságot.",
            "Nem annotált időszak nem része a pontosságmérésnek. "
            "A stopvonali/helyi áthaladás nem beérkezésmérés.",
        ],
    )
