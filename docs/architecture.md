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
| `scene.py` | Kép/videó megfigyelése, ellenőrzött irányok, kezdeti terhelés és becslési modell |
| `scene_sumo.py` | Négyágú/T-sablon, típusos járműigény, generált fájlcsomag és összehasonlítás |
| `dashboard_scene.py` | Felismerésből generált SUMO-helyzet ellenőrzése és futtatása |
| `flow.py` | Menthető kameraprofil, meglévő követési pozíciókból irányított áthaladási események |
| `flow_validation.py` | Kézi referencia, eseményszintű egyeztetés, pontossági és mintaméret-riport |
| `flow_video.py` | Számlálóvonalak és irányonkénti számlálás a meglévő jelölt videón |
| `dashboard_flow.py` | Kamerabeállítás, forgalommérés és referenciaellenőrzés felülete |

## Adatfolyam

A szintetikus ág: forgatókönyv → explicit járműigény → SUMO → metrikák → összehasonlítás.

A képfeldolgozási ág: helyi kép → detektálás → régió-hozzárendelés → megfigyelés. Az `estimate` ehhez külön megadott érkezési intenzitásból készít forgatókönyveket. A kapcsolat fájlalapú; nincs automatikus élő visszacsatolás. Az adaptív vezérlő jelenleg a SUMO belső soradatait használja.

A rekonstrukciós ág a meglévő detektálási/tracking kimenetet `TrafficScene` modellé alakítja. A hálózatot `netconvert`, a kezdeti és későbbi járműigényt a `scene_sumo` generálja. A futtatás a meglévő `run_simulation` függvényen keresztül történik, a generált fájlcsomaggal. Részletek: [Képi adatokból SUMO](scene-to-sumo.md).

A mért forgalmi ág az `observations.jsonl` fájlt olvassa, új YOLO-futtatás nélkül. A kamerához és forrásvideóhoz kötött `FlowMeasurement` opcionális bemenet a `TrafficScene` modellben. A mért és a Poisson-érkezések nem keverhetők; az előbbiek az eredeti eseményidőt követik. Részletek: [Videós forgalommérés](traffic-flow.md).

Az élő ág: kameraoldal/közvetlen URL → háttérben dekódolt legfrissebb kép → YOLO és ByteTrack → számlálók és lámpaállapot → időzítetten frissülő Streamlit-nézet. Külön szál végzi a dekódolást és az elemzést, közös pufferben egyetlen képkockával. Az élő ág sem vezérel valódi vagy szimulált lámpát. Leállítás, időkorlát vagy megszűnt felületi kapcsolat esetén a munkamenet lezárja a dekódolót.

Minden futás saját könyvtárat és TraCI-kapcsolatot kap. A bemenetek, a konfiguráció és a véletlen mag megmaradnak az eredmény mellett. A létrejött kapcsolat hiba vagy megszakítás esetén is lezárul; részleges fájlok maradhatnak, de sikeres `result.json` csak lezárt futás után készül.

Az `MI` könyvtár SUMO-példái referenciaként szolgáltak. A projekt nem importál belőle és nem tartalmaz onnan átmásolt kódot, modellt vagy adatkészletet.
