from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pandas as pd
import streamlit as st

from smarttraffic_ai.config import AppConfig, load_yaml
from smarttraffic_ai.detection import CATEGORY_LABELS, MOTOR_VEHICLES, Region
from smarttraffic_ai.flow import (
    CameraProfile,
    CountingLine,
    FlowMeasurement,
    fingerprint,
    measure_flow,
    select_arrivals,
)
from smarttraffic_ai.flow_validation import ManualReference, ValidationReport, evaluate_flow
from smarttraffic_ai.simulation import save_json

ROLES = {"entry": "Új belépés", "discharge": "Helyi/stopvonali áthaladás"}


def _camera_editor(data, preset):
    camera_id = st.text_input(
        "Kamera azonosítója", value=preset.camera_id if preset else "camera-01"
    )
    confirmed = st.checkbox("Ellenőriztem: a videó kameranézete végig rögzített.", value=False)
    zone_columns = ["ID", "Ág", "Bal", "Fent", "Jobb", "Lent"]
    zones = st.data_editor(
        pd.DataFrame(
            [
                dict(zip(zone_columns, [r.id, r.direction, *r.bounds], strict=True))
                for r in preset.zones
            ]
            if preset
            else [],
            columns=zone_columns,
        ),
        key=f"flow-zones-{camera_id}",
        num_rows="dynamic",
        hide_index=True,
        column_config={
            "Ág": st.column_config.SelectboxColumn(options=["N", "E", "S", "W"], required=True),
            **{
                c: st.column_config.NumberColumn(min_value=0.0, max_value=1.0, required=True)
                for c in zone_columns[2:]
            },
        },
    )
    st.caption(
        "Normalizált koordináták: 0–1. A zónák kézi megfeleltetések a SUMO ágaihoz, "
        "nem felismert égtájak."
    )
    columns = ["ID", "Zóna", "Ág", "X1", "Y1", "X2", "Y2", "Irány", "Mérés"]
    lines = st.data_editor(
        pd.DataFrame(
            [
                dict(
                    zip(
                        columns,
                        [
                            line.id,
                            line.zone_id,
                            line.approach,
                            *line.start,
                            *line.end,
                            line.inbound,
                            ROLES[line.role],
                        ],
                        strict=True,
                    )
                )
                for line in preset.lines
            ]
            if preset
            else [],
            columns=columns,
        ),
        key=f"flow-lines-{camera_id}",
        num_rows="dynamic",
        hide_index=True,
        column_config={
            "Ág": st.column_config.SelectboxColumn(options=["N", "E", "S", "W"], required=True),
            "Irány": st.column_config.SelectboxColumn(
                options=["negative_to_positive", "positive_to_negative"], required=True
            ),
            "Mérés": st.column_config.SelectboxColumn(options=list(ROLES.values()), required=True),
            **{
                c: st.column_config.NumberColumn(min_value=0.0, max_value=1.0, required=True)
                for c in ("X1", "Y1", "X2", "Y2")
            },
        },
    )
    window = st.selectbox(
        "Mérési időablak (s)",
        [10, 30, 60],
        index=[10, 30, 60].index(preset.window_seconds) if preset else 0,
    )
    payload = preset.model_dump() if preset else {}
    return CameraProfile.model_validate(
        {
            **payload,
            "camera_id": camera_id,
            "fixed_view_confirmed": confirmed,
            "reference_size": preset.reference_size if preset else [data["width"], data["height"]],
            "window_seconds": window,
            "zones": [
                Region(
                    id=str(row["ID"]),
                    direction=row["Ág"],
                    bounds=tuple(float(row[c]) for c in zone_columns[2:]),
                ).model_dump()
                for row in zones.to_dict("records")
                if pd.notna(row["ID"])
            ],
            "lines": [
                CountingLine(
                    id=str(row["ID"]),
                    zone_id=row["Zóna"],
                    approach=row["Ág"],
                    start=(row["X1"], row["Y1"]),
                    end=(row["X2"], row["Y2"]),
                    inbound=row["Irány"],
                    role={v: k for k, v in ROLES.items()}[row["Mérés"]],
                ).model_dump()
                for row in lines.to_dict("records")
                if pd.notna(row["ID"])
            ],
        }
    )


def _reference_editor(measurement, key):
    uploaded = st.file_uploader(
        "Kézzel ellenőrzött referencia (JSON)", type=["json"], key=f"flow-ref-{key}"
    )
    if uploaded:
        return ManualReference.model_validate_json(uploaded.getvalue())
    st.caption(
        "A referenciaeseményeket a videó megtekintésével add meg. "
        "A program számlálási eredménye nem referenciaadat."
    )
    annotator = st.text_input("Referencia készítője", key=f"flow-annotator-{key}")
    reviewed = st.checkbox(
        "A két szakaszt végignéztem, az eseményeket kézzel ellenőriztem.", key=f"flow-human-{key}"
    )
    both = st.checkbox(
        "Az ellenkező irányú áthaladásokat is annotáltam.", key=f"flow-ref-both-{key}"
    )
    first, second = st.columns(2)
    middle = measurement.duration_seconds / 2
    begin1 = first.number_input("Első szakasz kezdete (s)", 0.0, middle, 0.0)
    end1 = first.number_input("Első szakasz vége (s)", 0.001, measurement.duration_seconds, middle)
    begin2 = second.number_input(
        "Második szakasz kezdete (s)", 0.0, measurement.duration_seconds, middle
    )
    end2 = second.number_input(
        "Második szakasz vége (s)",
        0.001,
        measurement.duration_seconds,
        measurement.duration_seconds,
    )
    columns = ["Idő (s)", "Vonal", "Kategória", "Irány"]
    table = st.data_editor(
        pd.DataFrame(columns=columns),
        num_rows="dynamic",
        hide_index=True,
        key=f"flow-reference-events-{key}",
        column_config={
            "Idő (s)": st.column_config.NumberColumn(
                min_value=0.0, max_value=measurement.duration_seconds, required=True
            ),
            "Vonal": st.column_config.SelectboxColumn(
                options=[line.id for line in measurement.camera.lines], required=True
            ),
            "Kategória": st.column_config.SelectboxColumn(
                options=[CATEGORY_LABELS[c] for c in MOTOR_VEHICLES], required=True
            ),
            "Irány": st.column_config.SelectboxColumn(
                options=["inbound", "outbound"], required=True
            ),
        },
    )
    reverse = {value: key for key, value in CATEGORY_LABELS.items()}
    events = [
        {
            "timestamp_seconds": float(row["Idő (s)"]),
            "line_id": row["Vonal"],
            "vehicle_type": reverse[row["Kategória"]],
            "direction": row["Irány"],
        }
        for row in table.to_dict("records")
        if pd.notna(row["Idő (s)"])
    ]
    intervals = [(begin1, end1), (begin2, end2)]
    if any(
        not any(begin <= event["timestamp_seconds"] < end for begin, end in intervals)
        for event in events
    ):
        raise ValueError("A referenciaesemény a két kijelölt időszak valamelyikébe essen.")
    if not annotator:
        return None
    return ManualReference.model_validate(
        {
            "camera_id": measurement.camera.camera_id,
            "source_sha256": measurement.source_sha256,
            "profile_sha256": measurement.profile_sha256,
            "annotator": annotator,
            "human_reviewed": reviewed,
            "directions": ["inbound", "outbound"] if both else ["inbound"],
            "segments": [
                {
                    "begin": begin,
                    "end": end,
                    "events": [
                        event for event in events if begin <= event["timestamp_seconds"] < end
                    ],
                }
                for begin, end in intervals
            ],
        }
    )


def render_flow_tab(root: Path):
    st.write(
        "Rögzített videó forgalommérése a meglévő követési pozíciókból, új YOLO-futtatás nélkül."
    )
    cfg = load_yaml(root / "config/app.yaml", AppConfig)
    files = sorted(
        (root / cfg.output_dir).glob("video-*/analysis.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    files = [path for path in files if (path.parent / "observations.jsonl").is_file()]
    if not files:
        st.info("Előbb dolgozz fel egy MP4-videót a Videóelemzés lapon.")
        return
    analysis = st.selectbox(
        "Videófelismerés a forgalomméréshez",
        files,
        format_func=lambda p: p.parent.name,
        key="flow-analysis",
    )
    data = json.loads(analysis.read_text(encoding="utf-8"))
    raw = Path(data.get("input_path", ""))
    if not raw.is_file():
        raw = root / "outputs/video-validation/videos" / data.get("input_name", "")
    if raw.is_file() and hashlib.sha256(raw.read_bytes()).hexdigest() == data["input_sha256"]:
        with st.expander("Eredeti videó a kézi ellenőrzéshez (számlálási feliratok nélkül)"):
            st.video(str(raw))
    profiles = sorted((root / "config/cameras").glob("*.json"))
    chosen = st.selectbox(
        "Mentett kamerabeállítás",
        [None, *profiles],
        format_func=lambda p: p.stem if p else "Új kamera",
        key="flow-preset",
    )
    upload = st.file_uploader(
        "Kamerabeállítás betöltése (JSON)", type=["json"], key="flow-camera-upload"
    )
    try:
        preset = (
            CameraProfile.model_validate_json(upload.getvalue())
            if upload
            else (
                CameraProfile.model_validate_json(chosen.read_text(encoding="utf-8"))
                if chosen
                else None
            )
        )
        camera = _camera_editor(data, preset)
        if camera.notes:
            st.info(camera.notes)
        st.caption(
            "A nyíl mutatja a beszámított irányt. A helyi/stopvonali áthaladás nem új beérkezés. "
            "A vonalak módosításakor a mérést újra kell készíteni."
        )
        import cv2

        from smarttraffic_ai.flow_video import draw_flow_frame, render_flow_video

        capture = cv2.VideoCapture(str(analysis.parent / "annotated.mp4"))
        try:
            ok, frame = capture.read()
            if ok:
                st.image(draw_flow_frame(frame, camera), channels="BGR", width="stretch")
        finally:
            capture.release()
        st.download_button(
            "Kamerabeállítás mentése (JSON)",
            camera.model_dump_json(indent=2),
            f"{camera.camera_id}.json",
            key="flow-camera-save",
        )
        overlay = st.checkbox("Jelölt mérési videó mentése", value=True)
        if st.button("Forgalommérés indítása", disabled=not camera.fixed_view_confirmed):
            with st.spinner("Vonalátlépések feldolgozása…"):
                path = measure_flow(root, analysis, camera)
                if overlay:
                    render_flow_video(analysis, path)
            st.session_state["flow_measurement"] = str(path)
            st.session_state["flow_analysis"] = str(analysis)
            st.session_state.pop("flow_validation", None)
    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        ImportError,
        subprocess.SubprocessError,
    ) as exc:
        st.warning(f"A kamerabeállítás vagy mérés még nem használható: {exc}")
        return
    path = st.session_state.get("flow_measurement")
    if not path:
        return
    measurement = FlowMeasurement.model_validate_json(Path(path).read_text(encoding="utf-8"))
    if (
        measurement.profile_sha256 != fingerprint(camera)
        or measurement.analysis_sha256 != hashlib.sha256(analysis.read_bytes()).hexdigest()
    ):
        st.info("Másik videó vagy kamerabeállítás van kiválasztva. Indíts új mérést.")
        return
    directory = Path(path).parent
    if (directory / "flow-annotated.mp4").is_file():
        st.video(str(directory / "flow-annotated.mp4"))
    st.dataframe(
        [
            {
                "Kezdet (s)": w.begin,
                "Vég (s)": w.end,
                **{f"{d} áthaladás": w.inbound_counts[d] for d in ("N", "E", "S", "W")},
                **{
                    f"{d} normalizált jármű/perc": w.vehicles_per_minute[d]
                    for d in ("N", "E", "S", "W")
                },
            }
            for w in measurement.windows
        ],
        hide_index=True,
    )
    st.caption("A percérték az adott rövid időablakra normalizált mérés; nem órás előrejelzés.")
    st.dataframe(
        [
            {
                "Idő (s)": e.timestamp_seconds,
                "ID": e.track_id,
                "Vonal": e.line_id,
                "Ág": e.approach,
                "Kategória": CATEGORY_LABELS[e.vehicle_type],
                "Irány": e.direction,
                "Kezdetben jelen volt": e.initial_present,
                "Bizonytalanság": ", ".join(e.quality_flags),
            }
            for e in measurement.events
        ],
        hide_index=True,
    )
    arrivals, excluded = select_arrivals(measurement)
    st.write(
        f"Új, egyértelmű entry esemény: {len(arrivals)}. "
        f"Kezdetben jelen lévő ID: {len(measurement.initial_tracks)}."
    )
    st.caption(
        f"Kizárt új érkezések okai: {excluded}; követési diagnosztika: {measurement.diagnostics}"
    )
    with st.expander("Összevetés kézi referenciával"):
        try:
            reference = _reference_editor(measurement, fingerprint(measurement)[:12])
            if reference:
                st.download_button(
                    "Kézi referencia mentése (JSON)",
                    reference.model_dump_json(indent=2),
                    "reference.json",
                )
            if st.button("Referenciaértékelés", disabled=reference is None):
                report = evaluate_flow(measurement, reference)
                save_json(directory / "validation.json", report.model_dump(mode="json"))
                st.session_state["flow_validation"] = str(directory / "validation.json")
            if (directory / "validation.json").is_file():
                report = ValidationReport.model_validate_json(
                    (directory / "validation.json").read_text(encoding="utf-8")
                )
                if report.measurement_sha256 != fingerprint(measurement):
                    raise ValueError("Az értékelés másik méréshez tartozik.")
                metrics = st.columns(3)
                for column, name, value in zip(
                    metrics,
                    ["Precision", "Recall", "F1"],
                    [report.precision, report.recall, report.f1],
                    strict=True,
                ):
                    column.metric(name, "Nincs adat" if value is None else f"{value:.1%}")
                st.dataframe(
                    [
                        {
                            "Ág": direction,
                            "Referencia": row["reference"],
                            "Számlált": row["predicted"],
                            "Abszolút eltérés": row["absolute_count_error"],
                            "Relatív eltérés": row["relative_count_error"],
                        }
                        for direction, row in report.by_approach.items()
                    ],
                    hide_index=True,
                )
                if not report.human_reviewed:
                    st.warning(
                        "A referencia nincs ember által ellenőrizve; ez csak előzetes értékelés."
                    )
                if not report.approved_for_arrivals:
                    st.warning(
                        "A mérés még nem igazolt, kétirányú beérkezésmérés. "
                        "Az F1, a mintaméret és a vonalak szerepe is ellenőrzendő."
                    )
        except (ValueError, KeyError, TypeError) as exc:
            st.error(f"A referencia nem használható: {exc}")
    for name in ("measurement.json", "camera.json", "events.csv", "windows.csv", "validation.json"):
        if (directory / name).is_file():
            st.download_button(
                name, (directory / name).read_bytes(), name, key=f"flow-download-{name}"
            )
