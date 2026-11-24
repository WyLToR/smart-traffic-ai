# Források és licencek

A verziók a 2026. november 24-i ellenőrző környezetre vonatkoznak (Windows, Python 3.12.10).
A „csomag-metaadat” jelölésű licenceket a telepített csomag saját metaadataiból olvastuk ki.
A ByteTrack és az uv licencét a sorban megadott hivatalos licencoldal alapján rögzítettük.
Ami nem ellenőrzött, azt külön jelöljük.

A projekt saját kódjához a csapat még nem választott licencet; a repository ezért nem
tartalmaz licencfájlt.

## Szoftverek és könyvtárak

| Megnevezés | Készítő / projekt | Hivatalos URL | Felhasználás | Verzió | Licenc |
|---|---|---|---|---|---|
| Python | Python Software Foundation | https://www.python.org/ | Futtatókörnyezet | 3.12.10 | PSF License |
| Ultralytics | Ultralytics | https://github.com/ultralytics/ultralytics | YOLO-inferencia, ByteTrack-implementáció | 8.4.198 | AGPL-3.0 (csomag-metaadat) |
| PyTorch | PyTorch Foundation | https://pytorch.org/ | Az Ultralytics neurálishálózat-futtatója, CPU | 2.7.1+cpu (lock: 2.15.0) | BSD-3-Clause (csomag-metaadat) |
| OpenCV (opencv-python) | OpenCV | https://opencv.org/ | Videódekódolás, rajzolás, lámpaszín HSV-elemzése | 4.14.0 | Apache-2.0 (csomag-metaadat) |
| lap | gatagat/lap | https://github.com/gatagat/lap | A ByteTrack hozzárendelési lépése | 0.5.13 | BSD-2-Clause (csomag-metaadat) |
| Eclipse SUMO | Eclipse Foundation, DLR | https://eclipse.dev/sumo/ | Forgalmi mikroszimuláció, `netconvert` | 1.28.0 | EPL-2.0 OR GPL-2.0-or-later (csomag-metaadat) |
| TraCI, sumolib | Eclipse SUMO | https://sumo.dlr.de/docs/TraCI.html | Szimuláció vezérlése és hálózat olvasása Pythonból | 1.28.0 | EPL-2.0 OR GPL-2.0-or-later (csomag-metaadat) |
| Streamlit | Snowflake / Streamlit | https://streamlit.io/ | Dashboard | 1.66.1 | Apache-2.0 (csomag-metaadat) |
| FFmpeg | FFmpeg-projekt | https://ffmpeg.org/ | Jelölt MP4 kódolása, elemzési videóváltozat | 8.1 (gyan.dev essentials build) | A helyi build `--enable-gpl --enable-version3` beállítású, így GPLv3; külső programként hívjuk, nem terjesztjük |
| Pydantic | Pydantic | https://docs.pydantic.dev/ | Adatmodellek és validáció | 2.14.2 | MIT (csomag-metaadat) |
| PyYAML | PyYAML | https://pyyaml.org/ | Konfiguráció | 6.0.3 | MIT (csomag-metaadat) |
| Plotly | Plotly | https://plotly.com/python/ | Diagramok a dashboardon | 6.9.0 | MIT (csomag-metaadat) |
| Pillow | Python Pillow | https://python-pillow.github.io/ | Képbeolvasás, jelölt kép | 12.3.0 | MIT-CMU (csomag-metaadat) |
| pandas | pandas | https://pandas.pydata.org/ | Táblázatok a dashboardon | 3.1.0 | BSD-3-Clause (csomag-metaadat) |
| yt-dlp (opcionális) | yt-dlp | https://github.com/yt-dlp/yt-dlp | YouTube élő HLS-cím feloldása | 2026.10.26 | Unlicense (csomag-metaadat) |
| pytest, Ruff | pytest, Astral | https://pytest.org/, https://docs.astral.sh/ruff/ | Tesztelés, statikus ellenőrzés | 9.2.0, 0.17.3 | MIT (csomag-metaadat) |
| uv | Astral | https://docs.astral.sh/uv/ | Csomagkezelés, `uv.lock` | 0.11.3 | MIT OR Apache-2.0, https://github.com/astral-sh/uv/blob/main/docs/reference/policies/license.md |

## AI-modellek és módszerek

| Megnevezés | Készítő | URL | Felhasználás | Licenc |
|---|---|---|---|---|
| YOLO11n (`yolo11n.pt`) | Ultralytics | https://docs.ultralytics.com/models/yolo11/ ; súly: `github.com/ultralytics/assets` v8.3.0 kiadás | Villámgyors profil | Ultralytics: AGPL-3.0 vagy Enterprise licenc, https://www.ultralytics.com/license |
| YOLO26n (`yolo26n.pt`) | Ultralytics | https://docs.ultralytics.com/models/yolo26/ ; súly: `github.com/ultralytics/assets` v8.4.0 kiadás | Kiegyensúlyozott (alap) profil | mint fent |
| YOLO26l (`yolo26l.pt`) | Ultralytics | mint fent | Részletes profil | mint fent |
| COCO-adatkészlet | COCO Consortium | https://cocodataset.org/ | A YOLO-modellek előtanítása (nem mi tanítottuk) | A modellek a COCO osztálylistáját használják; a projekt nem tartalmaz COCO-adatot |
| ByteTrack | Zhang és mtsai., ECCV 2022 | https://arxiv.org/abs/2110.06864 ; https://github.com/FoundationVision/ByteTrack | Objektumkövetés módszere; az Ultralytics `BYTETracker` implementációját hívjuk | Eredeti repository: MIT, https://github.com/FoundationVision/ByteTrack/blob/main/LICENSE ; a ténylegesen használt implementáció az Ultralytics része (AGPL-3.0) |

A három YOLO-modell egymás alternatívája, nem egymásra épülő lánc. A modellfájlok nincsenek
a repositoryban; a `download-model` parancs a fenti hivatalos kiadásokból tölti le őket.
Az AGPL-3.0 hálózati szolgáltatásként való üzemeltetésnél is forráskód-közzétételi
kötelezettséget írhat elő; a projekt helyi oktatási bemutatóként fut.

## Képek és videók

| Fájl | Forrás és készítő | Felhasználási feltétel | Beadási csomagba |
|---|---|---|---|
| `busy_intersection.mp4` (bemutató) | Pexels, „Busy City Intersection with Pedestrians Crossing”, SHOX ART, https://www.pexels.com/video/busy-city-intersection-with-pedestrians-crossing-33865608/ (eredeti: 3840×2160, 59,94 FPS, 38 s) | Pexels License és ToS | **Nem**; beszerzés: [data/README.md](../data/README.md) |
| `crosswalk_red_car.mp4` | Pexels, „People Waiting To Cross The Street On The Pedestrian Lane”, K, https://www.pexels.com/video/people-waiting-to-cross-the-street-on-the-pedestrian-lane-2836277/ | Pexels License és ToS | Nem |
| A két videóból kimentett képkockák (`frame_002/008/015.jpg`) | Saját kimentés a fenti videókból | Pexels License és ToS | Nem; a bemutatóképet a beszerzési parancs állítja elő |
| Shinjuku-képkockák és 5 s-os szegmens | YouTube élő közvetítés, https://www.youtube.com/watch?v=6dp-bvQ7RWo | **Nem ellenőrzött**; csak helyi mérésre | Nem |
| `IMG_6277.MP4` és 5 s-os próbája | A csapat saját felvétele | Saját; felismerhető járókelőket és rendszámokat tartalmazhat | Nem, amíg az adatvédelmi és felhasználási feltételek nincsenek tisztázva |

A két Pexels-videó helyi példánya a
[yolo-streamlit-detection-tracking](https://github.com/aparsoft/yolo-streamlit-detection-tracking)
projekt `sample-videos` kiadásából származik (az eredeti első 20 másodperce, 1280×720, 30 FPS,
hang nélkül); a készítői adatok annak `videos/ATTRIBUTION.md` fájljából és a Pexels-oldalakról valók
(ellenőrizve: 2026. november 24.). A Pexels License szerint a videók szabadon használhatók és
módosíthatók, forrásmegjelölés nélkül. A Pexels felhasználási feltételeinek 5. pontja viszont
tiltja a tartalom önálló („Standalone”) terjesztését digitális fájlként; a változatlan, illetve csak
vágott vagy átméretezett változat ide tartozik. Ezért a mintákat nem terjesztjük, csak a beszerzésük
módját adjuk meg. Nyilvánosan megtekinthető videó nem jelenti automatikusan, hogy
szabadon letölthető, tárolható vagy újraterjeszthető.

## Élő forrásként támogatott szolgáltatások

Az Időkép (https://www.idokep.hu/webkamera), a Budapest Közút kamerafigyelője
(https://kozutfigyelo.budapestkozut.hu/) és a YouTube élő közvetítései technikailag
megadhatók forrásként. Felhasználási feltételeiket nem ellenőriztük; a bemutató és a mérések
nem ezekre épülnek, és belőlük felvételt nem tárolunk a repositoryban.

## Dokumentáció

- Ultralytics követés: https://docs.ultralytics.com/modes/track
- Ultralytics end-to-end fej és NMS: https://docs.ultralytics.com/guides/end2end-detection
- SUMO TraCI: https://sumo.dlr.de/docs/TraCI.html
- SUMO netconvert: https://sumo.dlr.de/docs/netconvert.html
- Streamlit: https://docs.streamlit.io/
