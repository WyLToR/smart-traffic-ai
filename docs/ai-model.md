# Kép- és videófeldolgozás

A `config/detection.yaml` adja meg a modellt, a confidence küszöböt, a bemeneti méretet,
az eszközt és a régiókat. A jelenlegi alap a Kiegyensúlyozott profil:
`models/yolo26n.pt`, confidence 0,20, méret 960, max_det 500, CPU.
A három profil a meglévő `DetectionConfig` sémára épül; részletek: [profilok](processing-profiles.md).

## Telepítés

Ajánlott, a lock szerinti telepítés (Windows alatt CPU-s PyTorch):

```bash
uv sync --locked --python 3.12 --extra dev --extra sumo --extra vision
```

A fejlesztői gépen korábban kézzel telepített, szintén ellenőrzött CPU-s változat:

```bash
uv pip install --python .venv/Scripts/python.exe --no-cache torch==2.7.1 torchvision==0.22.1 --index-url https://download.pytorch.org/whl/cpu
uv pip install --python .venv/Scripts/python.exe --no-cache -e ".[dev,sumo,vision]"
```

A lock `torch 2.15.0`-t rögzít, a kézi út 2.7.1-et; mindkettővel lefut a teljes tesztkészlet.
Kézi telepítés után `uv run --no-sync` használandó, különben a `uv` a lock szerinti változatra cseréli.

A súlyfájlok a Gitből kizárt `models/` mappába kerülnek. A program csak kifejezett kérésre
tölt le, a `download-model` paranccsal vagy a felület modellkezelő gombjával. A letöltés
után ellenőrzi a betölthetőséget és az osztályokat. Felhasználási feltételek:
[Ultralytics licence](https://www.ultralytics.com/license).

## Feldolgozás

A PIL beolvassa és az EXIF szerint forgatja a JPG/PNG képet, az OpenCV BGR-re alakítja.
A méretezést és az inferenciát az Ultralytics `predict` végzi. A konfiguráció csak `car`,
`bus`, `truck`, `motorcycle`, `bicycle` és `person` osztályneveket enged. Az NMS osztályonkénti,
hogy például egy személy és kerékpár egymást átfedő doboza ne nyomja el egymást.

A régiók normalizált, nem átfedő téglalapok. A hozzárendelés a befoglaló doboz alsó középpontja alapján történik; közös határvonalon az első konfigurált régió dönt. Régión kívüli objektumnál az irány ismeretlen. A mellékelt régiókat kameranézetenként be kell állítani.

A kimenet képazonosítót, időbélyeget, képméretet, feldolgozási időt és objektumlistát tartalmaz. A `--timestamp` időzónás felvételi időt fogad; nélküle a fájl módosítási idejét használjuk. Feltöltésnél ez a feltöltés ideje, nem a felvételé.

A `detection.json`, `summary.json`, `config.json` és `annotated.png` az adott feldolgozás mappájába kerül. A `--mock` előre megadott tesztobjektumokat használ, és `source: mock` jelölést ad; hiba esetén nincs automatikus váltás erre.

A YOLO11n CPU-inferenciája mintaképeken és videókon ellenőrzött. Ez nem kamerás pontosságmérés. Takarás, kis felbontás és éjszakai felvétel esetén külön tesztkészlet szükséges.

## Videó és követés

A `video.py` egy videóhoz egyszer kér modellt a cache-ből. A követő minden videóhoz új
ByteTrack-példány, amely megmarad a képkockák között. Új ID a konfigurált confidence
küszöbtől indulhat; a meglévő ID megtartásához gyengébb találat is használható. A követő
30 képkockányi kimaradást tart fenn, ami nem garantál helyes újraazonosítást.

Egy ID legalább 3 megfigyelés és 0,5 s összes látható idő után kerül a számlálóba. A kategóriát az eddigi találatok confidence-szel súlyozott szavazata adja; egy ID kategóriaváltása nem hoz létre új objektumot. A narancssárga doboz még nem megerősített, a zöld már összesített azonosítót jelöl.

- `first_seen_seconds`, `last_seen_seconds`: az első és utolsó észlelt képkocka kezdőideje a videóban.
- `visible_seconds`: csak az észlelt képkockák időtartamának összege, a rövid kimaradások nélkül.
- `span_seconds`: az első és az utolsó megfigyelt képkocka vége közötti idő, a résekkel együtt.
- `observations`: észlelt képkockák száma, nem különböző közlekedők száma.

Az időalap az OpenCV dekódolt időbélyege. Hiányzó vagy nem növekvő időbélyegnél FPS-alapú lépés helyettesíti, ezt a JSON számlálja. A feldolgozás falióraideje külön mező. A videók között nincs közös követőállapot.

A kimenet `outputs/video-*` alatt: `annotated.mp4`, `analysis.json`, `tracks.csv`, `timeline.csv`,
`detections.jsonl`, `observations.jsonl`, a tényleges `tracker.yaml` és az encoder naplója.
A `detections.jsonl` az ID nélküli találatokat is tartalmazza; az `above_threshold` jelzi,
hogy a találat eléri-e a felhasználó confidence-küszöbét. A követő gyengébb egyezést is
megtarthat meglévő ID-val. Az `observations.jsonl` továbbra is csak követett pozíciókat ad át
a SUMO-nak és a vonalátlépés-számlálónak. Az ID-val rendelkező doboz a követő simított pozíciója;
a nyers YOLO-koordináták bekapcsolt diagnosztikával kerülnek a `raw_detections` mezőbe.
A jelölt MP4 H.264, hang nélkül; a böngészős lejátszáshoz FFmpeg kell.
Változó FPS bemenetnél a kimeneti, állandó FPS-es videó időalapja eltérhet az exportált időbélyegektől.

Az ID nélküli felismerések világoskék dobozt kapnak, és nem növelik az egyedi ID-k számát.
A `person` és a `bicycle` külön objektumkategória: összegük nem hitelesített közlekedőszám.
A ByteTrack ugyanazt az Ultralytics-követőt használja, de a program a detektálást a követő
szűrése előtt megőrzi. Részletek és ismételhető mérés: [felismerési audit](detection-audit.md).

Az összes ID nem hitelesített egyedi jármű- vagy gyalogosszám. Takarás és kategóriatévesztés szétvághat vagy összekeverhet pályákat; a fél másodpercnél rövidebb találatok kimaradnak az összesítőből. A külön [forgalommérési ág](traffic-flow.md) irányított vonalátlépési eseményeket készít, és ezeket a [videó–SUMO kapcsolat](scene-to-sumo.md) felhasználhatja. A mért események száma és a követett ID-k száma eltérő fogalom.

## Jelzőlámpák

A videóhívás a `traffic light` osztályt is lekéri a YOLO-tól, de a közlekedőket számláló `TrackCounter` ezt kizárja. A lámpák külön eredményben szerepelnek.

A `traffic_lights.py` a lámpadobozon vagy a kézzel kijelölt területen belüli fényes, telített HSV-színkomponenseket vizsgálja. Kis vagy bizonytalan foltnál ismeretlen állapotot ad; egyidejű erős piros és zöld esetén is ismeretlent. Három egymást követő találat kell az új állapot megerősítéséhez. A lámpa eltűnése vagy bizonytalan képe nem tartja meg a korábbi jelzést.

A YOLO COCO-modellje általános lámpakategóriát ismer, színt és gyalogos/jármű altípust nem. A típus ezért kamerabeállítás, nem automatikus modelljóslat. Az automatikusan megtalált, még be nem állított lámpa típusa ismeretlen. A típus eredete a táblázatban és a `kind_source` mezőben is szerepel. A gyalogosprofil kétállapotú, piros/zöld jelzőt feltételez; a jármű/ismert típus nélküli profil sárgát és piros+sárgát is kezel.

A `config/traffic-lights.yaml` a két ellenőrzött mintafájl SHA-256 lenyomatához rendeli a kijelölt lámpaterületeket és típusokat. Más videóra ezek nem kerülnek rá automatikusan. A dashboard szerkeszthető táblázatában megadható az ID, típus és a normalizált téglalap; az első képkocka mutatja a kijelölést. A beállítás az adott elemzés JSON-jába kerül, a közös konfigurációt a felület nem írja felül.

A lámpák állapota feldolgozás közben látszik, a kimenetben a `traffic-lights.csv` és az `analysis.json` tartalmazza. A JSON állapotonkénti összes időt is tárol. Az ismeretlen idő a megerősítésre váró, nem látható vagy nem értékelhető képkockákat is tartalmazza. A rosszul kijelölt vagy kameramozgás miatt elcsúszó terület, tükröződés és takarás téves színt okozhat; a színheurisztika nem hitelesített jelzésfelismerő.
