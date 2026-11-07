# Felismerési audit – 2026. november 7.

## A hiba és a javítás

A videós `_objects` közvetlenül a `model.track()` eredményét olvasta. Az Ultralytics
`on_predict_postprocess_end` a detektált dobozlistát az aktivált trackekre szűkíti.
Az alkalmazás így a még ID nélküli felismeréseket sem rajzolta ki. A Busy Intersection
4. képkockáján a confidence-küszöböt elérő 28 találatból 23 követett doboz maradt.
Ezek a számok a hat közlekedési kategóriát és a külön kezelt lámpákat tartalmazzák.

A `detection.predict_frame` most közös inferenciát ad a képhez, videóhoz és élő képhez.
A videós réteg ugyanazt az Ultralytics `BYTETracker` osztályt hívja, a korábbi paraméterekkel,
de megőrzi az ID nélküli találatokat is. Nincs második modellfuttatás képkockánként.
A rajzolás külön jelöli ezeket; a megerősített egyedi számláló továbbra sem veszi át őket.
A javított Busy-képkockán 28 küszöb feletti találat, 23 aktív track és 6 ID nélküli találat
látszik. Az összegek eltérhetnek, mert a követő küszöb alatti egyezést is megtarthat.

Az osztályfüggetlen NMS helyett osztályonkénti elnyomást használunk, hogy például az
egymásra vetülő személy és kerékpár ne nyomja el egymást. A COCO-megfeleltetés a modell
saját névlistájából készül: person=0, bicycle=1, car=2, motorcycle=3, bus=5, truck=7;
a külön lámpaosztály 9. Hiányzó konfigurált kategória most hibajelzést ad.

Nem találtam dupla képméretezést, hibás BGR/RGB-váltást vagy zóna miatti doboztörlést.
A kép eredeti méretben jut a modellhez, a letterbox-kezelést az Ultralytics végzi.
A régiók csak irányt rendelnek. Javult az EXIF szerinti képforgatás, a sérült kép már
modellbetöltés előtt elutasítható, a videó hash-számítása pedig nem olvassa egyszerre
memóriába a teljes fájlt.

A valódi éjszakai videó SUMO-átadásánál a követő simított doboza néha a képhatáron
kívülre ért. Emiatt az `analyze_video` hibás normalizált pozíciót jelzett. A követett
doboz most a képhatárokra korlátozott; a végső 150 képkockás futásban 36 ilyen korrekció volt.
A darabszám a diagnosztikában látható.

## Bemenetek és mérési feltételek

Windows, Python 3.12.10, Ultralytics 8.4.198, PyTorch 2.7.1+cpu. Az NVIDIA RTX A2000
Laptop GPU 4096 MiB memóriával és 573.71-es driverrel elérhető, de a telepített PyTorch
`cuda.is_available()` értéke hamis. A környezet nem változott.

A felhasználó képe a [Shinjuku-közvetítésből](https://www.youtube.com/watch?v=6dp-bvQ7RWo)
származik. A képfájl nem volt helyben hozzáférhető, ezért ugyanebből a forrásból friss
5 másodpercet mentettem: 1280×720, 30 FPS, 150 képkocka. Ez ugyanaz a nézet, másik időpont.
Két további bemenet a már helyben lévő Busy Intersection és Crosswalk Red Car nappali mintája.

A teljes képeken két modellt, három méretet (640/960/1280) és négy küszöböt
(0,10/0,15/0,25/0,35) mértem: 72 konfiguráció–kép páros, két ismétléssel és külön bemelegítéssel.
Kiegészítő mérés: 1280/0,20, nyolc ismétléssel. Alap: CPU, FP32, batch=1, IoU=0,7,
max_det=300. A telepített verzió a YOLO26-ot is NMS-es, one-to-many módban töltötte be;
az opcionális end-to-end módban az IoU-küszöb nem végez elnyomást.

Három képen összesen 11 autó és 5 személy dobozát jelöltem ki vizuális ellenőrzéssel,
korlátozott értékelési régiókban. Ez Codex által készített, közelítő annotáció,
**nem függetlenül, ember által hitelesített referencia**. A régiók az audit közben
lettek kiválasztva; nincs külön, félretett teszthalmaz. Az eredmények ezekre a kis
képrészletekre vonatkoznak, nem a teljes képre vagy minden kamerára.
Az egyeztetés osztályhelyes, egy-egy értelmű, IoU ≥ 0,5.

## Eredmények

Az éjszakai régiómintán, YOLO26n-nel:

| Mutató | 960 / conf 0,25 | 1280 / conf 0,20 |
|---|---:|---:|
| Helyes autó | 8 | 8 |
| Kihagyott autó | 0 | 0 |
| Téves autó | 0 | 0 |
| Helyes személy | 1 | 2 |
| Kihagyott személy | 1 | 0 |
| Téves személy | 0 | 0 |
| Autó precision / recall / F1 | 1 / 1 / 1 | 1 / 1 / 1 |
| Személy precision / recall / F1 | 1 / 0,5 / 0,667 | 1 / 1 / 1 |
| Átlagos ismételt detektálás | 110 ms | 157 ms |
| Folyamat-RSS a hívás után | 446 MiB | 459 MiB |

A modellbetöltés és a bemelegítés nincs az ismételt detektálási időben.
Az RSS pillanatnyi folyamatmemória, nem csúcsérték vagy GPU-memória.
A 1280/0,20 kb. 42%-kal lassabb volt ezen a mérésen. A Crosswalk-minta két jelölt
személyéből viszont csak egyet talált meg megfelelő dobozzal, míg 960/0,25 mellett kettőt.
Mindkét beállítás adott egy további, ugyanahhoz a személyhez tartozó részleges dobozt.
Ezért a nagyobb méret és kisebb küszöb nem lett általános alapbeállítás.

A három ROI-minta együtt, conf=0,25 mellett; az értékek TP / FP / FN:

| Modell, méret | Autó | Személy |
|---|---|---|
| YOLO11n, 640 | 10 / 0 / 1 | 3 / 0 / 2 |
| YOLO11n, 960 | 11 / 1 / 0 | 4 / 1 / 1 |
| YOLO11n, 1280 | 11 / 1 / 0 | 4 / 1 / 1 |
| YOLO26n, 640 | 8 / 1 / 3 | 3 / 0 / 2 |
| YOLO26n, 960 | 11 / 0 / 0 | 4 / 1 / 1 |
| YOLO26n, 1280 | 11 / 0 / 0 | 3 / 1 / 2 |

Ebben a kis mintában a YOLO26n/960 adott kevesebb téves autót; általános modellfölény
nem igazolt. A YOLO26n/960/conf=0,25 alapbeállítás megmaradt. Az éjszakai 1280/0,20
a felület haladó paneljén kipróbálható, de kameránként ellenőrizni kell.

Az eredeti felbontású, átfedő 640-es szeletek és a teljes kép találatainak osztályonkénti
összevonása is lefutott. YOLO26n/960/conf=0,25 esetén 113 ms helyett 666 ms kellett,
a jelölt személyek száma nem javult, egy téves autó hozzáadódott. A CLAHE-kísérletben
a helyesen felismert éjszakai személyek száma 1-ről 0-ra csökkent. Ezek a kísérletek
nem kerültek az alkalmazás alapfeldolgozásába; a slicing a mérőscript külön kapcsolója.

## Videó és SUMO

A 150 képkockás éjszakai videó a régi és javított feldolgozással is 31 megerősített ID-t
adott: 23 autó, 8 személy. A javított futás 99 képkockáján volt ID nélküli felismerés is,
egy képen legfeljebb öt. Ezek eddig nem látszottak. Ez megjelenítési és adatmegőrzési
javítás, nem bizonyított tracking-recall-növekedés. Nincs trackenként annotált referencia,
ezért ID-switch- vagy újraazonosítási pontosságot nem állítok.

Az `observations.jsonl` továbbra is ID-val rendelkező pozíciókat tartalmaz. A külön
`detections.jsonl` megőrzi az ID nélküli felismerést és jelöli a küszöb alatti trackegyezést.
A személyek és kerékpárok nem válnak gépjárművé a SUMO-ban. A javított éjszakai videó
15 kezdeti autójából mind a 15 célba ért a valódi TraCI-próbán. Az N/E-hozzárendelés
ehhez kézi tesztmegfeleltetés volt, nem a helyszín úthálózatának rekonstruálása.
Az integrációs tesztek a többi generálási és futtatási ágat is ellenőrzik.

A végső, diagnosztikás CLI-videófutás 25,34 s volt: modellbetöltés 2,99 s,
dekódolás 0,53 s, detektálás 18,79 s, tracking 0,88 s, annotálás 0,79 s,
encoderbe írás 0,33 s. A fennmaradó idő többek között export és encoderlezárás.
Ez nem valós idejű 30 FPS-es feldolgozás. Ebben a CLI-próbában nem volt előnézeti
callback; a böngésző saját renderidejét nem mértem. A dashboard-callback idejét a
`timings.preview_seconds` külön gyűjti.

A végső helyi ellenőrzés: 161 sikeres teszt, egy alapból kihagyott opcionális modellteszt,
sikeres Ruff és fordíthatósági ellenőrzés. Az opcionális modellteszt a valódi éjszakai
képpel külön bekapcsolva szintén sikeres volt. Commit, push és környezetcsere nem történt.

## Használat és reprodukció

A **Haladó felismerési beállítások** panel a kép-, videó- és élő lapon elérhető.
A részletes diagnosztika megmutatja a modellkimenet, a confidence- és kategóriaszűrés,
a tracking, a megjelenítés és az export darabszámait. A „modellkimenet” már az Ultralytics
belső előszűrése és utófeldolgozása utáni lista, nem a neurális háló teljes tenzora.
Diagnosztikai módban a konfigurált küszöb és 0,10 közül a kisebb értékig vizsgálunk; a normál
eredmény továbbra is csak a kiválasztott közlekedési kategóriákat tartalmazza.

```powershell
uv run --no-sync python scripts/audit_detection.py --input sajat-kep.jpg
uv run --no-sync python scripts/audit_detection.py --input sajat-kep.jpg --reference referencia.json --slicing
```

A referencia JSON kulcsa a képfájl SHA-256-értéke. Egy bejegyzés `regions` listája
`categories` és pixelkoordinátás `bbox` mezőket, az `objects` lista `category` és `bbox`
mezőket tartalmaz. A dobozok eredeti képkoordináták, nem normalizáltak.
A mérések az `outputs/detection-audit/` alatt vannak, Gitből kizárva:

- `baseline.json`, `baseline-shinjuku.json`: kiinduló eredmények;
- `source.json`, `references.json`, `*-reference.jpg`: forrás és vizuális jelölések;
- `comparison/comparison.json`: 72 alapmérés, dobozokkal és időkkel;
- `final-comparison/comparison.json`: ismételt 960/1280 és 0,20/0,25 mérés;
- `slicing/comparison.json`, `preprocessing.json`: elvetett kísérletek;
- `video-comparison.json`, `tracking-after.json`, `final-video.json`, `final-sumo.json`: integráció.

GPU-próbához külön virtuális környezetben CUDA-s PyTorch és hozzá illő torchvision kell,
majd `torch.cuda.is_available()` és rövid valódi inferencia ellenőrzése. A telepítőt a
[PyTorch választójával](https://pytorch.org/get-started/locally/) kell a driverhez választani;
a jelenlegi CPU-környezetet nem cseréltem le. Az NMS- és tracking-viselkedés háttere:
[Ultralytics inferenciafejek](https://docs.ultralytics.com/guides/end2end-detection),
[követés](https://docs.ultralytics.com/modes/track).
