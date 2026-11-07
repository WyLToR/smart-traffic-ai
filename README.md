# SmartTraffic AI

Forgalomelemző és jelzőlámpa-vezérlést összehasonlító egyetemi projekt Python, SUMO és YOLO használatával. A lámpavezérlés kizárólag szimulációban működik.

## Telepítés

A projekt gyökerében, telepített `uv` mellett:

```bash
uv sync --locked --python 3.12 --extra dev --extra sumo
```

Ez telepíti a Python-függőségeket és a SUMO-t. Meglévő rendszerszintű SUMO esetén a `sumo` extra elhagyható. A képfeldolgozás külön telepítést és helyi modellfájlt igényel: [YOLO beállítása](docs/ai-model.md).

Már beállított környezetben a lenti `--no-sync` parancsokat használd. Így a `uv` nem cseréli le a külön telepített CPU-s PyTorchot. Részletes telepítés és hibaelhárítás: [installation.md](docs/installation.md).

## Futtatás

```bash
# Kereszteződés és a három mintaforgatókönyv generálása
uv run --no-sync python -m smarttraffic_ai build-network

# Bemutató SUMO-GUI-val
uv run --no-sync python -m smarttraffic_ai demo --scenario balanced --gui

# Ugyanaz a csúcsforgalom kétféle vezérléssel
uv run --no-sync python -m smarttraffic_ai simulate --scenario rush-hour --controller fixed
uv run --no-sync python -m smarttraffic_ai simulate --scenario rush-hour --controller adaptive

# Lámpaprogramok összehasonlítása
uv run --no-sync python -m smarttraffic_ai optimize --scenario rush-hour

# Dashboard: http://localhost:8501
uv run --no-sync python -m smarttraffic_ai dashboard
```

A három beépített forgatókönyv: `balanced`, `rush-hour`, `variable`. Mindegyik 600 másodperces, szintetikus forgalmat ír le. Saját YAML/JSON-fájl is átadható a `--scenario` argumentumnak. A `--seed` felülírja a véletlen magot; optimalizálásnál egyetlen magra szűkíti a futást.

## Videóelemzés

A dashboard **Videóelemzés** lapján feltölthetsz MP4-et, vagy választhatsz a letöltött mintavideók közül. A **Videó feldolgozása** gomb után látszik az előnézet, a pillanatnyi és az összesített számláló, valamint az éppen látott azonosítók ideje.

A kép-, videó- és élő feldolgozásnál három **Feldolgozási profil** választható:

| Profil | Modell | Képméret | Confidence | Maximum találat |
|---|---|---:|---:|---:|
| Villámgyors | YOLO11n | 640 | 0,25 | 300 |
| Kiegyensúlyozott (alap) | YOLO26n | 960 | 0,20 | 500 |
| Részletes | YOLO26l | 1280 | 0,15 | 1000 |

A **Haladó felismerési beállítások** panelen a méret, küszöb és kategóriák módosíthatók.
Ez nem írja át a konfigurációs fájlt. A Részletes profil CPU-n lassú: a helyi mérésben
egy 2 másodperces videó feldolgozása kb. 69 másodperc volt. A nagyobb modell nem garantál
minden kamerán jobb pontosságot. A profilok nem hagynak ki MP4-képkockákat.

Hiányzó modell a panelen vagy parancssorból tölthető le, hivatalos Ultralytics-forrásból:

```bash
uv run --no-sync python -m smarttraffic_ai download-model --profile detailed
uv run --no-sync python -m smarttraffic_ai detect --input kep.jpg --profile balanced
uv run --no-sync python -m smarttraffic_ai analyze-video --input video.mp4 --profile fast
```

Mért idők, cache és memóriahiba esetén történő visszalépés: [feldolgozási profilok](docs/processing-profiles.md).
Az ID nélküli felismerések is kapnak dobozt; a képkocka találatai, az aktív ID-k és a megerősített
egyedi ID-k külön számok. A részletes diagnosztika külön kapcsolható be.
Mérések és korlátok: [felismerési audit](docs/detection-audit.md).

Csak autó, busz, teherautó, motorkerékpár, kerékpár és gyalogos szerepel a kimenetben. Táska és más, közlekedéshez nem szükséges kategória ki van szűrve. Az összesítő legalább 3 észlelést és fél másodperc látható időt vár meg. Egy ID-t egyszer számol, de hosszabb takarás után ugyanaz a közlekedő új ID-t kaphat.

Az elemzés végén lejátszható és letölthető a jelölt videó. CSV/JSON tartalmazza az első és utolsó észlelést, az összes látható időt és a képkockánkénti számokat. A látható időből a kihagyott képkockák kimaradnak. Az első–utolsó időszak ezeket a réseket is tartalmazza.

A jelzőlámpák külön dobozt és táblázatot kapnak: piros, sárga, zöld, piros+sárga vagy ismeretlen állapottal. A szín a képből becsült. A gyalogos/jármű típust a **Lámpák és típusuk beállítása** panelen lehet megadni; a YOLO ezt önmagában nem különbözteti meg. A két mintavideóhoz van ellenőrzött lámpaterület-beállítás. A lámpák nem számítanak bele a közlekedők darabszámába.

Élő videóhoz válaszd a **Videóelemzés → Élő forrás** lehetőséget. Illeszd be az Időkép kameraoldalának címét (például `https://www.idokep.hu/webkamera/hgabesz`), vagy egy közvetlen HLS/HTTP(S)/RTSP videócímet, majd kattints az **Élő elemzés indítása** gombra. A böngészős `blob:` cím nem használható; az Időkép-oldalból a program minden indításkor kiolvassa az aktuális HLS-forrást.

Frissülő képes kamerák is megadhatók, például `https://www.idokep.hu/webkamera/kevenet`, illetve közvetlen JPG/PNG-címek. Ezeket a program 30 másodpercenként kéri le; változatlan képet nem elemez újra. Ilyenkor az adott kép közlekedőit jelöli és számolja, egyedi követési ID, összesített járműszám és láthatósági idő nélkül. A különálló képek közötti mozgás nem rekonstruálható; a lámpaszín is csak az adott képből becsült jelzés. A képek letöltési időpontja nem feltétlenül a felvétel készítési ideje.

A Budapest Közút kameraoldalai is beilleszthetők, például `https://kozutfigyelo.budapestkozut.hu/list/camerahistory?id=10003`. A program a nyilvános API-ból a legfrissebb kameraképet kéri le, képenként elemzi, és kiírja a szolgáltató képidőbélyegét. Az oldal korábbi képeinek teljes lejátszását nem dolgozza fel.

YouTube élő közvetítésnél a videó linkjét add meg, például `https://www.youtube.com/watch?v=HUeaYuBLNNQ`. A `youtube.com/watch`, `youtu.be`, `/live/` és `/embed/` alakokat felismeri, a beágyazási paramétereket elhagyja. Az aktuális HLS-forrást minden indításkor újra feloldja, legfeljebb 720p H.264 videót választ, a teljes közvetítést nem tölti le. Ehhez a `youtube` extra (`uv pip install -e '.[youtube]'`) és a PATH-ban Node.js 22+ vagy Deno 2.3+ szükséges. A helyi gépen ezek már be vannak állítva. Korlátozott, megszűnt vagy támogatott HLS nélküli videónál hibát jelez; nincs automatikus bejelentkezés vagy böngészős sütiolvasás. A YouTube változásai miatt a feloldót időnként frissíteni kell: `uv pip install -U 'yt-dlp[default]'`.

Az élő előnézet dobozokkal, ID-kkel, becsült látható időkkel és számlálókkal frissül. Alapból 120 másodperces próba indul, legfeljebb 5 kép/másodperces elemzéssel; mindkettő állítható. A **Leállítás** gomb megszakítja a feldolgozást, utána JSON tölthető le. A felület bezárása után 30 másodperccel a feldolgozó automatikusan leáll. A teljes élő videót nem menti, a HLS-szegmensek ideiglenes fájljai leálláskor törlődnek.

Az élő látható idő mintavételi becslés, az időbélyeg az elemzés kezdete óta eltelt idő. A hálózati kimaradás nem adódik hozzá a láthatósághoz. Két másodpercnél régebbi képen a lámpaállapot nem jelenik meg aktuálisként; kapcsolatvesztés után újra kell indítani az elemzést, új számlálással. A HLS szegmensenként érkezik, ezért a kép késhet. Titkosított, fMP4- vagy byte-range HLS-forrás jelenleg nem támogatott.

```bash
uv run --no-sync python -m smarttraffic_ai analyze-video --input sajat-video.mp4
```

A videóelemzéshez a `vision` extra és a PATH-ból elérhető FFmpeg szükséges. Beállítások és idődefiníciók: [ai-model.md](docs/ai-model.md).

## Kép/videó → SUMO

Videóból mért belépésekhez előbb a **Forgalommérés** lapot használd: menthető kamerazónák és irányított számlálóvonalak, időbélyegzett események, 10/30/60 másodperces számlálás, jelölt videó és kézi referenciaértékelés érhető el. A mért események saját időbélyegükkel kapcsolhatók a SUMO-ba; a kezdetben jelen lévő járművek nem duplázódnak meg. A stopvonali/helyi áthaladás külön szerepű, nem automatikusan új beérkezés. A teljes folyamat és a demonstráció korlátai: [Videós forgalommérés](docs/traffic-flow.md).

A **Kép/videó → SUMO** lapon a már lefuttatott felismerésből saját forgalmi helyzet generálható:

1. A Képfeldolgozás vagy Videóelemzés lapon dolgozd fel a bemenetet.
2. Válaszd ki a felismerést, majd rendeld a találatokat N/E/S/W bevezető ágakhoz. Kézi hozzárendelés és normalizált téglalapzónák használhatók. A kép széle nem határozza meg a forgalmi irányt; a parkoló találatokat hagyd ki.
3. Válassz négyágú vagy T-csomópontot, sávszámot, ághosszt, sebességet és kanyarodási arányokat. Ezek sablonparaméterek, nem a képből mért geometria.
4. Ellenőrizd a kezdeti terhelést és a külön megadott későbbi érkezéseket, majd kattints a **SUMO-forgatókönyv létrehozása** gombra.
5. Indítsd el a generált forgalmat, szükség esetén SUMO-GUI-val, vagy hasonlítsd össze a fix és adaptív vezérlést azonos járműigénnyel. A teljes fájlcsomag ZIP-ben is letölthető.

A pillanatnyi gépjárműszám kezdeti terhelést ad; nem változik észrevétlenül új érkezéssé. A gépjárművek típusa megmarad (személyautó, busz, teherautó, motorkerékpár). A gyalogosok és kerékpárok megfigyelése szerepel az adatokban, de a mostani SUMO-sablonban nem szimuláltak. Az ismeretlen irányú találatok kimaradnak a járműigényből.

Videónál a megerősített tracking-ID-k pozíciói és a képkockák tényleges időközei alapján időablakos foglaltság készül. A későbbi intenzitás kézzel adható meg, vagy a megfigyelt foglaltság súlyozhat egy megadott alapintenzitást. Ez továbbra is feltételezés, nem számlálóvonalon mért érkezés. Korábbi, `observations.jsonl` nélküli videóeredménynél újra kell futtatni a videóelemzést.

Ez a két becslési mód megmaradt. A harmadik lehetőség a **Követett vonalátlépések időbélyegei**: az elkészült forgalommérésből pontosan az elfogadott új entry események kerülnek a generátorba, Poisson-újragenerálás nélkül. A pontosság igazolásához ember által ellenőrzött referencia kell; enélkül külön jelölt kísérleti futtatás választható. A meglévő busy_intersection minta demonstráció, nem igazolt beérkezési referencia.

Parancssorból ugyanaz a folyamat:

```bash
# Előbb ellenőrizd és igazítsd a képhez a scene-example.yaml példazónáit!
uv run --no-sync python -m smarttraffic_ai reconstruct --input sajat-kep.jpg --settings config/scene-example.yaml --run
uv run --no-sync python -m smarttraffic_ai reconstruct --input sajat-video.mp4 --settings config/scene-example.yaml --compare

# A kiírt scene-* könyvtár útvonalát add meg:
uv run --no-sync python -m smarttraffic_ai scene-run --scene outputs/scene-AZONOSITO --gui
uv run --no-sync python -m smarttraffic_ai scene-compare --scene outputs/scene-AZONOSITO
```

A `--input` meglévő `detection.json` vagy `analysis.json` is lehet. A generált könyvtár saját hálózatot, járműigényt és `simulation.sumocfg` állományt tartalmaz. A hálózatot `netconvert` készíti; a kész `.net.xml` fájlt a generátor nem írja át. A mérések az indított `run-*` könyvtárban találhatók. Módszer, mezők, fázisok és korlátok: [Képi adatokból SUMO](docs/scene-to-sumo.md).

## Állóképi felismerés és korábbi becslés

```bash
uv run --no-sync python -m smarttraffic_ai detect --input sajat-kep.jpg
uv run --no-sync python -m smarttraffic_ai estimate --input detection.json --prior-rate 450
```

A `detect` JPG/PNG képet fogad. Az eredmény JSON és jelölt kép; az `estimate --input` értékéhez a kiírt JSON útvonalát add meg. A képfeldolgozás is a hat közlekedési kategóriát használja. A forgatókönyv-adapter irányonkénti gépjárműszámaiba a gyalogos és a kerékpár nem számít bele.

Az `estimate` alacsony, közepes és magas intenzitású forgatókönyvet készít a megadott jármű/óra feltételezésből. A képen látott darabszám nem érkezési intenzitás; az adapter nem méri meg az álló sor hosszát vagy a járművek sebességét. A kimeneti forgatókönyv JSON átadható a `simulate --scenario` argumentumnak.

Modell nélküli kipróbáláshoz a `detect --mock` előre megadott tesztobjektumokat használ. A kimenet jelzi ezt a forrást.

## Eredmények

A futások az `outputs/` könyvtárba kerülnek. Egy szimuláció mappája tartalmazza a `result.json`, `metrics.csv`, `timeline.csv` és `tripinfo.xml` fájlokat, valamint a hálózat és a járműigény másolatát.

Az optimalizálás `runs.csv` fájlja az egyes futásokat, a `comparison.csv` és `comparison.json` a magok szerinti átlagolt rangsort tárolja. A kisebb pontszám kedvezőbb. Az adaptív vezérlés nem feltétlenül jobb a fixnél. A metrikák és a célfüggvény pontos definíciója: [optimization.md](docs/optimization.md).

## Tesztelés

```bash
uv run --no-sync python -m pytest
uv run --no-sync python -m ruff check .
```

A SUMO-t igénylő tesztek hiányzó szimulátornál kimaradnak. Az integrációs tesztek ideiglenes könyvtárban futnak, nem írnak a saját eredményeid közé. Részletek: [testing.md](docs/testing.md).

## Felépítés és korlátok

A kód a `src/smarttraffic_ai/`, a konfiguráció a `config/`, a mintaforgatókönyvek a `data/scenarios/` alatt találhatók. A projekt az `MI` mappától független.

- [Architektúra és adatfolyam](docs/architecture.md)
- [SUMO-hálózat és vezérlés](docs/sumo.md)
- [Korlátok és következő feladatok](docs/limitations.md)

Van konfigurálható vonalátlépés-számlálás és referenciaértékelés. Valós kereszteződésre kalibrált geometria és ember által igazolt kamerás pontosság még nincs. Külső képek és modellek eredetét, illetve felhasználási feltételeit külön kell rögzíteni.
