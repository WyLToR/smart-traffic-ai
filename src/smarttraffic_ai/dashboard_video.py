from __future__ import annotations

import hashlib
from pathlib import Path

import streamlit as st

from smarttraffic_ai.detection import CATEGORY_LABELS, TRAFFIC_CATEGORIES
from smarttraffic_ai.samples import available_samples, video_digest
from smarttraffic_ai.simulation import output_directory
from smarttraffic_ai.traffic_lights import (
    KIND_LABELS,
    STATE_LABELS,
    LightRegion,
    annotate_lights,
    regions_for_video,
)
from smarttraffic_ai.video import process_video


def count_rows(summary, current_label="Most megerősített ID", detections=None):
    return [
        {
            "Kategória": CATEGORY_LABELS[name],
            current_label: summary["current_by_category"][name],
            "Összes követett ID": summary["by_category"][name],
            **({"Képkockán felismert objektum": detections[name]} if detections else {}),
        }
        for name in TRAFFIC_CATEGORIES
    ]


def track_rows(tracks):
    return [
        {
            "ID": track["track_id"],
            "Kategória": CATEGORY_LABELS[track["category"]],
            "Első észlelés (s)": round(track["first_seen_seconds"], 2),
            "Utolsó észlelés (s)": round(track["last_seen_seconds"], 2),
            "Látható idő (s)": round(track["visible_seconds"], 2),
            "Első–utolsó időszak (s)": round(track["span_seconds"], 2),
        }
        for track in tracks
    ]


def light_rows(lights):
    return [
        {
            "Lámpa": light["light_id"],
            "Típus": KIND_LABELS[light["kind"]],
            "Jelzés": STATE_LABELS[light["state"]],
            "Típus alapja": "Kamerabeállítás"
            if light["kind_source"] == "camera-config"
            else "Ismeretlen",
        }
        for light in lights
    ]


def configure_lights(root, path=None, source_key="live"):
    import pandas as pd

    digest = video_digest(path) if path else hashlib.sha256(source_key.encode()).hexdigest()
    defaults = regions_for_video(root, digest) if path else []
    with st.expander("Lámpák és típusuk beállítása"):
        st.caption(
            "A szín a képből készül. A YOLO nem különbözteti meg a gyalogos- és "
            "járműjelzőt: a típust itt rendelheted hozzá a kijelölt területhez. "
            "A koordináták 0–1 közöttiek, a bal felső saroktól számítva."
        )
        columns = ["ID", "Típus", "Bal", "Fent", "Jobb", "Lent", "Min. fényesség"]
        data = pd.DataFrame(
            [
                dict(
                    zip(
                        columns,
                        [r.id, KIND_LABELS[r.kind], *r.bounds, r.min_brightness],
                        strict=True,
                    )
                )
                for r in defaults
            ],
            columns=columns,
        )
        edited = st.data_editor(
            data,
            num_rows="dynamic",
            hide_index=True,
            key=f"light-regions-{digest}",
            column_config={
                "ID": st.column_config.TextColumn(required=True),
                "Típus": st.column_config.SelectboxColumn(
                    options=list(KIND_LABELS.values()), required=True
                ),
                **{
                    name: st.column_config.NumberColumn(
                        min_value=0.0, max_value=1.0, step=0.001, required=True
                    )
                    for name in columns[2:6]
                },
                "Min. fényesség": st.column_config.NumberColumn(
                    min_value=0, max_value=255, step=1, default=100, required=True
                ),
            },
        )
        reverse = {label: key for key, label in KIND_LABELS.items()}
        regions = [
            LightRegion(
                id=str(row["ID"]),
                kind=reverse[row["Típus"]],
                bounds=tuple(float(row[name]) for name in columns[2:6]),
                min_brightness=int(row["Min. fényesség"])
                if pd.notna(row["Min. fényesség"])
                else 100,
            )
            for row in edited.to_dict("records")
            if pd.notna(row["ID"])
        ]
        if len({r.id for r in regions}) != len(regions):
            raise ValueError("A lámpák ID-je legyen egyedi.")
        if path is None:
            st.caption("A beállítások a következő élő indításkor lépnek életbe.")
            return regions
        import cv2

        capture = cv2.VideoCapture(str(path))
        try:
            ok, frame = capture.read()
            if ok:
                height, width = frame.shape[:2]
                readings = [
                    {
                        "light_id": r.id,
                        "kind": r.kind,
                        "state": "unknown",
                        "bbox": (
                            r.bounds[0] * width,
                            r.bounds[1] * height,
                            r.bounds[2] * width,
                            r.bounds[3] * height,
                        ),
                    }
                    for r in regions
                ]
                st.image(
                    annotate_lights(frame, readings),
                    channels="BGR",
                    caption="Kijelölt lámpaterületek az első képkockán",
                    width="stretch",
                )
        finally:
            capture.release()
    return regions


def show_video_result(result):
    from smarttraffic_ai.dashboard_detection import show_counts, show_processing

    st.subheader(f"Eredmény: {result['input_name']}")
    sampling = result.get("sampling", {})
    if sampling.get("resampled"):
        st.info(
            f"Választott elemzési változat: {sampling['requested_fps']} FPS "
            f"az eredeti {sampling['source_fps']:.2f} FPS helyett. "
            "A videó normál időben játszódik le; a követés eltérhet az eredeti képkockás módtól."
        )
    if result.get("frame_count_note"):
        st.info(result["frame_count_note"])
    show_processing(
        result.get("config"),
        result.get("runtime"),
        result["processing_seconds"],
        result.get("processing_fps"),
    )
    st.video(result["video_path"])
    st.metric("Összes megerősített azonosító", result["summary"]["total_unique"])
    show_counts(
        result["summary"]["by_category"],
        "A teljes videó megerősített ID-i, nem áthaladási események.",
    )
    st.dataframe(
        count_rows(
            result["summary"], "Utolsó megerősített ID", result.get("last_detections_by_category")
        ),
        hide_index=True,
        width="stretch",
    )
    st.dataframe(track_rows(result["tracks"]), hide_index=True, width="stretch")
    st.subheader("Jelzőlámpák az utolsó képkockán")
    st.dataframe(light_rows(result.get("last_light_readings", [])), hide_index=True)
    if result.get("traffic_lights"):
        st.dataframe(
            [
                {
                    "Lámpa": light["light_id"],
                    "Típus": KIND_LABELS[light["kind"]],
                    **{
                        f"{STATE_LABELS[state]} (s)": round(seconds, 2)
                        for state, seconds in light["state_seconds"].items()
                    },
                }
                for light in result["traffic_lights"]
            ],
            hide_index=True,
        )
    directory = Path(result["directory"])
    for name, label, mime in [
        ("annotated.mp4", "Jelölt videó letöltése", "video/mp4"),
        ("tracks.csv", "Azonosítók és látható idők (CSV)", "text/csv"),
        ("analysis.json", "Teljes elemzés (JSON)", "application/json"),
        ("detections.jsonl", "Képkockánkénti felismerések (JSONL)", "application/x-ndjson"),
        ("timeline.csv", "Képkockánkénti számlálás (CSV)", "text/csv"),
        ("traffic-lights.csv", "Lámpák állapota és típusa (CSV)", "text/csv"),
    ]:
        if not (directory / name).is_file():
            continue
        st.download_button(
            label, (directory / name).read_bytes(), name, mime=mime, key=f"video-download-{name}"
        )


def render_video_tab(root: Path, has_yolo: bool):
    st.write("Autók, buszok, teherautók, motorok, kerékpárok és gyalogosok követése.")
    samples = available_samples(root)
    source = st.radio(
        "Videó forrása",
        ["Feltöltés", "Mintavideó", "Élő forrás"] if samples else ["Feltöltés", "Élő forrás"],
        horizontal=True,
    )
    if source == "Élő forrás":
        from smarttraffic_ai.dashboard_live import render_live_tab

        render_live_tab(root, has_yolo)
        return
    from smarttraffic_ai.dashboard_detection import detection_settings, show_diagnostics

    config = detection_settings(root, "video")
    session = st.session_state.get("live_session")
    if session is not None:
        session.stop()
    uploaded = None
    path = None
    if source == "Mintavideó":
        sample = st.selectbox("Mintavideó", samples, format_func=lambda item: item.label)
        path = root / sample.path
        if sample.description:
            st.caption(sample.description)
    else:
        uploaded = st.file_uploader("Közlekedési videó (MP4)", type=["mp4"], key="traffic-video")
        if uploaded is not None:
            digest = hashlib.sha256(uploaded.getbuffer()).hexdigest()
            stored = st.session_state.get("saved_video_upload")
            if stored is None or stored[0] != digest:
                directory = output_directory(root, "video-upload")
                path = directory / "input.mp4"
                with path.open("wb") as stream:
                    stream.write(uploaded.getbuffer())
                st.session_state["saved_video_upload"] = (digest, str(path))
            else:
                path = Path(stored[1])
    light_regions = None
    analysis_fps = st.selectbox(
        "Elemzési képkockasebesség",
        [None, 30, 15],
        format_func=lambda value: (
            "Eredeti – minden képkocka"
            if value is None
            else f"Legfeljebb {value} FPS – gyorsabb elemzés"
        ),
        key="video-analysis-fps",
    )
    if analysis_fps is not None:
        st.caption(
            "Magasabb FPS-es forrásnál külön elemzési másolat készül, az eredeti fájl megmarad. "
            "Kevesebb időpillanatot vizsgálunk; "
            "a gyors objektumok és rövid lámpaváltások kimaradhatnak."
        )
    calibration_error = False
    if path is not None:
        try:
            light_regions = configure_lights(root, path)
        except (OSError, ValueError, TypeError, KeyError, ImportError) as exc:
            calibration_error = True
            st.error(f"A lámpabeállítás nem használható: {exc}")
    st.caption(
        "Egy ID legalább 3 észlelés és fél másodperc látható idő után számít az összesítésbe. "
        "A szám követett azonosítókat jelent: hosszabb takarás után ugyanaz új ID-t kaphat."
    )
    st.caption(
        "A látható idő csak az észlelt képkockák ideje; az első–utolsó időszak "
        "a köztes kihagyásokat is tartalmazza. Az idők a videó idővonalán értendők."
    )
    if st.button(
        "Videó feldolgozása",
        disabled=(
            not has_yolo
            or path is None
            or calibration_error
            or not (root / config.model_path).is_file()
        ),
    ):
        st.session_state.pop("video_result", None)
        progress = st.progress(
            0.0,
            text=(
                f"Legfeljebb {analysis_fps} FPS-es elemzési változat előkészítése…"
                if analysis_fps
                else "Videó megnyitása és modellbetöltés…"
            ),
        )
        preview = st.empty()
        counts = st.empty()
        tracks = st.empty()
        light_table = st.empty()

        def update(event, frame):
            ratio = min(1.0, event["frame"] / event["total_frames"]) if event["total_frames"] else 0
            progress.progress(
                ratio,
                text=f"{event['seconds']:.1f} s feldolgozva · "
                f"összes ID: {event['summary']['total_unique']}"
                + (
                    f" · {event['runtime']['warnings'][-1]}"
                    if event.get("runtime", {}).get("warnings")
                    else ""
                ),
            )
            preview.image(
                frame, channels="BGR", caption="Feldolgozás közbeni előnézet", width="stretch"
            )
            counts.dataframe(
                count_rows(event["summary"], detections=event["detections_by_category"]),
                hide_index=True,
                width="stretch",
            )
            tracks.dataframe(track_rows(event["tracks"]), hide_index=True, width="stretch")
            light_table.dataframe(light_rows(event["lights"]), hide_index=True, width="stretch")

        try:
            result = process_video(
                root,
                path,
                on_progress=update,
                light_regions=light_regions,
                config=config,
                analysis_fps=analysis_fps,
            )
            st.session_state["video_result"] = result
            progress.progress(1.0, text="Az elemzés elkészült.")
            preview.empty()
            counts.empty()
            tracks.empty()
            light_table.empty()
        except Exception as exc:
            progress.empty()
            st.error(f"A videó feldolgozása nem sikerült: {exc}")
    if "video_result" in st.session_state:
        show_video_result(st.session_state["video_result"])
        show_diagnostics(st.session_state["video_result"].get("diagnostics"))
    elif not has_yolo:
        st.info("A videóelemzéshez YOLO-modell és a vision függőségek szükségesek.")
    if "video_result" not in st.session_state:
        return
    result = st.session_state["video_result"]
    st.caption(
        f"{result['frames']} képkocka · {result['duration_seconds']:.2f} s videó · "
        f"{result['processing_seconds']:.1f} s feldolgozás. A kimeneti videó hang nélkül készül."
    )
