# Architektúra

A CLI és a Streamlit dashboard ugyanazokat a függvényeket hívja.

| Modul | Feladat |
|---|---|
| `config.py` | Pydantic-sémák és YAML-betöltés |
| `traffic.py` | Reprodukálható járműigény és route XML |
| `controllers.py` | Fix/adaptív állapotgép, szimulátorhívások nélkül |
| `simulation.py` | Hálózatgenerálás, TraCI-kapcsolat, mérés és export |
| `optimization.py` | Jelöltek futtatása és rangsorolása; tesztben helyettesíthető futtató |
| `detection.py` | YOLO és mock detektor, régiók, összesítés, jelölt kép |
| `video.py` | MP4, ByteTrack-azonosítók, láthatósági idők, számlálás és jelölt videó |
| `traffic_lights.py` | Lámpaterületek, színállapot, típus-hozzárendelés és állapotidők |
| `dashboard_video.py` | Videófeltöltés, feldolgozási előnézet, táblázatok és letöltések |
| `live.py` | Élő URL feloldása, HLS-dekódolás, legfrissebb kép átadása és elemzési munkamenet |
| `youtube_source.py` | YouTube-link normalizálása és az aktuális H.264 HLS-forrás feloldása |
| `dashboard_live.py` | Élő forrás indítása/leállítása, frissülő jelölt kép és számlálók |
| `estimation.py` | Megfigyelési összesítés és feltételezett intenzitású forgatókönyvek |

## Adatfolyam

A szintetikus ág: forgatókönyv → explicit járműigény → SUMO → metrikák → összehasonlítás.

A képfeldolgozási ág: helyi kép → detektálás → régió-hozzárendelés → megfigyelés. Az `estimate` ehhez külön megadott érkezési intenzitásból készít forgatókönyveket. A kapcsolat fájlalapú; nincs automatikus élő visszacsatolás. Az adaptív vezérlő jelenleg a SUMO belső soradatait használja.

Az élő ág: kameraoldal/közvetlen URL → háttérben dekódolt legfrissebb kép → YOLO és ByteTrack → számlálók és lámpaállapot → időzítetten frissülő Streamlit-nézet. Külön szál végzi a dekódolást és az elemzést, közös pufferben egyetlen képkockával. Az élő ág sem vezérel valódi vagy szimulált lámpát. Leállítás, időkorlát vagy megszűnt felületi kapcsolat esetén a munkamenet lezárja a dekódolót.

Minden futás saját könyvtárat és TraCI-kapcsolatot kap. A bemenetek, a konfiguráció és a véletlen mag megmaradnak az eredmény mellett. A létrejött kapcsolat hiba vagy megszakítás esetén is lezárul; részleges fájlok maradhatnak, de sikeres `result.json` csak lezárt futás után készül.

Az `MI` könyvtár SUMO-példái referenciaként szolgáltak. A projekt nem importál belőle és nem tartalmaz onnan átmásolt kódot, modellt vagy adatkészletet.
