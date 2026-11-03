# Kép- és videófeldolgozás

A `config/detection.yaml` adja meg a modellt, a confidence küszöböt, a bemeneti méretet, az eszközt és a régiókat. Alapértékek: `models/yolo11n.pt`, 0,35, 640, CPU.

## Telepítés

Általános telepítés:

```bash
uv pip install --python .venv/Scripts/python.exe -e ".[vision]"
```

Python 3.12 alatt ellenőrzött CPU-s változat:

```bash
uv pip install --python .venv/Scripts/python.exe --no-cache torch==2.7.1 torchvision==0.22.1 --index-url https://download.pytorch.org/whl/cpu
uv pip install --python .venv/Scripts/python.exe --no-cache -e ".[dev,sumo,vision]"
```

A közös `uv.lock` ettől eltérő PyTorchot rögzíthet. A külön telepített környezetben `uv run --no-sync` használható; újraszinkronizálás után a fenti parancsokkal állítható vissza a CPU-s változat.

A [YOLO11n súlyfájlt](https://github.com/ultralytics/assets/releases/download/v8.3.0/yolo11n.pt) helyezd a `models/` mappába. A program nem tölti le automatikusan. A modellfájlok Gitből kizártak. Felhasználási feltételek: [Ultralytics licence](https://www.ultralytics.com/license).

## Feldolgozás

A PIL beolvassa a JPG/PNG képet, az OpenCV BGR-re alakítja. A méretezést és az inferenciát az Ultralytics `predict` végzi. A konfiguráció csak `car`, `bus`, `truck`, `motorcycle`, `bicycle` és `person` osztályneveket enged. Ezek ID-listáját már a modellhívás megkapja. Az osztályfüggetlen NMS csökkenti a közel azonos, eltérő kategóriájú dobozok ismétlődését.

A régiók normalizált, nem átfedő téglalapok. A hozzárendelés a befoglaló doboz alsó középpontja alapján történik; közös határvonalon az első konfigurált régió dönt. Régión kívüli objektumnál az irány ismeretlen. A mellékelt régiókat kameranézetenként be kell állítani.

A kimenet képazonosítót, időbélyeget, képméretet, feldolgozási időt és objektumlistát tartalmaz. A `--timestamp` időzónás felvételi időt fogad; nélküle a fájl módosítási idejét használjuk. Feltöltésnél ez a feltöltés ideje, nem a felvételé.

A `detection.json`, `summary.json`, `config.json` és `annotated.png` az adott feldolgozás mappájába kerül. A `--mock` előre megadott tesztobjektumokat használ, és `source: mock` jelölést ad; hiba esetén nincs automatikus váltás erre.

A YOLO11n CPU-inferenciája mintaképeken és videókon ellenőrzött. Ez nem kamerás pontosságmérés. Takarás, kis felbontás és éjszakai felvétel esetén külön tesztkészlet szükséges.

## Videó és követés

A `video.py` egy videóhoz egyszer tölti be a modellt. A képkockák között ByteTrack és `persist=True` tartja meg az azonosítókat. Új ID a konfigurált confidence küszöbtől indulhat; a meglévő ID megtartásához gyengébb találat is használható. A követő 30 képkockányi kimaradást tart fenn, de ez nem garantál helyes újraazonosítást.

Egy ID legalább 3 megfigyelés és 0,5 s összes látható idő után kerül a számlálóba. A kategóriát az eddigi találatok confidence-szel súlyozott szavazata adja; egy ID kategóriaváltása nem hoz létre új objektumot. A narancssárga doboz még nem megerősített, a zöld már összesített azonosítót jelöl.

- `first_seen_seconds`, `last_seen_seconds`: az első és utolsó észlelt képkocka kezdőideje a videóban.
- `visible_seconds`: csak az észlelt képkockák időtartamának összege, a rövid kimaradások nélkül.
- `span_seconds`: az első és az utolsó megfigyelt képkocka vége közötti idő, a résekkel együtt.
- `observations`: észlelt képkockák száma, nem különböző közlekedők száma.

Az időalap az OpenCV dekódolt időbélyege. Hiányzó vagy nem növekvő időbélyegnél FPS-alapú lépés helyettesíti, ezt a JSON számlálja. A feldolgozás falióraideje külön mező. A videók között nincs közös követőállapot.

A kimenet `outputs/video-*` alatt: `annotated.mp4`, `analysis.json`, `tracks.csv`, `timeline.csv`, a tényleges `tracker.yaml` és az encoder naplója. A jelölt MP4 H.264, hang nélkül; a böngészős lejátszáshoz a rendszerre telepített FFmpeg kell (`ffmpeg -version`). A kimenet állandó FPS-re normalizált, ezért változó FPS bemenetnél a lejátszás időalapja eltérhet az exportált eredeti időbélyegektől.

Az összes ID nem hitelesített egyedi jármű- vagy gyalogosszám. Takarás és kategóriatévesztés szétvághat vagy összekeverhet pályákat; a fél másodpercnél rövidebb találatok kimaradnak az összesítőből. Nincs még vonalátlépés-számlálás vagy videó–SUMO adatkapcsolat.

## Jelzőlámpák

A videóhívás a `traffic light` osztályt is lekéri a YOLO-tól, de a közlekedőket számláló `TrackCounter` ezt kizárja. A lámpák külön eredményben szerepelnek.

A `traffic_lights.py` a lámpadobozon vagy a kézzel kijelölt területen belüli fényes, telített HSV-színkomponenseket vizsgálja. Kis vagy bizonytalan foltnál ismeretlen állapotot ad; egyidejű erős piros és zöld esetén is ismeretlent. Három egymást követő találat kell az új állapot megerősítéséhez. A lámpa eltűnése vagy bizonytalan képe nem tartja meg a korábbi jelzést.

A YOLO COCO-modellje általános lámpakategóriát ismer, színt és gyalogos/jármű altípust nem. A típus ezért kamerabeállítás, nem automatikus modelljóslat. Az automatikusan megtalált, még be nem állított lámpa típusa ismeretlen. A típus eredete a táblázatban és a `kind_source` mezőben is szerepel. A gyalogosprofil kétállapotú, piros/zöld jelzőt feltételez; a jármű/ismert típus nélküli profil sárgát és piros+sárgát is kezel.

A `config/traffic-lights.yaml` a két ellenőrzött mintafájl SHA-256 lenyomatához rendeli a kijelölt lámpaterületeket és típusokat. Más videóra ezek nem kerülnek rá automatikusan. A dashboard szerkeszthető táblázatában megadható az ID, típus és a normalizált téglalap; az első képkocka mutatja a kijelölést. A beállítás az adott elemzés JSON-jába kerül, a közös konfigurációt a felület nem írja felül.

A lámpák állapota feldolgozás közben látszik, a kimenetben a `traffic-lights.csv` és az `analysis.json` tartalmazza. A JSON állapotonkénti összes időt is tárol. Az ismeretlen idő a megerősítésre váró, nem látható vagy nem értékelhető képkockákat is tartalmazza. A rosszul kijelölt vagy kameramozgás miatt elcsúszó terület, tükröződés és takarás téves színt okozhat; a színheurisztika nem hitelesített jelzésfelismerő.
