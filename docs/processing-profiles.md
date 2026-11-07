# Feldolgozási profilok

Képnél, MP4-nél és élő forrásnál a **Feldolgozási profil** választó ugyanazt a közös
YOLO-inferenciát állítja be. A Kiegyensúlyozott az alapértelmezett.

| Profil | Modell | Méret | Confidence | max_det |
|---|---|---:|---:|---:|
| Villámgyors (`fast`) | YOLO11n | 640 | 0,25 | 300 |
| Kiegyensúlyozott (`balanced`) | YOLO26n | 960 | 0,20 | 500 |
| Részletes (`detailed`) | YOLO26l | 1280 | 0,15 | 1000 |

A modell a profilhoz kötött; a képméret, küszöb és kategóriák a haladó panelen módosíthatók.
A választás nem írja át a YAML-t. A végén a modell, tényleges méret, confidence, eszköz,
idő és videónál a feldolgozási FPS is látszik. A videó összesített számai megerősített
tracking-ID-ket jelentenek, nem vonalátlépéseket vagy igazolt egyedi közlekedőket.

## Modellfájlok és cache

A hiányzó modellnél a feldolgozás letiltott, letöltési gomb és hivatalos link jelenik meg.
Parancssorból:

```bash
uv run --no-sync python -m smarttraffic_ai download-model --profile detailed
uv run --no-sync python -m smarttraffic_ai detect --input kep.png --profile balanced
uv run --no-sync python -m smarttraffic_ai analyze-video --input video.mp4 --profile fast
```

A letöltés a hivatalos `ultralytics/assets` kiadásból történik: YOLO11n esetén v8.3.0,
YOLO26n/l esetén v8.4.0. Az ideiglenes fájlt csak sikeres modellbetöltés és osztályellenőrzés
után nevezzük át. A már létező fájlt nem töltjük le újra. Hibás meglévő fájlnál hibaüzenet
jelenik meg; cseréhez előbb nevezd át a hibás példányt. A súlyok és ellenőrzőösszegek Gitből kizártak.

A `model_store.py` folyamatonként legfeljebb két modellpéldányt tart a cache-ben.
A kulcs a fájl, annak mérete/módosítási ideje, az eszköz és a számábrázolás. A modell
közös prediktorát zárolás védi; a ByteTrack minden vizsgálathoz külön tartozik.
A **Modellcache ürítése** elengedi a cache hivatkozásait. A futó vizsgálatok saját
modellhivatkozásai érvényesek maradnak. A nagy modell csak kiválasztás utáni feldolgozáskor töltődik be.

## Memóriahiba és hardver

A Részletes profil memóriahibánál ugyanazt a képkockát 1280 → 960 → 640 méreten próbálja
újra. A követő csak sikeres inferencia után lép tovább, ezért a visszalépés nem hagy ki
képkockát és nem lépteti kétszer a ByteTracket. Az eredmény figyelmeztetést ad, és a
tényleges méretet exportálja; ha 640 sem fér el, kisebb modell választását kéri.
Más típusú feldolgozási hiba nem indít ilyen visszalépést.

A helyi gépen CPU-s PyTorch fut. A 4 GB-os RTX A2000 a jelenlegi csomaggal nem használható
CUDA-inferenciára; nem történt környezetcsere. A GPU külön, kézzel beállított CUDA-s
környezetben és `device` konfigurációval használható. A 4 GB-os GPU-n a Részletes profil
memóriaigényét nem mértük. A CPU-s futásokban nem történt tényleges memóriahiba;
a visszalépési ág célzott, szimulált hibával tesztelt.

Nincs automatikus MP4-képkockakihagyás, slicing vagy SAHI. A korábbi szeletelési kísérlet
nem adott elég előnyt a költségéhez képest; az auditáló scriptben továbbra is külön kapcsolható.

## Helyi mérések – 2026. november 7.

Windows, Python 3.12.10, Ultralytics 8.4.198, PyTorch 2.7.1+cpu, i7-11850H, 32 GB RAM.
Mindhárom modell betöltése és tényleges inferenciája sikeres. A YOLO26l fájlja 53 211 173 bájt.
A három profil eltérő méretet és küszöböt használ: ez profil-összehasonlítás, nem azonos
paraméterű, kizárólag modellarchitektúrát összevető kísérlet.

Három 1280×720-as jelenet: a meglévő Shinjuku éjszakai kép, Busy Intersection és Crosswalk Red Car.
A képek ugyanazok minden profilnál. Az első hívás után képenként három ismétlés történt.

| Profil | Súlybetöltés | Első kép hívása | Bemelegedett detektálás átlaga | Teljes képfeldolgozás, cache-ből | Folyamat-RSS |
|---|---:|---:|---:|---:|---:|
| Villámgyors | 193 ms | 2594 ms | 80 ms | 290 ms | 385 MiB |
| Kiegyensúlyozott | 111 ms | 337 ms | 109 ms | 307 ms | 443 MiB |
| Részletes | 204 ms | 1471 ms | 1084 ms | 1298 ms | 893 MiB |

Az elsőként futtatott Villámgyors profil első hívása a közös CPU/backend-bemelegítés
költségét is viseli. Ezt nem szabad az ismételt inferencia idejével összehasonlítani.
A teljes képfeldolgozás beolvasást, annotálást és exportot is tartalmaz.
Az RSS folyamatmemória a hívás után, nem izolált modellmemória, csúcsérték vagy VRAM.

Mindkét videó 2 másodperc, 30 FPS és 60 képkocka. Minden profil mind a 60-at feldolgozta.

| Profil | Éjszakai videó teljes ideje / FPS | Zsúfolt nappali videó ideje / FPS |
|---|---|---|
| Villámgyors | 9,87 s / 6,08 | 5,49 s / 10,93 |
| Kiegyensúlyozott | 7,87 s / 7,63 | 8,04 s / 7,46 |
| Részletes | 68,05 s / 0,88 | 68,68 s / 0,87 |

Az első éjszakai futás a Villámgyorsnál a Python/Ultralytics inicializálást is tartalmazza;
emiatt annak teljes ideje nagyobb lett a Kiegyensúlyozotténál. Bemelegedett inferenciában
és a második videón a Villámgyors volt gyorsabb. Ezek CLI-mérések, böngésző-előnézet nélkül.
A feldolgozási FPS nem a forrás FPS-e vagy a kimeneti videó lejátszási sebessége.

## Felismerés és SUMO

A korábbi audit 11 autót és 5 személyt tartalmazó, korlátozott ROI-mintáján:

| Profil | Autó TP / FP / FN | Személy TP / FP / FN |
|---|---|---|
| Villámgyors | 10 / 0 / 1 | 3 / 0 / 2 |
| Kiegyensúlyozott | 11 / 0 / 0 | 4 / 1 / 1 |
| Részletes | 11 / 0 / 0 | 5 / 0 / 0 |

Az egyeztetés IoU ≥ 0,5 és osztályhelyes. A jelölések Codex vizuális ellenőrzésével készültek,
nem független emberi referenciaadatok, és nem fedik le a teljes képeket. Ezen a kis mintán
a Részletes volt jobb, általános pontossági fölény nem igazolt. A több teljes képes találat
önmagában nem pontossági mutató. A Kiegyensúlyozott a jobb időigény miatt maradt az alap.

Az éjszakai videó → TrafficScene → valódi SUMO/TraCI lánc mindhárom profillal sikeres:
14/14, 15/15 és 23/23 kezdeti jármű célba ért. A teszt N/E-hozzárendelése kézi megfeleltetés,
nem helyszíni úthálózat-rekonstrukció. A gyalogosok és kerékpárok nem kerültek gépjárműként a SUMO-ba.
Külön valódi próba igazolta, hogy a cache közös modellje mellett két vizsgálat külön
ByteTracket és új ID-állapotot kap. A modellekhez ugyanaz a detektálási séma tartozik.

## Ellenőrzés és eredményfájlok

Az `analysis.json` és `detection.json` `config` mezője a tényleges modellbeállítást tárolja.
A `runtime` külön jelzi a cache-találatot, betöltést, első és további inferenciát,
kért/tényleges méretet és a visszalépéseket. Minden futás külön kimeneti mappát kap.

Ismételhető képmérés:

```bash
uv run --no-sync python scripts/audit_detection.py --input kep.jpg --profiles fast balanced detailed
```

A mostani eredmények Gitből kizárva az `outputs/profiles-validation/` alatt találhatók:
`images.json`, `files.json`, `videos.json`, `cache-validation.json`, a két videóminta és
a `runtime/outputs/` alatti jelölt eredmények/SUMO-futtatások. A referencia a korábbi
`outputs/detection-audit/references.json`.

Érintett kód: `profiles.py`, `model_store.py`, `detection.py`, `video.py`, `live.py`, a meglévő
dashboard és közös beállítópanel, valamint a CLI. Nem került be új függőség vagy SUMO-futtató.
Hosszú videós terheléspróba és független, nagyobb pontossági adatkészlet nincs a mérésben.
