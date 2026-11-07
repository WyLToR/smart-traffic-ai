from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import plotly.express as px
import streamlit as st

from smarttraffic_ai.config import AppConfig, load_scenario, load_yaml, project_root
from smarttraffic_ai.dashboard_video import render_video_tab
from smarttraffic_ai.detection import CATEGORY_LABELS, DetectionConfig, DetectionResult, detect_file
from smarttraffic_ai.estimation import estimate_scenarios
from smarttraffic_ai.optimization import optimize
from smarttraffic_ai.simulation import binary, output_directory, run_simulation

METRIC_LABELS = {
    "demand": "Tervezett járművek",
    "departed": "Hálózatba lépett járművek",
    "arrived": "Célba ért járművek",
    "remaining": "Befejezetlen utak",
    "pending": "Bejutásra váró járművek",
    "active_at_end": "Hálózatban maradt járművek",
    "waiting_at_end": "A végén sorban vagy bejutásra várók",
    "mean_wait": "Átlagos várakozás (s)",
    "max_wait": "Legnagyobb várakozás (s)",
    "mean_travel_completed": "Célba értek átlagos utazási ideje (s)",
    "mean_queue": "Átlagos sorhossz (jármű)",
    "max_queue": "Legnagyobb sorhossz (jármű)",
    "total_stopped_seconds": "Összes állásidő (jármű·s)",
    "total_insertion_delay": "Összes bejutási késés (jármű·s)",
    "collision_vehicle_events": "Ütközésben érintett járműesemények",
    "moving_vehicle_steps": "Mozgó járművek összes mintavételi lépése",
    "red_stopped_vehicle_steps": "Piros jelzésnél álló járművek mintavételi lépései",
    "warmup_departed": "Beállási idő alatt hálózatba lépett járművek",
    "measured_arrivals": "Mért eseményből ütemezett új járművek",
    "measured_inserted": "Mért eseményből ténylegesen bejutott járművek",
    "measured_pending": "Mért eseményből bejutásra váró járművek",
    "measured_arrived": "Mért eseményből célba ért járművek",
}
for _side, _label in {"N": "Észak", "E": "Kelet", "S": "Dél", "W": "Nyugat"}.items():
    for _prefix, _meaning in {
        "demand": "Tervezett",
        "departed": "Hálózatba lépett",
        "arrived": "Célba ért",
    }.items():
        METRIC_LABELS[f"{_prefix}_{_side}"] = f"{_meaning} – {_label} (jármű)"
for _category, _label in CATEGORY_LABELS.items():
    METRIC_LABELS[f"demand_{_category}"] = f"Tervezett – {_label}"
SOURCE_LABELS = {
    "synthetic": "Szintetikus",
    "image-estimate": "Képből származó, feltételezett",
    "video-estimate": "Videóból származó, becsült",
    "video-measured": "Követett vonalátlépésekből (a pontosságot a referenciariport jelzi)",
    "mock-estimate": "Mock adaton alapuló, feltételezett",
}


def show_run(result, prefix="current-run"):
    st.caption(f"{result['scenario']['name']} · {SOURCE_LABELS[result['scenario']['source']]}")
    metrics = result["metrics"]
    columns = st.columns(3)
    columns[0].metric("Átlagos várakozás", f"{metrics['mean_wait']:.2f} s")
    columns[1].metric("Célba ért járművek", metrics["arrived"])
    columns[2].metric("Befejezetlen utak", metrics["remaining"])
    st.table(
        [{"Mutató": METRIC_LABELS.get(key, key), "Érték": value} for key, value in metrics.items()]
    )
    directory = Path(result["directory"])
    timeline = directory / "timeline.csv"
    if timeline.is_file():
        import pandas as pd

        data = pd.read_csv(timeline)
        data = data.rename(
            columns={"time": "Idő (s)", "ns_queue": "Észak–dél", "ew_queue": "Kelet–nyugat"}
        )
        st.plotly_chart(
            px.line(
                data,
                x="Idő (s)",
                y=["Észak–dél", "Kelet–nyugat"],
                labels={"value": "Várakozó járművek", "variable": "Irány"},
            ),
            width="stretch",
            key=f"{prefix}-timeline",
        )
    st.download_button(
        "Mérési eredmény letöltése (JSON)",
        json.dumps(result, ensure_ascii=False, indent=2),
        "result.json",
        key=f"{prefix}-json",
    )
    if (directory / "metrics.csv").is_file():
        st.download_button(
            "Mérési eredmény letöltése (CSV)",
            (directory / "metrics.csv").read_bytes(),
            "metrics.csv",
            key=f"{prefix}-csv",
        )


def show_comparison(report, prefix="current-comparison"):
    best = report["best"]
    st.success(f"Legjobb a vizsgált jelöltek között: {best['candidate']}")
    st.caption("A mutatók a véletlen magok szerinti futások átlagai. Kisebb pontszám kedvezőbb.")
    baseline = next(row for row in report["summary"] if row["candidate"] == "fixed-baseline")
    difference = best["mean_wait"] - baseline["mean_wait"]
    st.metric(
        "A kiválasztott program átlagos várakozása",
        f"{best['mean_wait']:.2f} s",
        f"{difference:+.2f} s a fix alaphoz képest",
        delta_color="inverse",
    )
    rows = [
        {
            "Program": row["candidate"],
            "Észak–déli zöld (s)": row["ns_green"],
            "Kelet–nyugati zöld (s)": row["ew_green"],
            "Pontszám": row["score"],
            "Átlagos várakozás (s)": row["mean_wait"],
            "Célba ért": row["arrived"],
            "Befejezetlen": row["remaining"],
            "Futások": row["runs"],
        }
        for row in report["summary"]
    ]
    st.dataframe(rows, hide_index=True)
    st.plotly_chart(
        px.bar(rows, x="Program", y="Átlagos várakozás (s)"), width="stretch", key=f"{prefix}-chart"
    )
    st.download_button(
        "Összehasonlítás letöltése (JSON)",
        json.dumps(report, ensure_ascii=False, indent=2),
        "comparison.json",
        key=f"{prefix}-json",
    )
    csv_path = Path(report["directory"]) / "comparison.csv"
    if csv_path.is_file():
        st.download_button(
            "Összehasonlítás letöltése (CSV)",
            csv_path.read_bytes(),
            "comparison.csv",
            key=f"{prefix}-csv",
        )


def main():
    root = project_root()
    app = load_yaml(root / "config/app.yaml", AppConfig)
    st.set_page_config(page_title=app.title, layout="wide")
    st.title(app.title)
    st.write("Forgalmi forgatókönyvek és jelzőlámpa-programok összehasonlítása SUMO-szimulációban.")
    st.caption("Oktatási v0.1.0 · Kizárólag szimulált jelzőlámpa-vezérlés")
    try:
        binary("sumo")
        binary("netconvert")
        available = True
        st.success("A SUMO-integráció elérhető.")
    except FileNotFoundError as exc:
        available = False
        st.warning(str(exc))
    detection_cfg = load_yaml(root / "config/detection.yaml", DetectionConfig)
    has_yolo = (root / detection_cfg.model_path).is_file() and importlib.util.find_spec(
        "ultralytics"
    ) is not None
    st.info(
        "YOLO-modell és csomag elérhető."
        if has_yolo
        else "YOLO-modell vagy csomag nincs telepítve. A SUMO ettől függetlenül használható."
    )
    latest_runs = sorted(
        (root / app.output_dir).glob("run-*/result.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if latest_runs:
        try:
            latest = json.loads(latest_runs[0].read_text(encoding="utf-8"))
            st.caption(
                f"Utolsó szimuláció: {latest['scenario']['name']}; "
                f"átlagos várakozás: {latest['metrics']['mean_wait']:.2f} s; "
                f"célba ért: {latest['metrics']['arrived']} jármű."
            )
        except (OSError, ValueError, KeyError):
            st.caption("Az utolsó eredmény nem olvasható.")
    scenario_tab, image_tab, video_tab, flow_tab, scene_tab, result_tab = st.tabs(
        [
            "Forgatókönyvek és futtatás",
            "Képfeldolgozás",
            "Videóelemzés",
            "Forgalommérés",
            "Kép/videó → SUMO",
            "Eredmények",
        ]
    )
    with scenario_tab:
        paths = sorted((root / "data/scenarios").glob("*.yaml"))
        scenarios = {path.stem: load_scenario(root, path.stem) for path in paths}
        selected = st.selectbox(
            "Forgatókönyv", list(scenarios), format_func=lambda key: scenarios[key].name
        )
        scenario = scenarios[selected]
        st.write(f"Adatforrás: {SOURCE_LABELS[scenario.source]}; időtartam: {scenario.duration} s.")
        st.table(
            [
                {
                    "Kezdet (s)": window.begin,
                    "Vége (s)": window.end,
                    **{f"{d} (jármű/óra)": rate for d, rate in window.rates.items()},
                }
                for window in scenario.windows
            ]
        )
        for assumption in scenario.assumptions:
            st.write(f"• {assumption}")
        controller = st.radio(
            "Vezérlés",
            ["fixed", "adaptive"],
            horizontal=True,
            format_func=lambda mode: "Fix" if mode == "fixed" else "Adaptív",
        )
        if st.button("Szimuláció indítása", disabled=not available):
            with st.spinner("A SUMO-szimuláció fut…"):
                try:
                    st.session_state["run"] = run_simulation(root, scenario, controller)
                    st.success("A futás befejeződött. Az Eredmények lapon megtekinthető.")
                except Exception as exc:
                    st.error(f"A szimuláció nem sikerült: {exc}")
        if st.button("Optimalizálási kísérlet indítása", disabled=not available):
            with st.spinner("Jelöltek összehasonlítása több véletlen maggal…"):
                try:
                    st.session_state["comparison"] = optimize(root, scenario)
                    st.success("Az összehasonlítás befejeződött. Nyisd meg az Eredmények lapot.")
                except Exception as exc:
                    st.error(f"Az összehasonlítás nem sikerült: {exc}")
    with image_tab:
        uploaded = st.file_uploader("Helyi közlekedési kép", type=["jpg", "jpeg", "png"])
        mock = st.checkbox("Tesztadat használata YOLO helyett", value=False)
        if mock:
            st.warning("Mock mód: a megadott téglalapok tesztadatok, nem AI-felismerések.")
        if uploaded:
            st.image(uploaded, caption="Eredeti kép")
            if st.button("Kép feldolgozása", disabled=not (mock or has_yolo)):
                directory = output_directory(root, "upload")
                path = directory / f"input{Path(uploaded.name).suffix.lower()}"
                path.write_bytes(uploaded.getvalue())
                try:
                    with st.spinner("Kép feldolgozása…"):
                        result_path = detect_file(root, path, mock)
                    st.session_state["detection"] = str(result_path)
                except Exception as exc:
                    st.error(f"A képfeldolgozás nem sikerült: {exc}")
        if "detection" in st.session_state:
            result_path = Path(st.session_state["detection"])
            result = DetectionResult.model_validate_json(result_path.read_text(encoding="utf-8"))
            st.image(str(result_path.parent / "annotated.png"), caption="Objektumok és régiók")
            st.write(
                f"Forrás: {'mock tesztadat' if result.source == 'mock' else 'YOLO-felismerés'}"
            )
            st.caption(
                "Feltöltésnél a fájl időbélyege a feltöltés ideje; nem ismert felvételi idő."
            )
            st.table(
                [
                    {
                        "Kategória": CATEGORY_LABELS[obj.category],
                        "Bizonyosság": obj.confidence,
                        "Irány": obj.direction,
                        "Régió": obj.region,
                        "Téglalap": str(obj.bbox),
                    }
                    for obj in result.objects
                ]
            )
            st.write(f"Összes felismert közlekedő: {len(result.objects)}")
            st.table(
                [
                    {"Irány": d, "Megfigyelt gépjárművek": n}
                    for d, n in result.summary()["by_direction"].items()
                ]
            )
            prior = st.number_input(
                "Feltételezett érkezési intenzitás (jármű/óra/irány)",
                min_value=0.0,
                max_value=5000.0,
                value=450.0,
            )
            estimate, alternatives = estimate_scenarios(result, prior)
            st.warning(estimate["uncertainty"])
            for alternative in alternatives:
                st.download_button(
                    f"{alternative.name} (JSON)",
                    alternative.model_dump_json(indent=2),
                    f"{alternative.id}.json",
                )
            st.download_button(
                "Megfigyelés letöltése (JSON)", result.model_dump_json(indent=2), "detection.json"
            )
            st.download_button(
                "Feltételezések és bizonytalanság letöltése (JSON)",
                json.dumps(estimate, ensure_ascii=False, indent=2),
                "estimate.json",
            )
    with video_tab:
        render_video_tab(root, has_yolo)
    with flow_tab:
        from smarttraffic_ai.dashboard_flow import render_flow_tab

        render_flow_tab(root)
    with scene_tab:
        from smarttraffic_ai.dashboard_scene import render_scene_tab

        render_scene_tab(root, available)
    with result_tab:
        directory = root / app.output_dir
        files = sorted(
            [
                *directory.glob("run-*/result.json"),
                *directory.glob("optimization-*/comparison.json"),
            ],
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if "run" in st.session_state:
            st.subheader("Legutóbbi indított szimuláció")
            show_run(st.session_state["run"])
        if "comparison" in st.session_state:
            st.subheader("Legutóbbi indított összehasonlítás")
            show_comparison(st.session_state["comparison"])
        if files:
            selected_file = st.selectbox(
                "Mentett eredmény", files, format_func=lambda p: p.parent.name
            )
            if st.button("Mentett eredmény megnyitása"):
                try:
                    result = json.loads(selected_file.read_text(encoding="utf-8"))
                    if "best" in result:
                        show_comparison(result, "saved-comparison")
                    else:
                        show_run(result, "saved-run")
                except (OSError, ValueError, KeyError) as exc:
                    st.error(f"Nem olvasható eredmény: {exc}")
        else:
            st.info("Még nincs mentett szimulációs eredmény.")


if __name__ == "__main__":
    main()
