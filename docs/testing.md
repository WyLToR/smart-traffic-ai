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

Valódi helyi modellteszt külön, PowerShellből:

```powershell
$env:SMARTTRAFFIC_MODEL_TEST_IMAGE = 'C:\kepek\kozlekedes.jpg'
uv run --no-sync python -m pytest -m vision
Remove-Item Env:SMARTTRAFFIC_MODEL_TEST_IMAGE
```

Ehhez mindhárom profil helyi modellfájlja kell. A próba mindhárommal JPG- és PNG-feldolgozást
ellenőriz, összesen hat esetben. Kép megadása nélkül kimaradnak; a többi teszt nem
helyettesíti a valódi inferencia ellenőrzését.

A `test_profiles.py` a profilhozzárendelést, a cache-t, a hibás/hiányzó modellt, a hivatalos
letöltést és a memóriahibánál történő visszalépést vizsgálja. A memóriahiba szimulált;
a teszt nem meríti ki szándékosan a gép RAM-ját. A felületi és videós tesztek ellenőrzik
a profilváltást, a képkockák megőrzését és a tényleges beállítások exportját.
