# Telepítés

Ajánlott a 64 bites Python 3.12. A projektet a repository gyökeréből futtasd.

## Új környezet

```bash
uv sync --locked --python 3.12 --extra dev --extra sumo
```

`uv` nélkül, PowerShellben:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev,sumo]"
```

A `vision` extra és a YOLO-súly külön telepítendő: [ai-model.md](ai-model.md). Meglévő, kézzel beállított CPU-s PyTorch mellett a `uv run --no-sync` megőrzi a környezetet; egy új `uv sync` a lock alapján újraszinkronizálja azt.

## SUMO

A `sumo` extra az `eclipse-sumo` csomagot telepíti. Ha már van rendszerszintű SUMO, az extra elhagyható. A keresés sorrendje: `PATH`, `SUMO_HOME/bin`, majd a Python `sumo/bin` csomagkönyvtára.

A külön telepítő a [SUMO hivatalos oldalán](https://sumo.dlr.de/docs/Downloads.php) található. Példa PowerShellben, a saját telepítési útvonaladhoz igazítva:

```powershell
$env:SUMO_HOME = "C:\Program Files (x86)\Eclipse\Sumo"
$env:PATH = "$env:SUMO_HOME\bin;$env:PATH"
sumo --version
netconvert --version
```

A `traci` és a `sumolib` önmagában nem tartalmazza a szimulátort. Célszerű a SUMO és a Python-kliens verzióját egyeztetni.

## Indítás és hibaelhárítás

```bash
uv run --no-sync python -m smarttraffic_ai build-network
uv run --no-sync python -m smarttraffic_ai dashboard
```

| Hiba | Teendő |
|---|---|
| Nem található a Python-modul | Ellenőrizd a munkakönyvtárat és hogy ugyanabba a `.venv` környezetbe telepítettél-e. |
| Nem található `sumo` vagy `netconvert` | Telepítsd a `sumo` extrát vagy javítsd a `PATH`/`SUMO_HOME` értékét. |
| A GUI nem indul | Próbáld `--gui` nélkül; a dashboard headless SUMO-t használ. |
| Nincs YOLO-modell | Ellenőrizd a `config/detection.yaml` fájl `model_path` mezőjét. |
| Tiltott PowerShell-aktiválás | Használd közvetlenül a `.venv/Scripts/python.exe` fájlt vagy a `uv run --no-sync` parancsot. |
| Más mappából nem található a projekt | Add meg a teljes projektutat a `SMARTTRAFFIC_ROOT` környezeti változóban. |

Nincs automatikus `.env`-betöltés. A támogatott telepítési mód a repositoryból történő szerkeszthető telepítés; a wheel önmagában nem tartalmazza a konfigurációt és az adatokat. Más operációs rendszeren a SUMO és a virtuális környezet elérési útja eltérhet; a projektet Windows alatt ellenőriztük.
