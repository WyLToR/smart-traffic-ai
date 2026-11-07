from __future__ import annotations

import json

import streamlit as st

from smarttraffic_ai.dashboard_video import (
    configure_lights,
    count_rows,
    light_rows,
    track_rows,
)
from smarttraffic_ai.detection import CATEGORY_LABELS
from smarttraffic_ai.live import LiveSession, fresh, validate_source


def render_live_tab(root, has_yolo):
    from smarttraffic_ai.dashboard_detection import (
        detection_settings,
        show_diagnostics,
        show_processing,
    )

    config = detection_settings(root, "live")
    url = st.text_input(
        "Kameraoldal, videó vagy frissülő kép URL",
        value="https://www.idokep.hu/webkamera/hgabesz",
        key="live_source",
    )
    st.caption(
        "YouTube élő link, Időkép vagy Budapest Közút kameraoldal, közvetlen HLS (.m3u8), "
        "HTTP(S) videó, "
        "RTSP vagy JPG/PNG kép. "
        "A blob: cím helyett a kameraoldal címét add meg. A kép a forrás saját késésével érkezik."
    )
    seconds = st.number_input("Elemzés időtartama (másodperc)", 10, 600, 120, 10)
    fps = st.slider("Elemzési mintavétel (kép/másodperc)", 1, 10, 5)
    regions = []
    valid = True
    try:
        validate_source(url)
        regions = configure_lights(root, source_key=url)
    except (ValueError, TypeError, KeyError) as exc:
        valid = False
        st.error(str(exc))
    st.caption(
        "Csak a hat közlekedési kategória és a jelzőlámpák kerülnek elemzésre. "
        "A gyalogos/jármű lámpatípust a fenti panelen adhatod meg. "
        "A számlálás legalább 3 észlelést és 0,5 s becsült láthatóságot vár meg. "
        "Videónál az idők az első elemzett képkockától értendők; "
        "a látható idő mintavételi becslés, "
        "a hálózati kimaradás nem számít bele. Új indításkor új számlálás kezdődik."
    )
    st.caption(
        "Frissülő kameraképnél 30 másodpercenként kérünk új képet. Ilyenkor képenkénti "
        "darabszám készül, folyamatos követés és láthatósági idő nélkül; "
        "a videó mintavételi beállítása erre nem vonatkozik."
    )

    @st.fragment(run_every=0.5)
    def live_view():
        session = st.session_state.get("live_session")
        running = session is not None and session.running
        start, stop = st.columns(2)
        if start.button(
            "Élő elemzés indítása",
            disabled=(
                not has_yolo or not valid or running or not (root / config.model_path).is_file()
            ),
        ):
            session = LiveSession(root, url, regions, seconds, fps, config=config).start()
            st.session_state["live_session"] = session
        if stop.button("Élő elemzés leállítása", disabled=session is None or not session.running):
            session.stop()
        if session is None:
            if not has_yolo:
                st.info("Az élő elemzéshez helyi YOLO-modell és a vision függőségek szükségesek.")
            return
        event, status, error = session.snapshot()
        st.write(
            "Leállítás folyamatban…" if session.running and session.stop_event.is_set() else status
        )
        if error:
            st.error(error)
        if event is None:
            return
        snapshot = event.get("source_kind") == "snapshot"
        current = session.running and not session.stop_event.is_set() and fresh(event)
        label = (
            "Legutóbbi kamerakép"
            if snapshot
            else ("Élő kép" if current else "Utolsó feldolgozott kép")
        )
        st.image(
            event["image"],
            channels="BGR",
            width="stretch",
            caption=f"{label} · {event['seconds']:.1f} s · {event['frames']} elemzett képkocka",
        )
        if snapshot:
            import time

            if event.get("source_captured_at"):
                st.caption(f"A forrás képének időbélyege: {event['source_captured_at']}")
            st.info(
                "Képenkénti elemzés: nincs folyamatos videó, összesített egyedi járműszám "
                "vagy mérhető láthatósági idő. A lámpaszín az adott képből becsült, "
                "nem folyamatosan ellenőrzött jelzés. "
                f"Az utolsó feldolgozott képet {time.monotonic() - event['received_at']:.0f} s "
                "óta tároljuk; a kamera felvétele ennél régebbi is lehet."
            )
            st.dataframe(
                [
                    {"Kategória": CATEGORY_LABELS[name], "Ezen a képen": count}
                    for name, count in event["counts"].items()
                ],
                hide_index=True,
                width="stretch",
            )
            st.dataframe(light_rows(event["lights"]), hide_index=True, width="stretch")
        elif current:
            st.dataframe(
                count_rows(event["summary"], detections=event.get("detections_by_category")),
                hide_index=True,
                width="stretch",
            )
            st.dataframe(light_rows(event["lights"]), hide_index=True, width="stretch")
        else:
            st.info(
                "Nincs friss elemzett kép. Az utolsó észlelés nem jelzi a jelenlegi lámpaállapotot."
            )
            st.dataframe(
                count_rows(
                    event["summary"], "Utolsó megerősített ID", event.get("detections_by_category")
                ),
                hide_index=True,
                width="stretch",
            )
        if not snapshot:
            st.dataframe(track_rows(event["tracks"]), hide_index=True, width="stretch")
        show_diagnostics(event.get("diagnostics"))
        show_processing(event.get("config"), event.get("runtime"))
        if not session.running:
            saved = getattr(session, "result", None)
            if saved is not None:
                previous = st.session_state.get("live_result", {})
                if previous.get("directory") != saved["directory"]:
                    st.session_state["live_result"] = saved
                    st.rerun()
                st.success(
                    "Az élő vizsgálat mentve. A Kép/videó → SUMO lapon "
                    "a Legutóbbi élő vizsgálat bemenetet válaszd."
                )
            elif not snapshot:
                st.warning(
                    "Ehhez a korábbi vizsgálathoz nincs mentett pozícióexport. "
                    "Az összesítés letölthető, de a SUMO-átadáshoz indíts új élő elemzést."
                )
            result = {key: value for key, value in event.items() if key != "image"}
            result.pop("received_at", None)
            result["time_basis"] = (
                "independent snapshots; no tracking or visibility duration"
                if snapshot
                else "monotonic since first analyzed frame; sampled visibility estimate"
            )
            st.download_button(
                "Élő elemzés eredménye (JSON)",
                json.dumps(result, ensure_ascii=False, indent=2),
                "live-analysis.json",
                mime="application/json",
            )

    live_view()
