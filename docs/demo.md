# Bemutatási útmutató (5–8 perc)

A bemutató internet és élő kamera nélkül fut. Előfeltétel: a [README](../README.md) szerinti
telepítés, mindhárom modell letöltve (`download-model`), és egy próbafuttatás a bemutató előtt.
A bemenetek a `data/samples/demo/` mappába kerülnek; a Pexels-feltételek miatt nincsenek a
repositoryban, beszerzésük SHA-256-ellenőrzéssel: [data/README.md](../data/README.md). Ezt a bemutató előtt,
internetkapcsolattal kell elvégezni.

Indítás: `uv run --no-sync python -m smarttraffic_ai dashboard`, majd `http://localhost:8501`.

A lenti számok a 2026. november 24-i ellenőrző futásokból valók (Windows, Intel Core i7-11850H,
CPU-s PyTorch, más terhelés nélkül). Más gépen az idők eltérnek; a darabszámok azonos modellel
és beállítással megegyeznek.

## 1. A projekt (kb. 30 s)

Közlekedési képből vagy videóból YOLO-modellel felismerjük és követjük a közlekedőket, ebből
SUMO-forgatókönyvet készítünk, és összehasonlítjuk a fix és az adaptív jelzőlámpa-vezérlést.
Az AI a felismerésben van; az adaptív vezérlés saját, szabályalapú heurisztika.

## 2. Objektumfelismerés (kb. 1 perc)

**Képfeldolgozás** lap → `data/samples/demo/busy_intersection_frame_008.jpg` feltöltése →
**Kép feldolgozása** (Kiegyensúlyozott profil). Várható: 9 gépjármű-találat a háttérúton (7 autó és 2 „busz”, ez utóbbi valójában egyetlen
villamos két átfedő doboza: jó példa a modell korlátjára)
és 11 gyalogos, jelölt kép és táblázat.

A profilok rövid összevetése (előre lefuttatott mérés, három referenciakép átlaga):

| Profil | Modell | Képenkénti idő | ROI-minta: jármű TP/FP/FN | ROI-minta: gyalogos TP/FP/FN |
|---|---|---:|---|---|
| Villámgyors | YOLO11n, 640 | 50 ms | 10 / 0 / 1 | 3 / 0 / 2 |
| Kiegyensúlyozott | YOLO26n, 960 | 74 ms | 11 / 0 / 0 | 4 / 1 / 1 |
| Részletes | YOLO26l, 1280 | 855 ms | 11 / 0 / 0 | 5 / 0 / 0 |

Fontos kimondani: a referencia mindössze 11 autó és 5 gyalogos, nem független emberi annotáció.

## 3. Videóelemzés (kb. 1,5 perc)

**Videóelemzés → Mintavideó → Bemutató – Busy Intersection**, **Villámgyors** profil →
**Videó feldolgozása**. A 600 képkocka kb. 40 s alatt fut le; közben látszik az előnézet.

Mutasd meg: a zöld doboz megerősített ID, a narancs még nem megerősített, a világoskék
ID nélküli találat; a fejléc a pillanatnyi és az összesített számot külön írja ki.
Várható: 120 megerősített ID (53 autó, 2 busz, 3 teherautó, 1 kerékpár, 61 gyalogos).
Ez követett azonosítók száma, nem hitelesített egyedi közlekedőszám.

A Részletes profilt élőben ne futtasd: a 2 s-os részleten 1,2 képkocka/s volt, ebből arányosítva
a 20 s-os videó becsülten kb. 8 perc (nem mértük).
Helyette a korábbi futás eredménye mutatható meg.

## 4. Forgalommérés (kb. 1 perc)

**Forgalommérés** lap → az előbbi elemzés → a felajánlott `busy-intersection` kamerabeállítás →
**Forgalommérés indítása**. Várható: 14 vonalátlépés (jobb vonal 9 befelé, bal vonal 5 kifelé),
10 s-os ablakokban 3 és 6 esemény.

Kimondandó: ezek `discharge` (helyi áthaladás) vonalak, így a mérésből nem lesz SUMO-érkezés.
Ember által ellenőrzött referencia nincs; a forgalommérés kísérleti, nem hitelesített funkció.

## 5. SUMO (kb. 1,5 perc)

**Kép/videó → SUMO → Legutóbbi videó**. A mintához tartozó zónák (bal útszakasz N, jobb E)
betöltődnek. Érkezés: **Foglaltsággal súlyozott intenzitási feltételezés**, alapérték 300 jármű/óra/ág,
szimulált idő 300 s → ellenőrzés bepipálása → **SUMO-forgatókönyv létrehozása**.

Opcionálisan **SUMO-GUI megnyitása** + **Generált forgalom indítása** – a járművek mozgása és a lámpa
fázisai láthatók; a futás végén az ablak bezárul.

## 6. Fix és adaptív összehasonlítás (kb. 1 perc)

**Fix és adaptív összehasonlítása**. Azonos hálózat, járműigény, seed (42) és időhorizont (305 s).
Az ellenőrző futás eredménye (a dashboard a fenti beállításokkal ugyanezt adja):

| Mutató | Fix | Adaptív |
|---|---:|---:|
| Tervezett járműigény | 50 | 50 |
| Bejutott | 50 | 50 |
| Célba ért | 35 | 32 |
| Átlagos várakozás (s) | 47,5 | 42,0 |
| Átlagos sorhossz (jármű) | 7,6 | 6,7 |
| Ütközés | 0 | 0 |

Kimondandó: az adaptív kevesebbet várakoztat, de a horizont végéig kevesebb jármű ér célba;
egyik sem jobb minden szempontból.

Szintetikus csúcsforgalmon (`rush-hour`, 10 jelölt × 2 seed) a legjobb vizsgált program
a fix 35/15 s-os zöldidő volt (pontszám 21,7), az adaptív 34,0, a fix alap 25/25 s 53,1.
Ezt az **Eredmények** lapon a mentett `optimization-*` összehasonlítás mutatja.

## 7. Eredmények és korlátok (kb. 1 perc)

- A felismerés kis, nem független mintán mért; általános pontosságot nem állítunk.
- A villamost a COCO-modellek buszként jelölik; takarás után ugyanaz a közlekedő új ID-t kaphat.
- A SUMO-geometria sablon, a kanyarodási arányok és érkezési intenzitások feltételezések.
- Gyalogos- és kerékpárforgalom nincs a szimulációban; a lámpaprogram nem a valódi.
- Élő kameraforrás technikailag támogatott, de a bemutató és az értékelés rögzített felvételen fut.

## Ha valami nem működik

- Letiltott feldolgozás gomb: hiányzó modell, a lap tetején megjelenő figyelmeztetés szerint töltsd le.
- „A SUMO-integráció nem érhető el”: `sumo` extra vagy `SUMO_HOME`/PATH, lásd [installation.md](installation.md).
- Tartalék: a teljes lánc parancssorból is lefut:
  `uv run --no-sync python -m smarttraffic_ai reconstruct --input data/samples/demo/busy_intersection.mp4 --settings config/scene-busy-intersection.yaml --compare`
  (alapprofillal; a kimenet a futás könyvtárát írja ki).
