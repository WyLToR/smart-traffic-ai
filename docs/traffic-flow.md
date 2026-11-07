# Videós forgalommérés

A rögzített videó már meglévő ByteTrack-pozícióexportjából irányított vonalátlépési események készülnek. A kamerabeállítás változtatása nem igényel új YOLO-futtatást. Élő videót és frissülő állóképet ez a mérési ág jelenleg nem kezel.

## Használat

1. Dolgozd fel az MP4-et a Videóelemzés lapon.
2. A **Forgalommérés** lapon válaszd ki a videófelismerést. Tölts be mentett kamerabeállítást, vagy add meg a zónákat és vonalakat a táblázatokban.
3. A normalizált koordináták és a képi előnézet alapján ellenőrizd a vonalakat. A nyíl mutatja a beszámított irányt. A beállítás számszerűen szerkeszthető, nem egérrel rajzolható.
4. Erősítsd meg, hogy a kameranézet végig rögzített, majd indítsd a mérést. A koordináták felbontásfüggetlenek; eltérő képaránynál új ellenőrzés szükséges.
5. Az események, 10/30/60 másodperces ablakok és a jelölt videó megtekinthetők. A kamerakonfiguráció, mérés és CSV-k letölthetők.
6. A kézi referencia összeállítható a felületen, vagy JSON-ból betölthető. Az eredeti videó külön is lejátszható, ha helyben elérhető és egyezik a forrás ellenőrzőösszege.
7. A **Kép/videó → SUMO** lapon válaszd a videót és a **Követett vonalátlépések időbélyegei** lehetőséget.

Parancssorból, korábban elkészült felismeréssel:

```bash
uv run --no-sync python -m smarttraffic_ai measure-flow --input outputs/video-AZONOSITO/analysis.json --camera config/cameras/busy-intersection.json --annotate
uv run --no-sync python -m smarttraffic_ai evaluate-flow --measurement outputs/flow-AZONOSITO/measurement.json --reference sajat-referencia.json --tolerance 1
```

A `measure-flow --input` MP4-et is fogad; ekkor előbb a meglévő videóelemzés fut le. A `measurement.json` és `validation.json` útvonala megadható a rekonstrukciós beállításban:

```json
{
  "arrival_mode": "measured",
  "flow_measurement_path": "outputs/flow-AZONOSITO/measurement.json",
  "flow_validation_path": "outputs/flow-AZONOSITO/validation.json",
  "arm_length": 250,
  "warmup_seconds": 5
}
```

Ezzel a meglévő `reconstruct --input ... --settings ... --run` parancs használható. A kamera mentett zónái adják az irány-hozzárendelést; kézi ID-felülírás nem keverhető a mért ággal. Az alapműködés igazolt referenciát kér. A felületen külön választható kísérleti mód, parancssorból `allow_unvalidated_flow: true` állítható. Ez látható feltételezés marad, nem pontossági minősítés.

## Mit jelent a mérés?

A kameraazonosítóhoz normalizált téglalapzónák, véges számlálóvonalak, beszámított mozgásirány és SUMO-bevezető ág tartozik. A kamera nem ellenőrzi automatikusan a rögzítettséget: ezt a videón a felhasználó vizsgálja meg. A vonal szerepe:

- `entry`: ellenőrzött beérkezési pont, lehetőleg a kialakuló sor előtt.
- `discharge`: kereszteződési, stopvonali vagy más helyi áthaladás. Ebből nem lesz automatikusan új SUMO-érkezés.

A követett befoglaló téglalap alsó középpontját használjuk. A pontnak a véges vonalat kell kereszteznie, nem annak meghosszabbítását. A normalizált holtsáv alapból 0,005, az oldalak megerősítéséhez két-két észlelés kell. Az átmeneti időbélyeg a környező megfigyelésekből interpolált; nem nagyobb pontosságú, mint az eredeti követés.

A vonal körüli kis remegés nem ad eseményt. Egy ID/vonal/mozgásirány csak egyszer számít a videóban; az ugyanazon ID-val megfigyelt ismételt visszafordulásokat ezért nem teljes utazási naplóként kezeljük. Az ellenirány külön esemény, nem új beérkezés.

Egy másodpercnél hosszabb eltűnés vagy túl nagy képtérbeli ugrás megszakítja a folytonos áthaladási bizonyítékot. Rövid időn belül eltűnő és közeli új ID-n megjelenő, azonos kategóriájú objektumnál `possible_id_switch` jelzés készül. Ez csak gyanú, nem bizonyított újraazonosítás. A 0,25 másodpercnél nagyobb intervallumon át interpolált áthaladás `crossing_across_gap` jelzést kap. A határok a mentett kamerakonfigurációban állíthatók; fizikai sebességet nem mérünk belőlük.

Az esemény tartalmazza a kamera- és track-ID-t, kategóriát, vonalat, SUMO-ágat, mozgásirányt, időbélyeget, képkockaszámot, kezdeti jelenlétet és bizonytalansági jelzéseket. Csak a meglévő videóelemzés végül megerősített gépjármű-ID-it használjuk. A személy- és kerékpárfelismerés változatlanul a korábbi ág része.

Az időablakok abszolút eseményszámot és az adott ablakra normalizált jármű/perc értéket adnak. Például három esemény tíz másodperc alatt 18 jármű/perc normalizált ráta, de a szimulációba három tényleges esemény kerül; nem generálunk belőle egy percnyi vagy órányi új forgalmat. Az utolsó, rövidebb ablak saját hosszával számolunk.

## Kézi referencia és pontosság

A referencia a kamera, a forrásvideó és a vonalbeállítás ellenőrzőösszegéhez kötött. Egymást nem fedő, ténylegesen végignézett szakaszokból és kézzel rögzített időpont/vonal/kategória/irány eseményekből áll. A program predikcióinak átmásolása nem kézi ellenőrzés.

Az egyeztetés egy-egy értelmű, a track-ID-től független. Azonos vonal, kategória és irány mellett, alapból legfeljebb egy másodperces eltéréssel keresünk párokat. A duplikált predikció fals pozitív marad. Precision, recall, eseményszintű F1, irányonkénti abszolút és relatív darabszámhiba készül. A nem annotált időszakok kimaradnak az értékelésből. Üres referencia és üres predikció nem igazol 100%-os pontosságot.

A beérkezési minősítés célja F1 ≥ 0,90, megfelelő mintán irányonként legfeljebb 10% darabszámhiba. Ezt csak legalább két szakasz, legalább 20 referenciaesemény és irányonként legalább 10 esemény mellett tekintjük elegendő mintának. Kis mintán az abszolút hibát is közöljük. A referencia emberi ellenőrzése, legalább két entry-ág és a felhasznált új belépések bizonytalansági jelzései is befolyásolják a minősítést. Az ellenirány értékelhető külön, de a beérkezési minősítéshez az inbound eseményeket kell ellenőrizni.

## SUMO-igény

Mért módban az érkezések nem Poisson-folyamatból készülnek. Az egyes járművek a megfigyelt kategóriával és a saját áthaladási időbélyegükkel indulnak; ehhez kizárólag a beállási idő adódik hozzá. Nincs időnyújtás vagy extrapoláció. A szimuláció vége a megfigyelt időtartam felfelé kerekített értéke és a beállási idő összege. Rövid videón ezért maradhatnak befejezetlen utak, különösen hosszú sablonágaknál.

A kezdőképen a kamerazónákban már szereplő ID-k külön kezdeti terhelést adnak. Ugyanezek az ID-k és a hozzájuk jelzett lehetséges ID-folytatások nem adnak új érkezést. Az ellenirány, a discharge, a bizonytalan esemény és az újabb entry-vonalon ismét megjelenő ID szintén nem duplázza meg az igényt. A kizárások a `flow-exclusions.json` állományban szerepelnek.

A `demand.json` megőrzi az új érkezések forrás-ID-ját, vonalát és időbélyegét. A futás `vehicle-demand.csv` fájlja járművenként tartalmazza az ütemezett és tényleges indulást, bejutási késést és célba érést. Az összesített mutatók külön mutatják a mért eseményből ütemezett, ténylegesen bejutott, bejutásra váró és célba ért járműveket. A meglévő fix/adaptív összehasonlítás változatlanul ugyanazt a generált igényt használja.

## A mellékelt demonstráció korlátja

A `config/cameras/busy-intersection.json` a helyben meglévő, húsz másodperces `busy_intersection.mp4` próbaprofilja. Két vonalat tartalmaz, de a kamera a kereszteződés közelét mutatja, és a gyalogosok gyakran kitakarják a járműveket. A vonalak ezért discharge szerepűek. A minta a számlálási működés demonstrációja, nem igazolt kétirányú upstream beérkezésmérés.

A mintához nincs ember által ellenőrzött referencia, így nem állítunk 90%-os valós eseményszintű F1-et. A szintetikus, előre ismert pályák tesztje külön ellenőrzi a számlálást, két időablakot, a kezdeti járművek kizárását és a SUMO-indulásokat. Ez nem helyettesíti a kamerás pontosságmérést.

