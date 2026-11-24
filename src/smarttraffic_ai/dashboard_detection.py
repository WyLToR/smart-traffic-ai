from pathlib import Path

import streamlit as st

from smarttraffic_ai.config import load_yaml
from smarttraffic_ai.detection import (
    CATEGORY_LABELS,
    MOTOR_VEHICLES,
    TRAFFIC_CATEGORIES,
    DetectionConfig,
)
from smarttraffic_ai.model_store import clear_model_cache, download_model, official_model_url
from smarttraffic_ai.profiles import DETECTION_PROFILES


def detection_settings(root: Path, key: str) -> DetectionConfig:
    defaults = load_yaml(root / "config/detection.yaml", DetectionConfig)
    profile_id = st.selectbox(
        "Feldolgozási profil",
        list(DETECTION_PROFILES),
        index=list(DETECTION_PROFILES).index(defaults.profile_id or "balanced"),
        format_func=lambda name: DETECTION_PROFILES[name].label,
        key=f"{key}-profile",
    )
    profile = DETECTION_PROFILES[profile_id]
    defaults = profile.apply(defaults)
    st.caption(f"{Path(defaults.model_path).name} · {profile.purpose} {profile.resource_estimate}")
    with st.expander("Haladó felismerési beállítások"):
        st.caption(f"Modell: {defaults.model_path}; teljes képes feldolgozás, szeletelés nélkül.")
        size = st.select_slider(
            "Inferenciaméret",
            sorted({640, 960, 1280, defaults.image_size}),
            value=defaults.image_size,
            key=f"{key}-{profile_id}-size",
        )
        confidence = st.slider(
            "Confidence-küszöb",
            0.01,
            0.95,
            max(0.01, min(0.95, defaults.confidence)),
            step=0.01,
            key=f"{key}-{profile_id}-confidence",
        )
        categories = st.multiselect(
            "Kategóriák",
            TRAFFIC_CATEGORIES,
            default=defaults.classes,
            format_func=lambda name: CATEGORY_LABELS[name],
            key=f"{key}-categories",
        )
        diagnostic = st.checkbox(
            "Részletes diagnosztika", value=defaults.diagnostics, key=f"{key}-diagnostics"
        )
        iou = st.slider("NMS IoU-küszöb", 0.1, 1.0, defaults.iou, 0.05, key=f"{key}-iou")
        maximum = st.number_input(
            "Legfeljebb ennyi találat",
            1,
            3000,
            defaults.max_detections,
            key=f"{key}-{profile_id}-max-det",
        )
        st.caption(
            "Az IoU-küszöb az NMS-t használó inferenciánál számít; "
            "az opcionális end-to-end fej nem végez ilyen elnyomást."
        )
        if st.button("Modellcache ürítése", key=f"{key}-clear-models"):
            clear_model_cache()
            st.success(
                "A modellcache kiürült. A futó vizsgálat saját modellje használatban marad."
            )
        st.caption(
            f"Eszköz: {defaults.device}. A beállítások csak erre a feldolgozásra érvényesek. "
            "A személy és a kerékpár külön objektum; összegük nem egyedi közlekedőszám."
        )
    if not (root / defaults.model_path).is_file():
        # Outside the expander: otherwise the disabled start button has no visible reason.
        st.warning(
            f"A kiválasztott modell még nincs letöltve: {Path(defaults.model_path).name}. "
            "Letöltés nélkül a feldolgozás nem indítható."
        )
        st.link_button("Hivatalos modellfájl", official_model_url(Path(defaults.model_path).name))
        if st.button("Modell letöltése", key=f"{key}-download"):
            try:
                with st.spinner("Modell letöltése és ellenőrzése…"):
                    download_model(root, Path(defaults.model_path).name)
                st.rerun()
            except Exception as exc:
                st.error(f"A modell letöltése nem sikerült: {exc}")
    if not categories:
        st.warning("Legalább egy kategóriát válassz; addig a konfigurált kategóriákat használjuk.")
    return DetectionConfig.model_validate(
        {
            **defaults.model_dump(),
            "model_path": defaults.model_path,
            "image_size": size,
            "confidence": confidence,
            "classes": categories or defaults.classes,
            "diagnostics": diagnostic,
            "iou": iou,
            "max_detections": maximum,
        }
    )


def show_processing(config, runtime=None, seconds=None, fps=None):
    if not config:
        return
    if isinstance(config, DetectionConfig):
        config = config.model_dump()
    text = (
        f"Modell: {Path(config['model_path']).name} · "
        f"képméret: {config['image_size']} · conf: {config['confidence']:.2f} · "
        f"eszköz: {config['device']}"
    )
    if seconds is not None:
        text += f" · feldolgozás: {seconds:.2f} s"
    if fps is not None:
        text += f" · feldolgozási FPS: {fps:.2f}"
    st.caption(text)
    for warning in (runtime or {}).get("warnings", []):
        st.warning(warning)


def show_counts(counts, caption=None):
    if caption:
        st.caption(caption)
    vehicles, people, bicycles = st.columns(3)
    vehicles.metric("Járművek", sum(counts.get(name, 0) for name in MOTOR_VEHICLES))
    people.metric("Személyek", counts.get("person", 0))
    bicycles.metric("Kerékpárok", counts.get("bicycle", 0))


def show_diagnostics(data, raw_preview=None):
    if not data:
        return
    with st.expander("Felismerési diagnosztika"):
        if raw_preview is not None and raw_preview.is_file():
            st.image(str(raw_preview), caption="Modellkimenet a részletes szűrés előtt")
        st.json(data)
        st.caption(
            "A modellkimenet már az Ultralytics belső confidence-, NMS- és max_det-lépése "
            "utáni lista. A zónák irányt rendelnek, nem törölnek találatot. "
            "A követő alacsonyabb confidence-ű egyezést is megtarthat meglévő ID-val."
        )
