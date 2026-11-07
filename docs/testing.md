# Tesztelés

A projekt gyökeréből:

```bash
uv run --no-sync python -m pytest
uv run --no-sync python -m ruff check .
```

Windows alatt a `scripts/check.ps1` mindkettőt és a Python-fájlok fordíthatóságát is ellenőrzi.

Csak az egységtesztekhez:

```bash
uv run --no-sync python -m pytest tests/unit
```

Az integrációs tesztek ideiglenes projektmappában futnak. A SUMO-t igénylő esetek
hiányzó telepítésnél kimaradnak; a videótesztekhez OpenCV és FFmpeg is kell.
Nem töltenek le modelleket vagy videókat, és nem használják a saját `outputs/` eredményeidet.

A tesztek a számlálást, a lámpák állapotváltását, a videóexportot, az élő vizsgálat
mentését és SUMO-átadását, valamint a szimuláció járműmérlegét ellenőrzik.
A helyettesített felismerés és a szintetikus pályák nem mérik a YOLO valós pontosságát.

Saját képpel a felismerés külön próbálható:

```bash
uv run --no-sync python -m smarttraffic_ai detect --input sajat-kep.jpg
```

Élő videót a dashboard **Videóelemzés → Élő forrás** nézetében tesztelj.
