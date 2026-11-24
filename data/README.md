# Adatok

A `scenarios/` saját készítésű, szintetikus forgatókönyveket tartalmaz. Az intenzitások feltételezések, nem valós forgalomszámlálás eredményei.

Saját képet például a Gitből kizárt `samples/private/` alatt tárolhatsz. Külső adat mellé rögzítsd a forrást és a felhasználási feltételeket. A feldolgozott képek és a szimulációs eredmények az `outputs/` könyvtárba kerülnek.

## Bemutató minták (`samples/demo/`, beszerzendő)

A bemutató a Pexels „Busy City Intersection with Pedestrians Crossing” videóján fut
(SHOX ART, https://www.pexels.com/video/busy-city-intersection-with-pedestrians-crossing-33865608/,
eredetileg 3840×2160, 59,94 FPS, 38 s). A Pexels felhasználási feltételei (ToS 5. pont) tiltják
a tartalom önálló, változatlan vagy csak vágott/átméretezett fájlként való terjesztését, ezért
a minta **nem része a repositorynak és a beadási csomagnak**; a mappa Gitből kizárt.

Beszerzés PowerShellben, a projekt gyökeréből. A forrás a
[yolo-streamlit-detection-tracking](https://github.com/aparsoft/yolo-streamlit-detection-tracking)
projekt `sample-videos` kiadása: az eredeti első 20 másodperce, 1280×720, 30 FPS, hang nélkül.

```powershell
New-Item -ItemType Directory -Force data/samples/demo | Out-Null
Invoke-WebRequest https://github.com/aparsoft/yolo-streamlit-detection-tracking/releases/download/sample-videos/busy_intersection.mp4 -OutFile data/samples/demo/busy_intersection.mp4
(Get-FileHash data/samples/demo/busy_intersection.mp4 -Algorithm SHA256).Hash
# Elvárt: 0880067FE1C79B31EFBA3FE9F22CB4BF75A6CDB27747D70AD8C76A5C54C729CA
uv run --no-sync python -c "import cv2; c = cv2.VideoCapture('data/samples/demo/busy_intersection.mp4'); c.set(cv2.CAP_PROP_POS_FRAMES, 240); ok, f = c.read(); cv2.imwrite('data/samples/demo/busy_intersection_frame_008.jpg', f, [cv2.IMWRITE_JPEG_QUALITY, 95])"
# Elvárt kép-SHA-256: FD4A453885002E5698DCBF522D895987CE5D95A2642FA3C10AD5F5F040BD248F
```

A második parancs a 8. másodperc (240. képkocka) képét menti; ugyanezzel a lenyomattal
készültek a dokumentált mérések. Egyező lenyomatnál a videó a **Mintavideó** lista első
eleme lesz, és automatikusan megkapja a `config/cameras/busy-intersection.json` kameraprofilt
és a `config/traffic-lights.yaml` lámpaterületét. Ha a kiadás nem érhető el, az eredeti
Pexels-videó is használható, de akkor más a lenyomat és a felbontás: a zónák arányosan
érvényesek, a számok viszont eltérnek a dokumentálttól, és a lámpaterület nem töltődik be.
A kép- és videóbemutató SUMO-beállítása: `config/scene-busy-intersection.yaml`.

## IMG_6277.MP4

A felhasználó által megadott valós kereszteződési felvétel eredeti helye:
`runs/detect/outputs/video-preview/IMG_6277.MP4`. A fájl változatlan maradt, nem került Gitbe.
Az adatvédelmi és felhasználási feltételek tisztázásáig sem a felvétel, sem a belőle készült
próbaminta vagy képkocka nem része a beadási csomagnak. A csomagban csak a hozzá tartozó
beállítások vannak (`config/cameras/img-6277.json`, lámpaterület, mintajegyzék-bejegyzés);
ezek személyes adatot nem tartalmaznak, és a fájl hiányában a program egyszerűen kihagyja a mintát.
H.264, 1280×720, kb. 120 FPS, 141,637 másodperc, kb. 487 MiB.

A `config/video-samples.yaml` felveszi a **Videóelemzés → Mintavideó** listába.
Az 5 másodperces, átkódolt próbaminta az `outputs/img6277-validation/` alatt található;
mind a 600 képkockája megmaradt. A többi MP4 a `samples/private/` mappából és a korábbi
mintavideó-könyvtárból is választható, nagybetűs `.MP4` kiterjesztéssel is.

A forrás konténere 17 000 képkockát jelez. A teljes OpenCV-beolvasás és az FFprobe
képkockaszámlálása egyaránt 16 994-et adott, a teljes idővonalon, dekódolási hiba nélkül.
Ez az ellenőrzött darabszám a fájl SHA-256-azonosítójához kötött; nem általános engedmény
a hiányos videókra. Más vagy megváltozott fájl képkockaeltérését a feldolgozó továbbra is elutasítja.

A `config/traffic-lights.yaml` a jobb oldali, teljesen látható járműjelző területét tartalmazza.
Ennél a napfényes felvételnél a minimális HSV-fényesség 200: az alacsonyabb küszöb
az inaktív lámpa tükröződését téves sárga jelzésnek vette. A többi kamera alapértéke nem változott.
Hat időpont képi ellenőrzése: 0/60/135 s zöld, 10/30/100 s piros. Rövid videós próbán
a zöld és a piros jelzés időbeli megerősítése is működött. A részben levágott felső és
a túl kicsi távoli lámpákhoz nem adtunk igazolatlan gyalogos/jármű típust.

A `config/cameras/img-6277.json` ellenőrizendő kiinduló zónákat és helyi számlálóvonalakat ad.
A kamera kissé mozog; rögzítettsége nincs jóváhagyva. Az E/W jelölés a két látható
menetirány SUMO-sablonhoz rendelése, nem mért égtáj. A parkolósort a zónák jórészt
kihagyják, de parkolásfelismerés nem történik. A vonalak `discharge` szerepűek: helyi
áthaladásból nem lesz automatikusan új SUMO-érkezés.

Feldolgozás után a **Forgalommérés** lap felkínálja a hozzá tartozó kameraprofilt.
A **Kép/videó → SUMO** lap betölti a kapcsolt zónákat; ezek kikapcsolhatók és szerkeszthetők,
a generálás előtt továbbra is ellenőrizni kell őket. A lámpa képen mért állapota nem
azonos a SUMO feltételezett lámpaprogramjával.

Ellenőrzés: az 5 másodperces részlet 600 képkockája valódi YOLO11n + ByteTrack feldolgozással
végigment, a zónák szerinti egy kezdeti autó a SUMO-ban célba ért. Az összes megerősített
ID száma nem valós áthaladási darabszám; nincs kézzel hitelesített pontossági referencia.
A teljes eredeti videón a dekódolás ellenőrzött, teljes YOLO-futtatás nem történt.
Eredmények: `outputs/img6277-validation/` (`source.json`, `decode.json`, `video-result.json`,
`sumo.json`, `red-result.json`, `light-validation.json`, `light-temporal.json`).
