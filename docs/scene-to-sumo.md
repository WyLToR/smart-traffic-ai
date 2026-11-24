# Képi adatokból SUMO-forgatókönyv

A SUMO a felismert közlekedési helyzet egyszerűsített változatát futtatja. A felismerés nem rekonstruálja az úthálózatot és a lámpaprogramot. A felhasználó ellenőrzi a bevezető ágakat, és sablont választ.

## Adatfolyam

`detect_file` / `process_video` → `analyze_image` / `analyze_video` → `TrafficScene` → `generate_scene` → a meglévő `run_simulation` TraCI-futtatója.

- `scene.py`: Pydantic-modellek, kézi/zónás megfeleltetés, pillanatnyi terhelés és időablakos videófoglaltság.
- `scene_sumo.py`: hálózat, járműtípusok, kezdeti pozíciók, érkezések, kész fájlcsomag és két vezérlés összehasonlítása.
- `dashboard_scene.py`: a meglévő dashboard új lapja. Paraméterváltozás után új generálást kér, így nem indul el észrevétlenül a korábbi helyzet.

Nincs új detektor vagy párhuzamos SUMO-futtató. A projekt aktuális detektorbeállításaival dolgozik; a PyTorch/CUDA környezetet a rekonstrukció nem módosítja.

## Megfigyelés és feltételezés

Az élő videóvizsgálat lezáráskor az `outputs/live-…/` mappába menti az `analysis.json`,
`observations.jsonl` és `preview.jpg` fájlokat. A SUMO-lapon a **Legutóbbi élő vizsgálat**
bemenet automatikusan kiválasztódik; újraindítás után a **Mentett eredmény** listában található.
A megfigyelt idő az első elemzett képkockától számít, ezért rövidebb lehet a kért vizsgálati
időnél. A teljes videót nem rögzítjük. A korábbi, pozícióexport nélküli élő vizsgálatot újra
kell futtatni. A 30 másodpercenként frissülő kameraképekből nem készül videós mozgástörténet.

| Adat | Eredet |
|---|---|
| Kategória, befoglaló téglalap, pillanatnyi darabszám | Meglévő YOLO-kimenet |
| Videóazonosító, időbélyeg és időköz | Meglévő tracking és dekódolás |
| Bevezető ág | Kézi hozzárendelés vagy ellenőrzött zóna; nincs automatikus égtájbecslés |
| Becsült sorhossz | Ismeretlen (`null`); a foglaltság nem bizonyít álló sort |
| Kezdeti gépjárművek | A kiválasztott pillanatnyi darabszám; álló helyzetük és pozíciójuk feltételezett |
| Későbbi érkezések | Konfigurált intenzitás, vagy foglaltsággal súlyozott intenzitási feltételezés |
| Sávok, úthossz, sebesség, kanyarodás, lámpaprogram | Sablon és felhasználói paraméter |

A `scene.json` a megfigyeléseket, becsléseket, `provenance` mezőket és feltételezéseket együtt tárolja. A személyek és kerékpárok darabszáma megmarad, de jelenleg csak a négy gépjárműtípus közlekedik a szimulációban. A parkolás és megállás nincs automatikusan elkülönítve; a nem szimulálandó találatok kézzel kihagyhatók.

Videónál az `observations.jsonl` minden képkocka idejét, időtartamát és normalizált tracking-pozícióit tartalmazza, az üres képkockákét is. Az elemző a végül megerősített azonosítókkal számol. Az időablakok foglaltsága a tényleges képkockaidőkkel súlyozott átlag, nem az ID-k új érkezésként történő megszámlálása. Hosszú takarás és ID-váltás továbbra is befolyásolhatja az eredményt.

A szimulációs időhorizont a választott forgalmi idő és az alapból 5 másodperces beállási idő összege. A videó időablakai a választott forgalmi időre skálázódnak. Az intenzitás jármű/óra, és nem válik automatikusan mért értékké.

Foglaltsággal súlyozott módban az alapérték jármű/óra/**megfigyelt ág**: az időablak teljes kerete az alapérték és a zónával vagy kézi hozzárendeléssel lefedett ágak számának szorzata, amelyet a megfigyelt gépjármű-foglaltság arányában osztunk szét. A kamerán nem látott ág nem kap érkezést, és a részét sem kapják meg a látott ágak. (2026. november 24. előtt a keretet a sablon összes ágának száma adta; két látott ágú négyágú csomópontnál ez a látott ágakon az alapérték kétszeresét eredményezte.)

Ez a konfigurált/foglaltsági becslési ág időkezelése. A külön **mért eseményes mód** az eredeti videóidőt tartja meg: nincs átskálázás vagy Poisson-generálás. A kezdetben jelen lévő ID-k és a nem beérkezést mérő vonalak nem adnak új érkezést. A forráshoz kötött referenciaértékelés, kísérleti mód és kizárások leírása: [Videós forgalommérés](traffic-flow.md).

## Generált hálózat és forgalom

Négyágú és T-csomópont választható, áganként 1–3 sávval, 50–2000 méteres ághosszal, 10–70 km/h sebességhatárral. A T-csomópont hiányzó ága állítható. A nem létező célirányok súlya kimarad, a fennmaradó kanyarodási arányok újranormalizálódnak. U-forduló nincs.

A `.nod.xml`, `.edg.xml` és `.con.xml` fájlokból a telepített `netconvert` hozza létre a `.net.xml` állományt. A lámpaprogram külön `signals.add.xml` fájl. Ez a SUMO által támogatott eljárás: [PlainXML](https://sumo.dlr.de/docs/Networks/PlainXML.html), [lámpaprogram betöltése](https://sumo.dlr.de/docs/Simulation/Traffic_Lights.html#loading_a_new_program).

A felismert gépjárművek indulási ideje 0. Sablonpozíciókat kapnak a megfelelő bevezető sávokon, kezdetben nulla sebességgel. Jelzőlámpás esetben a beállási idő alatt minden ág piros. A szükséges helyet a generátor ellenőrzi; túl sok kezdeti járműnél hosszabb ág vagy több sáv kell. A tényleges bejutást külön mérjük, így a SUMO által késleltetett beillesztés látható marad.

A későbbi érkezések külön, seedelt Poisson-folyamatból készülnek az intenzitási időablakok alapján. Járműtípus-arányuk a megfigyelésekhez kapcsolódik; hiányzó típusinformációnál személyautó az alapértelmezés. A `demand.json` megkülönbözteti a kezdeti és később érkező járműveket, és megadja a kiinduló/célágat.

## Vezérlés és mérés

A régi, csak egyenes kapcsolatokat tartalmazó példák megtartják az NS/EW vezérlést. Az új, kanyarodó hálózatok konzervatív módon egyszerre egy bevezető ágat szolgálnak ki: zöld → sárga → összpiros → következő ág. Így nem kap szabad jelzést a szembejövő balra kanyarodás az egyenes mozgással együtt. A minimum/maximum zöldet és az adaptív zöldidő-döntést ugyanaz a `Controller` adja; az `ApproachController` az ágak kiszolgálását illeszti hozzá. Jelzőlámpa nélküli sablonnál a SUMO elsőbbségi szabályai érvényesek, lámpaprogram-összehasonlítás nincs.

A fix és adaptív futás ugyanazt a generált hálózatot, explicit route fájlt, seedet és időhorizontot használja. A forgalmi fájlok ellenőrzőösszegei a mérési eredményben megmaradnak. Nem választunk győztest pusztán az átlagos várakozás alapján.

Az eredmények: `run-*/result.json`, `metrics.csv`, `timeline.csv`, `tripinfo.xml`. A járműmérleg tervezett = célba ért + megmaradt; megmaradt = bejutásra váró + hálózatban maradt. A sorhossz a bevezető sávokon 0,1 m/s alatt álló járművek száma, irányonként is az idősorban. A várakozás 1 s lépésekkel mintavett állásidő és bejutási késés; az átlag a teljes tervezett járműigényre vonatkozik. A beállási idő beleszámít. A célba értek utazási ideje csak a befejezett utakat jellemzi.

A `moving_vehicle_steps`, `red_stopped_vehicle_steps` és `warmup_departed` a valódi járműmozgás és a kezdeti beillesztés ellenőrzésére szolgál. A szimulációs futási idő és a felismerés feldolgozási ideje külön szerepel. A GUI a generált `simulation.sumocfg` fájlt futtatja; nem az előre elkészített demót.

Következő lépés a számlálóvonalas mérés ellenőrzése megfelelően belátható, fix beérkezési kamerán, ember által ellenőrzött referenciával. A sablongeometria és a kezdeti sorpozíciók továbbra is feltételezések; a rendszer nem pontos digitális másolat.
