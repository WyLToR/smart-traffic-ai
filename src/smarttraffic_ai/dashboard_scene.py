from __future__ import annotations

import hashlib
import io
import json
import zipfile
from pathlib import Path

import pandas as pd
import streamlit as st

from smarttraffic_ai.config import AppConfig, load_yaml
from smarttraffic_ai.detection import CATEGORY_LABELS, MOTOR_VEHICLES, DetectionResult, Region
from smarttraffic_ai.flow import CameraProfile
from smarttraffic_ai.samples import sample_for_hash
from smarttraffic_ai.scene import DIRECTIONS, SceneSettings, analyze_image, analyze_video
from smarttraffic_ai.scene_sumo import compare_scene, generate_scene, run_scene


def _mapping_editor(data, key):
    rows = []
    tracks = data.get("tracks", []) if isinstance(data, dict) else data.objects
    for index, obj in enumerate(tracks):
        rows.append(
            {
                "Azonosító": obj["track_id"] if isinstance(obj, dict) else index,
                "Kategória": CATEGORY_LABELS[
                    obj["category"] if isinstance(obj, dict) else obj.category
                ],
                "Irány": "Zóna szerint",
            }
        )
    if not rows:
        return {}
    edited = st.data_editor(
        pd.DataFrame(rows),
        hide_index=True,
        key=f"scene-mapping-{key}",
        disabled=["Azonosító", "Kategória"],
        column_config={
            "Irány": st.column_config.SelectboxColumn(
                options=["Zóna szerint", "Kihagyás", *DIRECTIONS],
                required=True,
            )
        },
    )
    return {
        int(row["Azonosító"]): row["Irány"] if row["Irány"] in DIRECTIONS else None
        for row in edited.to_dict("records")
        if row["Irány"] != "Zóna szerint"
    }


def render_scene_tab(root: Path, available: bool):
    st.write("A felismerésből sablonos SUMO-helyzet készül. Ellenőrizd az ágak megfeleltetését.")
    session = st.session_state.get("live_session")
    if session is not None and not session.running and getattr(session, "result", None):
        st.session_state["live_result"] = session.result
    live_result = st.session_state.get("live_result")
    if live_result and st.session_state.get("scene-live-seen") != live_result["directory"]:
        st.session_state["scene-input"] = "Legutóbbi élő vizsgálat"
        st.session_state["scene-live-seen"] = live_result["directory"]
    mode = st.radio(
        "Felismerési eredmény",
        ["Legutóbbi kép", "Legutóbbi videó", "Legutóbbi élő vizsgálat", "Mentett eredmény"],
        horizontal=True,
        key="scene-input",
    )
    path = None
    if mode == "Legutóbbi kép" and "detection" in st.session_state:
        path = Path(st.session_state["detection"])
    elif mode == "Legutóbbi videó" and "video_result" in st.session_state:
        path = Path(st.session_state["video_result"]["directory"]) / "analysis.json"
    elif mode == "Legutóbbi élő vizsgálat" and live_result:
        path = Path(live_result["directory"]) / "analysis.json"
    elif mode == "Mentett eredmény":
        cfg = load_yaml(root / "config/app.yaml", AppConfig)
        outputs = root / cfg.output_dir
        files = sorted(
            [
                *outputs.glob("detection-*/detection.json"),
                *outputs.glob("video-*/analysis.json"),
                *outputs.glob("live-*/analysis.json"),
            ],
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if files:
            path = st.selectbox(
                "Mentett kép- vagy videófelismerés",
                files,
                format_func=lambda p: p.parent.name,
                key="scene-file",
            )
    if path is None:
        if mode == "Legutóbbi élő vizsgálat":
            st.info(
                "A lezárt élő videóvizsgálat itt jelenik meg. A korábbi, pozícióexport "
                "nélküli vizsgálatot újra kell futtatni. A 30 másodpercenként frissülő "
                "kamerakép nem folyamatos videóvizsgálat."
            )
            return
        st.info(
            "Előbb dolgozz fel egy képet vagy MP4-videót a megfelelő lapon, "
            "vagy válassz mentett eredményt."
        )
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        video = "tracks" in data
        observation = data if video else DetectionResult.model_validate(data)
        source_key = hashlib.sha256(str(path).encode()).hexdigest()[:12]
        if video:
            if data.get("source_kind") == "live":
                st.caption(
                    f"Élő vizsgálat: {data['frames']} elemzett képkocka, "
                    f"{data['duration_seconds']:.1f} s megfigyelt idő "
                    f"(kért idő: {data['requested_seconds']} s). "
                    "A mintavétel közötti mozgás becsült; a teljes videót nem rögzítjük."
                )
                if data.get("error"):
                    st.warning(f"Megszakadt vizsgálat, részeredmény: {data['error']}")
                if (path.parent / "preview.jpg").is_file():
                    st.image(str(path.parent / "preview.jpg"), caption="Utolsó elemzett kép")
            if (path.parent / "annotated.mp4").is_file():
                st.video(str(path.parent / "annotated.mp4"))
        elif (path.parent / "annotated.png").is_file():
            st.image(
                str(path.parent / "annotated.png"), caption="Felismerések az eredeti képméretben"
            )
        st.caption(
            "N/E/S/W a kiválasztott sablon bevezető ágait jelenti. "
            "A kép bal oldala nem automatikusan W. A parkoló járműveket kézzel hagyd ki; "
            "a régi példa-zónákat nem vesszük át automatikusan."
        )
        mapping = _mapping_editor(observation, source_key)
        preset_zones = []
        sample = (
            sample_for_hash(root, data.get("original_input_sha256", data["input_sha256"]))
            if video
            else None
        )
        if sample and sample.camera_profile and (root / sample.camera_profile).is_file():
            camera = CameraProfile.model_validate_json(
                (root / sample.camera_profile).read_text(encoding="utf-8")
            )
            st.info(camera.notes)
            if st.checkbox(
                "A videóhoz előkészített zónák használata",
                value=True,
                key=f"scene-camera-{source_key}",
            ):
                preset_zones = camera.zones
        with st.expander("Megfigyelési zónák (normalizált koordináták)"):
            st.caption(
                "A befoglaló téglalap alsó középpontja dönti el a zónát. "
                "A kézi hozzárendelés felülírja a zónát."
            )
            columns = ["ID", "Irány", "Bal", "Fent", "Jobb", "Lent"]
            edited = st.data_editor(
                pd.DataFrame(
                    [
                        dict(zip(columns, [zone.id, zone.direction, *zone.bounds], strict=True))
                        for zone in preset_zones
                    ],
                    columns=columns,
                ),
                num_rows="dynamic",
                hide_index=True,
                key=f"scene-zones-{source_key}",
                column_config={
                    "Irány": st.column_config.SelectboxColumn(
                        options=list(DIRECTIONS), required=True
                    ),
                    **{
                        name: st.column_config.NumberColumn(
                            min_value=0.0, max_value=1.0, required=True
                        )
                        for name in columns[2:]
                    },
                },
            )
            regions = [
                Region(
                    id=str(row["ID"]),
                    direction=row["Irány"],
                    bounds=tuple(float(row[c]) for c in columns[2:]),
                )
                for row in edited.to_dict("records")
                if pd.notna(row["ID"])
            ]
        left, right = st.columns(2)
        intersection = left.selectbox(
            "Kereszteződés",
            ["four_way", "t_junction"],
            format_func=lambda v: "Négyágú" if v == "four_way" else "T-csomópont",
        )
        missing = right.selectbox(
            "Hiányzó ág (T-csomópont)",
            list(DIRECTIONS),
            index=2,
            disabled=intersection != "t_junction",
        )
        lanes = left.number_input("Sávok irányonként", 1, 3, 1)
        length = right.number_input("Ághossz (m, feltételezett)", 50.0, 2000.0, 250.0, 10.0)
        speed = left.number_input("Sebességhatár (km/h)", 10.0, 70.0, 50.0, 5.0)
        signalized = right.checkbox("Jelzőlámpás csomópont", value=True)
        duration = left.number_input("Szimulált forgalom időtartama (s)", 20, 3600, 120, 10)
        warmup = right.number_input("Kezdeti állapot beállása (s)", 0, 60, 5)
        seed = left.number_input("Véletlen mag", 0, 2147483647, 42)
        straight = left.slider("Egyenes haladás aránya", 0.0, 1.0, 0.8, 0.05)
        turn_left = right.slider("Balra kanyarodás aránya", 0.0, 1.0, 0.1, 0.05)
        arrival_mode = st.radio(
            "Későbbi érkezések",
            ["configured", "occupancy-weighted", "measured"]
            if video
            else ["configured", "occupancy-weighted"],
            format_func=lambda v: {
                "configured": "Kézzel megadott intenzitás",
                "occupancy-weighted": "Foglaltsággal súlyozott intenzitási feltételezés",
                "measured": "Követett vonalátlépések időbélyegei",
            }[v],
            key="scene-arrivals",
        )
        rates = dict.fromkeys(DIRECTIONS, 0.0)
        prior = 300.0
        flow_path = validation_path = None
        experimental = False
        if arrival_mode == "configured":
            fields = st.columns(4)
            for side, field in zip(DIRECTIONS, fields, strict=True):
                rates[side] = field.number_input(
                    f"{side} érkezés (jármű/óra)", 0.0, 10000.0, 0.0, 50.0
                )
        elif arrival_mode == "occupancy-weighted":
            prior = st.number_input(
                "Intenzitási alapérték (jármű/óra/ág, feltételezett)", 0.0, 2500.0, 300.0, 50.0
            )
        else:
            outputs = root / load_yaml(root / "config/app.yaml", AppConfig).output_dir
            signature = hashlib.sha256(path.read_bytes()).hexdigest()
            measurements = [
                p
                for p in outputs.glob("flow-*/measurement.json")
                if json.loads(p.read_text(encoding="utf-8")).get("analysis_sha256") == signature
            ]
            measurements.sort(key=lambda p: p.stat().st_mtime, reverse=True)
            if not measurements:
                st.info("Előbb készíts ehhez a videóhoz mérést a Forgalommérés lapon.")
                return
            flow_path = st.selectbox(
                "A videóhoz tartozó forgalommérés",
                measurements,
                format_func=lambda p: p.parent.name,
                key="scene-flow-measurement",
            )
            candidate = flow_path.parent / "validation.json"
            validation_path = candidate if candidate.is_file() else None
            experimental = st.checkbox(
                "Kísérleti futtatás: a beérkezési pontosság még nem igazolt.", value=False
            )
            st.caption(
                "Mért módban a kamera mentett zónái és a videó eredeti időhorizontja érvényes. "
                "A kezdeti ID-k, a helyi/stopvonali áthaladások "
                "és a bizonytalan események nem adnak új érkezést."
            )
        settings = SceneSettings(
            intersection_type=intersection,
            missing_arm=missing,
            lanes=lanes,
            arm_length=length,
            speed_kmh=speed,
            signalized=signalized,
            simulation_seconds=duration,
            warmup_seconds=warmup,
            seed=seed,
            regions=regions,
            object_directions={} if video else mapping,
            track_directions=mapping if video else {},
            turns={"straight": straight, "left": turn_left, "right": 1 - straight - turn_left},
            arrival_mode=arrival_mode,
            arrival_rates=rates,
            prior_rate=prior,
            flow_measurement_path=str(flow_path) if flow_path else None,
            flow_validation_path=str(validation_path) if validation_path else None,
            allow_unvalidated_flow=experimental,
        )
        scene = analyze_video(path, settings) if video else analyze_image(observation, settings)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        st.error(f"A forgalmi helyzet nem állítható össze: {exc}")
        return
    st.dataframe(
        [
            {
                "Ág": a.id,
                **{CATEGORY_LABELS[c]: a.observed_counts[c] for c in MOTOR_VEHICLES},
                "Kezdeti szimulált terhelés": sum(a.initial_vehicles.values()),
                "Becsült sorhossz": "Ismeretlen",
            }
            for a in scene.approaches
        ],
        hide_index=True,
    )
    st.caption(
        f"Irányhoz nem rendelt közlekedők a kezdőképen: {sum(scene.unassigned_counts.values())}. "
        "A látható gépjárművek kezdetben sablonpozíciókba kerülnek, "
        "a későbbi érkezések külön igényt alkotnak."
    )
    if scene.measured_flow:
        from smarttraffic_ai.flow import select_arrivals

        arrivals, excluded = select_arrivals(scene.measured_flow)
        st.write(
            f"Későbbi, mért új érkezések: {len(arrivals)}; eredeti megfigyelési idő: "
            f"{scene.measured_flow.duration_seconds:.2f} s. Kizárások: {excluded}."
        )
    with st.expander("Feltételezések és az adatok eredete"):
        st.json(scene.provenance)
        for text in scene.assumptions:
            st.write(text)
        st.dataframe(
            [
                {"Kezdet (s)": w.begin, "Vég (s)": w.end, **w.rates}
                for w in scene.estimated_arrivals
            ],
            hide_index=True,
        )
    if not any(sum(a.initial_vehicles.values()) for a in scene.approaches) and not any(
        sum(w.rates.values()) for w in scene.estimated_arrivals
    ):
        st.warning(
            "Nincs hozzárendelt gépjármű vagy későbbi érkezés: a generált szimuláció üres lesz."
        )
    reviewed = st.checkbox("Ellenőriztem az ágak megfeleltetését és a feltételezett paramétereket.")
    signature = hashlib.sha256(scene.model_dump_json().encode()).hexdigest()
    if st.button("SUMO-forgatókönyv létrehozása", disabled=not available or not reviewed):
        try:
            with st.spinner("Hálózat és járműigény generálása…"):
                directory = generate_scene(root, scene)
            st.session_state["scene_bundle"] = str(directory)
            st.session_state["scene_signature"] = signature
            st.session_state.pop("scene_run", None)
            st.session_state.pop("scene_comparison", None)
            st.success("A forgatókönyv elkészült.")
        except Exception as exc:
            st.error(f"A generálás nem sikerült: {exc}")
    directory = st.session_state.get("scene_bundle")
    if not directory:
        return
    if st.session_state.get("scene_signature") != signature:
        st.info("A beállítások megváltoztak. Az új helyzethez generáld újra a forgatókönyvet.")
        return
    st.code(str(directory), language=None)
    gui = st.checkbox("SUMO-GUI megnyitása a futtatáshoz", key="scene-gui")
    control = st.selectbox(
        "A generált helyzet vezérlése",
        ["fixed", "adaptive"],
        format_func=lambda v: "Fix" if v == "fixed" else "Adaptív",
    )
    if st.button("Generált forgalom indítása", disabled=not available):
        try:
            with st.spinner("A generált SUMO-helyzet fut…"):
                st.session_state["scene_run"] = run_scene(root, Path(directory), control, gui)
        except Exception as exc:
            st.error(f"A generált helyzet futtatása nem sikerült: {exc}")
    if st.button("Fix és adaptív összehasonlítása", disabled=not available or not signalized):
        try:
            with st.spinner("Két vezérlés futtatása ugyanazzal a járműigénnyel…"):
                st.session_state["scene_comparison"] = compare_scene(root, Path(directory))
        except Exception as exc:
            st.error(f"Az összehasonlítás nem sikerült: {exc}")
    if "scene_run" in st.session_state:
        from smarttraffic_ai.dashboard import show_run

        show_run(st.session_state["scene_run"], "scene-run")
    if "scene_comparison" in st.session_state:
        from smarttraffic_ai.dashboard import METRIC_LABELS

        report = st.session_state["scene_comparison"]
        st.caption(report["note"])
        st.dataframe(
            [
                {
                    "Vezérlés": "Fix" if r["controller"] == "fixed" else "Adaptív",
                    **{METRIC_LABELS.get(k, k): v for k, v in r["metrics"].items()},
                }
                for r in report["runs"]
            ],
            hide_index=True,
        )
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as bundle:
        for name in (
            "scene.json",
            "scenario.json",
            "network.net.xml",
            "demand.rou.xml",
            "signals.add.xml",
            "simulation.sumocfg",
            "manifest.json",
            "demand.json",
            "intersection.nod.xml",
            "intersection.edg.xml",
            "intersection.con.xml",
            "flow-measurement.json",
            "flow-validation.json",
            "flow-exclusions.json",
        ):
            file = Path(directory) / name
            if file.is_file():
                bundle.write(file, name)
    st.download_button(
        "Teljes SUMO-csomag (ZIP)",
        archive.getvalue(),
        "sumo-scene.zip",
        mime="application/zip",
        key="scene-download-zip",
    )
