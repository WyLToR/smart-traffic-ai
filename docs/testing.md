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

Valódi helyi modellteszt külön, PowerShellből, a mellékelt bemutatóképpel:

```powershell
$env:SMARTTRAFFIC_MODEL_TEST_IMAGE = (Resolve-Path 'data/samples/demo/busy_intersection_frame_008.jpg').Path
uv run --no-sync python -m pytest -m vision -ra
Remove-Item Env:SMARTTRAFFIC_MODEL_TEST_IMAGE
```

Ehhez mindhárom profil helyi modellfájlja kell. A próba mindhárommal JPG- és PNG-feldolgozást
ellenőriz, összesen hat esetben. Kép megadása nélkül kimaradnak; a többi teszt nem
helyettesíti a valódi inferencia ellenőrzését.

## Legutóbbi eredmény (2026. november 24.)

Windows 11, Python 3.12.10, CPU-s PyTorch 2.7.1, Ultralytics 8.4.198, SUMO 1.28.0:

| Ellenőrzés | Eredmény |
|---|---|
| `pytest -ra` | 195 teszt: 189 sikeres, 6 kihagyott, 0 hibás, 53 s |
| Kihagyás oka | a 6 valódi YOLO-teszt opt-in, `SMARTTRAFFIC_MODEL_TEST_IMAGE` nélkül nem fut |
| `pytest -m vision` a bemutatóképpel | 6 sikeres (3 profil × JPG/PNG) |
| `ruff check .`, `compileall -q src`, `scripts/check.ps1` | hibátlan |
| A beadási fájllistából készült tiszta másolat, `uv sync --locked ... --extra vision` (torch 2.15.0+cpu) | 189 sikeres, 6 kihagyott; a vision-tesztek 6/6; Ruff és compileall hibátlan; `download-model --profile fast` valódi letöltéssel; a demóminta beszerzése egyező SHA-256-tal |
| Tiszta másolat `vision` nélkül | a kép-, videó- és élő tesztek importhiány miatt kimaradnak |

A YOLO, a videófeldolgozás és a SUMO valódi futtatásának eredményei:
[projektdokumentáció](project-documentation.md#5-tesztelés-és-mérési-eredmények).

A `test_profiles.py` a profilhozzárendelést, a cache-t, a hibás/hiányzó modellt, a hivatalos
letöltést és a memóriahibánál történő visszalépést vizsgálja. A memóriahiba szimulált;
a teszt nem meríti ki szándékosan a gép RAM-ját. A felületi és videós tesztek ellenőrzik
a profilváltást, a képkockák megőrzését és a tényleges beállítások exportját.
