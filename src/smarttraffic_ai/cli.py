from __future__ import annotations

import argparse
import json
import subprocess
import sys

from traci.exceptions import FatalTraCIError, TraCIException

from smarttraffic_ai.config import load_scenario, project_root
from smarttraffic_ai.optimization import optimize
from smarttraffic_ai.simulation import build_network, run_simulation


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="SmartTraffic AI – szimulált forgalom elemzése")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("build-network", help="Négyirányú SUMO-hálózat generálása")
    for name in ("demo", "simulate", "optimize"):
        command = sub.add_parser(
            name,
            help={
                "demo": "SUMO-bemutató",
                "simulate": "Szimuláció",
                "optimize": "Lámpaprogramok összehasonlítása",
            }[name],
        )
        command.add_argument("--scenario", default="balanced", help="Azonosító vagy YAML-fájl")
        command.add_argument("--seed", type=int, help="Véletlen mag; optimalizálásnál egyetlen mag")
        if name != "optimize":
            command.add_argument("--controller", choices=["fixed", "adaptive"], default="fixed")
            command.add_argument("--gui", action="store_true", help="SUMO-GUI megnyitása")
    command = sub.add_parser("detect", help="Helyi JPG/PNG feldolgozása")
    command.add_argument("--input", required=True, help="Kép elérési útja")
    command.add_argument("--mock", action="store_true", help="Kifejezetten szintetikus tesztadat")
    command.add_argument("--timestamp", help="A felvétel ISO 8601 időbélyege, időzónával")
    command = sub.add_parser("analyze-video", help="MP4 követése, számlálás és láthatósági idők")
    command.add_argument("--input", required=True, help="MP4-videó elérési útja")
    command = sub.add_parser("estimate", help="Detektálási JSON-ból feltételezett forgatókönyvek")
    command.add_argument("--input", required=True)
    command.add_argument(
        "--prior-rate", type=float, default=450, help="Feltételezett jármű/óra/irány"
    )
    command = sub.add_parser("reconstruct", help="Kép/videó felismeréséből saját SUMO-forgatókönyv")
    command.add_argument("--input", required=True, help="JPG/PNG/MP4 vagy felismerési JSON")
    command.add_argument("--settings", required=True, help="Ellenőrzött SceneSettings YAML/JSON")
    command.add_argument("--run", action="store_true", help="Generálás után TraCI-futtatás")
    command.add_argument("--gui", action="store_true")
    command.add_argument(
        "--compare", action="store_true", help="Azonos igény fix és adaptív vezérléssel"
    )
    command.add_argument("--controller", choices=["fixed", "adaptive"], default="fixed")
    for name in ("scene-run", "scene-compare"):
        command = sub.add_parser(name, help="Generált forgalmi helyzet futtatása/összehasonlítása")
        command.add_argument("--scene", required=True, help="A generált scene-* könyvtár")
        if name == "scene-run":
            command.add_argument("--controller", choices=["fixed", "adaptive"], default="fixed")
            command.add_argument("--gui", action="store_true")
    command = sub.add_parser(
        "measure-flow", help="Követési pozíciókból irányított vonalátlépések mérése"
    )
    command.add_argument("--input", required=True, help="MP4 vagy a meglévő analysis.json")
    command.add_argument("--camera", required=True, help="Mentett CameraProfile JSON")
    command.add_argument("--annotate", action="store_true", help="Jelölt számlálási videó mentése")
    command = sub.add_parser(
        "evaluate-flow", help="Forgalommérés összevetése kézi referenciaeseményekkel"
    )
    command.add_argument("--measurement", required=True)
    command.add_argument("--reference", required=True)
    command.add_argument(
        "--tolerance", type=float, default=1.0, help="Egyeztetési időtolerancia (s)"
    )
    sub.add_parser("dashboard", help="Magyar Streamlit-felület indítása")
    args = parser.parse_args(argv)
    try:
        root = project_root()
        if args.command == "build-network":
            print(f"Elkészült: {build_network(root)}")
        elif args.command in {"simulate", "demo", "optimize"}:
            scenario = load_scenario(root, args.scenario)
            if args.seed is not None and not 0 <= args.seed <= 2147483647:
                raise ValueError("A véletlen mag 0 és 2147483647 közé essen.")
            if args.command == "optimize":
                from smarttraffic_ai.config import SearchConfig, load_yaml

                settings = load_yaml(root / "config/optimization.yaml", SearchConfig)
                if args.seed is not None:
                    settings.seeds = [args.seed]
                report = optimize(root, scenario, settings)
                print("Legjobb a vizsgált jelöltek közül:")
                print(json.dumps(report["best"], ensure_ascii=False, indent=2))
                print(f"Eredmények: {report['directory']}")
            else:
                result = run_simulation(
                    root, scenario, args.controller, seed=args.seed, gui=args.gui
                )
                print(json.dumps(result["metrics"], ensure_ascii=False, indent=2))
                print(f"Eredmények: {result['directory']}")
        elif args.command == "detect":
            from pathlib import Path

            from smarttraffic_ai.detection import detect_file

            print(detect_file(root, Path(args.input), args.mock, args.timestamp))
        elif args.command == "analyze-video":
            from pathlib import Path

            from smarttraffic_ai.video import process_video

            result = process_video(root, Path(args.input))
            print(f"Összes követett ID: {result['summary']['total_unique']}")
            print(f"Eredmények: {result['directory']}")
        elif args.command == "estimate":
            from pathlib import Path

            from smarttraffic_ai.detection import DetectionResult
            from smarttraffic_ai.estimation import estimate_scenarios
            from smarttraffic_ai.simulation import output_directory, save_json

            observation = DetectionResult.model_validate_json(
                Path(args.input).read_text(encoding="utf-8")
            )
            directory = output_directory(root, "estimate")
            estimate, scenarios = estimate_scenarios(observation, args.prior_rate)
            save_json(directory / "estimate.json", estimate)
            for scenario in scenarios:
                save_json(directory / f"{scenario.id}.json", scenario.model_dump())
                # JSON is also valid YAML and accepted by the scenario loader.
            print(f"Becslések és alternatív forgatókönyvek: {directory}")
        elif args.command in {"measure-flow", "evaluate-flow"}:
            from pathlib import Path

            from smarttraffic_ai.flow import CameraProfile, FlowMeasurement, measure_flow
            from smarttraffic_ai.simulation import save_json

            if args.command == "measure-flow":
                path = Path(args.input)
                if path.suffix.lower() == ".mp4":
                    from smarttraffic_ai.video import process_video

                    path = Path(process_video(root, path)["directory"]) / "analysis.json"
                camera = CameraProfile.model_validate_json(
                    Path(args.camera).read_text(encoding="utf-8")
                )
                measurement = measure_flow(root, path, camera)
                if args.annotate:
                    from smarttraffic_ai.flow_video import render_flow_video

                    render_flow_video(path, measurement)
                print(f"Forgalommérés és exportok: {measurement}")
            else:
                from smarttraffic_ai.flow_validation import ManualReference, evaluate_flow

                measurement = FlowMeasurement.model_validate_json(
                    Path(args.measurement).read_text(encoding="utf-8")
                )
                reference = ManualReference.model_validate_json(
                    Path(args.reference).read_text(encoding="utf-8")
                )
                report = evaluate_flow(measurement, reference, args.tolerance)
                path = Path(args.measurement).parent / "validation.json"
                save_json(path, report.model_dump(mode="json"))
                print(report.model_dump_json(indent=2))
                print(f"Referenciaértékelés: {path}")
        elif args.command in {"reconstruct", "scene-run", "scene-compare"}:
            from pathlib import Path

            from smarttraffic_ai.scene_sumo import compare_scene, run_scene

            if args.command == "reconstruct":
                from smarttraffic_ai.config import load_yaml
                from smarttraffic_ai.detection import DetectionResult, detect_file
                from smarttraffic_ai.scene import SceneSettings, analyze_image, analyze_video
                from smarttraffic_ai.scene_sumo import generate_scene

                if args.gui and not args.run:
                    raise ValueError("A --gui kapcsolóhoz a --run kapcsolót is add meg.")
                path = Path(args.input)
                if path.suffix.lower() in {".jpg", ".jpeg", ".png"}:
                    path = detect_file(root, path)
                elif path.suffix.lower() == ".mp4":
                    from smarttraffic_ai.video import process_video

                    path = Path(process_video(root, path)["directory"]) / "analysis.json"
                data = json.loads(path.read_text(encoding="utf-8"))
                settings = load_yaml(Path(args.settings), SceneSettings)
                scene = (
                    analyze_video(path, settings)
                    if "tracks" in data
                    else analyze_image(DetectionResult.model_validate(data), settings)
                )
                directory = generate_scene(root, scene)
                print(f"Generált SUMO-forgatókönyv: {directory}")
                if args.run:
                    result = run_scene(root, directory, args.controller, args.gui)
                    print(json.dumps(result["metrics"], ensure_ascii=False, indent=2))
                    print(f"Mérés: {result['directory']}")
                if args.compare:
                    print(f"Összehasonlítás: {compare_scene(root, directory)['directory']}")
            elif args.command == "scene-run":
                result = run_scene(root, Path(args.scene), args.controller, args.gui)
                print(json.dumps(result["metrics"], ensure_ascii=False, indent=2))
                print(f"Mérés: {result['directory']}")
            else:
                print(f"Összehasonlítás: {compare_scene(root, Path(args.scene))['directory']}")
        else:
            path = root / "src/smarttraffic_ai/dashboard.py"
            return subprocess.call([sys.executable, "-m", "streamlit", "run", str(path)])
        return 0
    except KeyboardInterrupt:
        print("A futást a felhasználó megszakította.", file=sys.stderr)
        return 130
    except (
        OSError,
        ValueError,
        RuntimeError,
        ImportError,
        subprocess.SubprocessError,
        FatalTraCIError,
        TraCIException,
    ) as exc:
        print(f"Hiba: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
