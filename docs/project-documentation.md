# SmartTraffic AI – projektdokumentáció

Tantárgy: Mesterséges intelligencia alapjai · Kategória: komplex, AI-t alkalmazó program ·
Állapot: 2026. november 24.

## 1. A projekt

**Probléma.** Egy kereszteződés jelzőlámpa-programjának értékeléséhez forgalmi adat kell,
kézi számlálással viszont ez lassú és drága. A kamerakép elérhető, de abból önmagában nem
derül ki, hogyan viselkedne a csomópont más lámpaprogrammal.

**Cél.** Olyan program, amely közlekedési képen vagy videón mesterséges intelligenciával
felismeri és követi a közlekedőket, a megfigyelésből forgalmi helyzetet állít elő, azt a SUMO
mikroszimulátorban lefuttatja, és összehasonlítja a fix és az adaptív jelzőlámpa-vezérlést.
A lámpát kizárólag szimulációban vezéreljük.

## 2. Technológiák és AI-modellek

| Komponens | Szerep |
|---|---|
| Python 3.12 | A teljes alkalmazás nyelve |
| YOLO11n, YOLO26n, YOLO26l (Ultralytics) | Előtanított, COCO-osztályos objektumdetektorok; három választható profil: Villámgyors, Kiegyensúlyozott, Részletes. **Egymás alternatívái**, nem egymásra épülő lánc. Nem mi tanítottuk őket. |
| ByteTrack (Ultralytics `BYTETracker`) | A képkockánkénti detektálásokból követési azonosítókat (ID) képez |
| OpenCV, FFmpeg | Videódekódolás, rajzolás, jelölt MP4 készítése; a lámpaszín HSV-alapú becslése |
| Eclipse SUMO, `netconvert` | Forgalmi mikroszimuláció, kereszteződés-hálózat generálása |
| TraCI | A szimuláció lépésenkénti vezérlése és mérése Pythonból |
| Streamlit | Magyar nyelvű webes felület |
| Pydantic, pytest, Ruff | Adatvalidáció, automatikus tesztek, statikus ellenőrzés |

Az **AI** a felismerésben és követésben van. Az **adaptív vezérlés saját, szabályalapú
heurisztika** (a zöldidő a várakozó sor hosszától függ, minimum- és maximumkorláttal);
nem tanított modell és nem megerősítéses tanulás. Az optimalizálás véges rácskeresés.
Források és licencek: [sources.md](sources.md).

## 3. A rendszer felépítése

```text
 JPG/PNG/MP4 ──► YOLO (profil) ──► ByteTrack (csak videó)
                                        │
                     detection.json / analysis.json, observations.jsonl
                                        │
            ┌───────────────────────────┼─────────────────────────────┐
            ▼                           ▼                             ▼
   zónák → irányonkénti        időablakos foglaltság        irányított vonalátlépés
   kezdeti terhelés            (videó)                       (forgalommérés, kísérleti)
            └───────────────────────────┼─────────────────────────────┘
                                        ▼
                    TrafficScene (megfigyelés + feltételezések, eredettel)
                                        ▼
         netconvert hálózat + járműigény ──► SUMO / TraCI ──► fix | adaptív vezérlő
                                        ▼
            metrikák (várakozás, sor, célba érés, ütközés) → JSON/CSV, dashboard
```

A modulok a `src/smarttraffic_ai/` alatt vannak: `detection.py`, `video.py` (felismerés,
követés), `flow.py`, `flow_validation.py` (forgalommérés, referenciaértékelés), `scene.py`,
`scene_sumo.py` (forgalmi helyzet és SUMO-csomag), `simulation.py`, `controllers.py`,
`optimization.py` (szimuláció, vezérlés, keresés), `dashboard*.py` (felület), `cli.py`.
Részletek: [architecture.md](architecture.md).

## 4. Saját fejlesztés

A projekt saját kódja a modellek és könyvtárak köré épülő teljes alkalmazás:

- **Kép- és videófeldolgozás integrációja**: közös inferencia képre, videóra és élő képre;
  ID nélküli találatok megőrzése; minden képkocka feldolgozása és ellenőrzése.
- **Modellprofilok és modellcache**: három profil, ellenőrzött hivatalos letöltés, memóriahiba
  esetén kisebb képméretre visszalépés.
- **Követési adatok kezelése**: megerősítési szabály (3 észlelés, 0,5 s), kategóriaszavazás,
  látható idő és időtartam elkülönítése, CSV/JSON export.
- **Irányított forgalomszámlálás**: normalizált számlálóvonalak, hiszterézis, ismételt
  átlépés és ID-váltás kezelése, 10/30/60 s-os ablakok, kézi referenciaértékelő.
- **Forgalmi adatmodell** (`TrafficScene`): minden érték mellett a forrása (mért vagy feltételezett).
- **SUMO-forgatókönyv generálása**: négyágú és T-csomópont, típusos járművek, kezdeti terhelés
  és későbbi érkezések külön kezelve.
- **Fix és adaptív vezérlő**, **rácskereső optimalizáló** azonos igényű, több seedes futásokkal.
- **Dashboard**, **parancssori felület**, **eredményexport**, **automatikus tesztek** (195 db).

Nem saját: a YOLO-modellek és súlyaik, a ByteTrack algoritmus és implementációja, a SUMO,
az OpenCV és a többi könyvtár.

## 5. Tesztelés és mérési eredmények

**Környezet.** Windows 11, Python 3.12.10, Intel Core i7-11850H, 32 GB RAM, CPU-s PyTorch 2.7.1
(az NVIDIA RTX A2000 a telepített PyTorch-csal nem használható), Ultralytics 8.4.198,
SUMO 1.28.0, FFmpeg 8.1. Minden szám 2026. november 24-i futásból származik, ha másképp nem jelöljük.

**Automatikus tesztek.** 195 teszteset: 189 sikeres, 6 kihagyott, 0 hibás, 53 s. A kihagyott
6 a valódi YOLO-inferencia opt-in tesztje; külön, a bemutató képével lefuttatva mind a 6 sikeres
(3 profil × JPG/PNG). Ruff és `compileall` hibátlan. Tiszta, lockból telepített másolatban
(`torch 2.15.0+cpu`), a README szerinti beszerzéssel is 189/6 az eredmény, és a kép → SUMO
bemutató ugyanazokat a számokat adta.

**Videó, három profillal.** Busy Intersection (Pexels), 1280×720, 30 FPS; minden futásban
a feldolgozott, a forrás- és a kimeneti képkockák száma egyezett, az ID-k 1-től indultak.

A teljes, 20 s-os, 600 képkockás videón:

| Profil | Feldolgozás | Sebesség | Megerősített ID |
|---|---:|---:|---:|
| Villámgyors (YOLO11n, 640) | 38,7 s | 15,5 kép/s | 120 |
| Kiegyensúlyozott (YOLO26n, 960) | 56,2 s | 10,7 kép/s | 167 |

A Részletes profilt (YOLO26l, 1280) CPU-s lassúsága miatt **csak a videó első 2 másodpercének
átkódolt részletén (60 képkocka)** mértük: 49,2 s, 1,2 kép/s, 31 megerősített ID. Ez a szám a fenti két sorral
nem vethető össze; ugyanezen a 2 s-os részleten a november 7-i mérés szerint a Villámgyors
5,5 s, a Kiegyensúlyozott 8,0 s alatt végzett ([processing-profiles.md](processing-profiles.md)).

A megerősített ID nem hitelesített közlekedőszám. A Kiegyensúlyozott profil 167 ID-jából 14
„busz”; ezeket egyenként nem ellenőriztük. A COCO-modellekben nincs villamos osztály: a
bemutatóképen a látható villamost a modell buszként, két átfedő dobozzal jelölte.

**Felismerési pontosság, korlátozott mintán.** Három képen kijelölt régiókban 11 autó és
5 gyalogos dobozát egy korábbi auditban (2026. november 7.) mesterséges intelligenciával
segített vizuális jelöléssel rögzítettük; **ez nem független, ember által hitelesített
referencia**. Egyeztetés: osztályhelyes, egy-egy értelmű, IoU ≥ 0,5. A jelenlegi kód a korábbi
táblázatot változatlanul reprodukálta. A profilok beállításával:

| Profil | Jármű TP/FP/FN | Jármű P / R / F1 | Gyalogos TP/FP/FN | Gyalogos P / R / F1 | Idő/kép |
|---|---|---|---|---|---:|
| Villámgyors | 10 / 0 / 1 | 1,00 / 0,91 / 0,95 | 3 / 0 / 2 | 1,00 / 0,60 / 0,75 | 50 ms |
| Kiegyensúlyozott | 11 / 0 / 0 | 1,00 / 1,00 / 1,00 | 4 / 1 / 1 | 0,80 / 0,80 / 0,80 | 74 ms |
| Részletes | 11 / 0 / 0 | 1,00 / 1,00 / 1,00 | 5 / 0 / 0 | 1,00 / 1,00 / 1,00 | 855 ms |

16 objektumból általános modellpontosság nem állítható. Három további képhez (nappali,
éjszakai zsúfolt, gyalogos és jármű) modellből készült annotációs vázlat áll rendelkezésre
emberi javításra; kiértékelés csak az ellenőrzés után értelmes.

**Követés és forgalommérés.** A 20 s-os videón a demonstrációs számlálóvonalak 14 átlépést
mértek (10 s-os ablakokban 3 és 6), 4 eseményt lehetséges ID-váltásként jelöltek. Ezek
helyi áthaladást mérő (`discharge`) vonalak, ezért egyik sem lett SUMO-érkezés. Kézi
referencia nélkül sem a követés, sem az áthaladási események pontosságát nem állítjuk;
a referenciaértékelő célja: legalább két szakasz, 20 esemény, irányonként 10, F1 ≥ 0,90.

**Kép → SUMO és videó → SUMO.** Azonos hálózat, járműigény, seed (42) és 305 s-os horizont,
foglaltsággal súlyozott, 300 jármű/óra/ág feltételezett érkezéssel. A kezdeti járművek
a felismert, zónához rendelt gépjárművek: a képnél a Kiegyensúlyozott profil 9 találata
(7 autó és 2 „busz”, amely valójában egyetlen villamos kettős találata), a videónál a
Villámgyors profillal elemzett első képkocka 3 autója.

| Mutató | Kép: fix | Kép: adaptív | Videó: fix | Videó: adaptív |
|---|---:|---:|---:|---:|
| Tervezett járműigény (ebből kezdeti) | 76 (9) | 76 (9) | 50 (3) | 50 (3) |
| Bejutott | 76 | 76 | 50 | 50 |
| Célba ért | 45 | 41 | 35 | 32 |
| Rendszerben maradt | 31 | 35 | 15 | 18 |
| Átlagos / max. várakozás (s) | 53,6 / 123,0 | 47,7 / 112,5 | 47,5 / 110,1 | 42,0 / 110,5 |
| Átlagos / max. sorhossz (jármű) | 12,9 / 30 | 11,5 / 26 | 7,6 / 18 | 6,7 / 13 |
| Ütközés | 0 | 0 | 0 | 0 |
| Célfüggvény (kisebb jobb) | 90,3 | 86,6 | 76,6 | 74,7 |

Az adaptív vezérlés kevesebbet várakoztatott, de a horizont végéig kevesebb jármű ért célba.

**Lámpaprogram-optimalizálás.** Szintetikus `rush-hour` forgatókönyv (É–D 850, K–Ny 200 jármű/óra),
10 jelölt × 2 seed = 20 futás; seedenként azonos járműigény és hálózat, 0 ütközés.
Célfüggvény: átlagos várakozás + 0,1 × max. várakozás + 60 × befejezetlen arány.

| Program | Pontszám | Átl. várakozás (s) | Célba ért | Befejezetlen |
|---|---:|---:|---:|---:|
| Fix, É–D 35 s / K–Ny 15 s (legjobb a vizsgáltak közül) | 21,7 | 11,4 | 312,5 | 35,0 |
| Adaptív | 34,0 | 20,9 | 303,0 | 44,5 |
| Fix alap, 25 / 25 s | 53,1 | 33,6 | 287,0 | 60,5 |

Az adaptív itt a fix alapnál jobb, de a forgalomhoz illesztett fix programnál rosszabb.
Ez a vizsgált véges jelöltkészlet legjobbja, nem globális optimum.

**Megfigyelt hibák és tanulságok.** A végső ellenőrzés során javítottuk: a foglaltsági
érkezésbecslés a kamerán nem látott ágak részét is a látott ágakra osztotta (kétszeres
terhelés); a Forgalommérés lap új videó után is a régi elemzést mutatta; a hiányzó modellről
szóló figyelmeztetés becsukott panelben volt; a megnyitott mentett eredmény a következő
kattintásra eltűnt. Tanulság, hogy a „működik” és a „helyes mennyiséget mér” két külön
ellenőrzés, és a pontossági állításhoz független referencia kell.

## 6. Korlátok

- A kamera felbontása és a távolság korlátozza a kis objektumok (gyalogos, kerékpár) felismerését.
- Takarás után ugyanaz a közlekedő új ID-t kaphat; az ID-váltást csak gyanúként jelöljük.
- A modellek pontossága kis, nem független mintán mért; a villamos buszként jelenik meg.
- Állóképből sebesség, sorhossz és érkezési intenzitás nem mérhető; ezek feltételezések.
- A SUMO-geometria sablon (sávszám, ághossz, irányok), a kanyarodási arányok kézzel megadottak.
- Gyalogos- és kerékpárforgalmat nem szimulálunk; a lámpaprogram nem a valódi.
- A mintavideókon nincs olyan rögzített nézet, amelyen a bevezető szakaszok mérhetők lennének,
  ezért a mért érkezési mód kísérleti; ember által ellenőrzött referencia nincs.
- Élő források technikailag támogatottak, de hozzáférési és adatvédelmi okból a bemutató és
  az értékelés rögzített, megfelelő felhasználási jogú felvételen történik.

## 7. Csapattagok munkamegosztása

A táblázatot a csapattagok töltik ki. A repository commitjainak száma nem tükrözi a tényleges
munkamegosztást, ezért abból nem következtettünk.

| Csapattag | Elvégzett feladat | Érintett modulok | Egyéni hozzájárulás |
|---|---|---|---|
| | | | |
| | | | |
| | | | |

Mesterségesintelligencia-alapú fejlesztői eszközök használata: a fejlesztés és a dokumentáció
egyes részeihez AI-asszisztenst használtunk (a korábbi audit jelölései is így készültek, lásd
[detection-audit.md](detection-audit.md)). A pontos tájékoztatást a csapat az egyetemi előírás
szerint egészíti ki.

## 8. Összegzés

Elkészült egy működő, tesztelt lánc: kép vagy videó → YOLO-felismerés → követés → forgalmi
helyzet → SUMO-szimuláció → fix és adaptív vezérlés → mérési eredmények, magyar felülettel.
Az AI szerepe a közlekedők felismerése és követése; ezekből lesz a szimuláció kezdeti terhelése,
járműtípus-összetétele és érkezési súlyozása. Az eredmények szerint az adaptív heurisztika
csökkenti a várakozást a fix alapprogramhoz képest, de a forgalomhoz hangolt fix program
csúcsforgalomban jobb lehet, és rövid horizonton a célba érők száma is csökkenhet.

Továbbfejlesztés: emberi referenciaannotációk és rögzített kameranézet a mért érkezési módhoz,
kamerakalibráció és homográfia, valódi lámpaprogram, gyalogosok szimulációja, GPU-s futtatás.

## 9. Források

A felhasznált szoftverek, modellek, adatforrások és felhasználási feltételeik: [sources.md](sources.md).
