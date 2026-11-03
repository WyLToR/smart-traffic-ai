# Vezérlés, keresés és mérési definíciók

## Fix és adaptív szabály

A fix alapvezérlő mindkét fő iránynak 25 s zöldet ad. Az adaptív változat legalább 12 és legfeljebb 40 s zöldet használ. Ha a másik irányban is várnak, és az aktív sor elfogyott, vagy eltelt a `min(40, 12 + 2 × aktív sorhossz)` célidő, a minimum zöld után sárgára vált. Legkésőbb 40 s után mindig vált. A sárga 3 s, az összpiros 2 s. Ezek az értékek konfigurálhatók; a keresés csak validált zöldidőt módosít.

A szabály determinisztikus, nem tanuló optimalizáló. A YOLO objektumfelismerés az AI-komponens; ez a vezérlő heurisztika. A minimum/maximum korlátok és az állapotátmenetek unit tesztekkel ellenőrzöttek.

## Keresés

A `config/optimization.yaml` alapértékei: észak–déli és kelet–nyugati zöldenként 15, 25, 35 s; magok 42 és 73. A 3×3 fix kombinációból a 25/25 alap nem ismétlődik, és ehhez külön adaptív jelölt társul: összesen 10 jelölt, 20 futás.

Minden jelölt ugyanazt a szcenáriót, hálózatot, időhorizontot és magonként ugyanazt az explicit járműigényt használja. A rendszer a hálózat és route SHA-256 értékét is egyezteti. A keresési teret a futás előtt validáljuk. A jelöltek pontszámát magonként számítjuk, majd átlagoljuk. Holtversenyben a jelölt neve ad determinisztikus sorrendet.

```text
score = mean_wait
      + max_wait_weight × max_wait
      + remaining_weight × remaining / max(1, demand)
```

Alap súlyok: `max_wait_weight = 0.1`, `remaining_weight = 60`. Minden tag másodperc jellegű költségként értelmezhető. A súlyokat a csapatnak a vizsgálati cél szerint kell megválasztania; nem kalibrált társadalmi költségek. A maximumvárakozás-tag korlátozza a kirívóan rossz kiszolgálás kedvezőnek értékelését, de nincs külön irányonkénti méltányossági optimum.

## Exportált metrikák

Jelölje `T` a futás végét, `dᵢ` a tervezett indulást, `aᵢ` a tényleges bejutás idejét. A még be nem jutott járműnél `aᵢ = T`. A lépés utáni TraCI-időből egy másodperc levonásával rögzítjük a lépés kezdetén történt indulást/érkezést. A route indulásai egész másodpercesek.

| Mező | Definíció és adatforrás |
|---|---|
| `demand` | A teljes explicit route-lista járműszáma, minden tervezett indulás `< T`. |
| `departed` | A `simulation.getDepartedIDList` halmazába került járművek. |
| `arrived` | A `simulation.getArrivedIDList` alapján célba értek száma. |
| `pending` | A tervezett, de még be nem jutott járművek száma. |
| `active_at_end` | Bejutott, de célba nem ért járművek száma. |
| `remaining` | `demand - arrived = pending + active_at_end`. |
| `waiting_at_end` | A négy bejövő sáv végső álló járműszáma plusz `pending`. A kifelé mozgókat nem sorolja ide. |
| `total_stopped_seconds` | Minden aktív jármű 0,1 m/s alatti sebességgel mért, másodpercenkénti mintáinak összege (`vehicle.getSpeed`). A teljes hálózatot figyeli. |
| `total_insertion_delay` | Az összes járműre `max(0, aᵢ-dᵢ)`, beleértve a még be nem jutottakat is. |
| `mean_wait` | Járművenként a mintavételezett állásidő + bejutási késés, majd az összes tervezett járműre átlagolva. |
| `max_wait` | A fenti járművenkénti összeg maximuma; üres igénynél 0. |
| `mean_travel_completed` | Tényleges bejutástól célba érésig eltelt idő, csak a befejezett utakra. Ha nincs ilyen út, `null`. Nem tartalmazza a bejutási késést. |
| `mean_queue`, `max_queue` | A négy bejövő sáv `getLastStepHaltingNumber` összege, az időhorizont összes másodpercére vett átlag/maximum. Egység: jármű. |
| `collision_vehicle_events` | A lépésenkénti `getCollidingVehiclesNumber` összege. Járműesemények száma, nem egyedi balesetek száma. A tesztelt esetekben 0 az elvárás. |

A várakozás 1 s felbontású mintavételi mutató, ezért nem azonos a SUMO tripinfo `waitingTime` mezőjével. Például a kezdeti nulla sebességű bejutási minta is növelheti. A [SUMO tripinfo definíciói](https://sumo.dlr.de/docs/Simulation/Output/TripInfo.html) külön olvashatók. Minden stratégia ugyanazt a mérési szabályt kapja.

A hálózaton kívüli torlódást a `pending` és a bejutási késés méri, nem a belső sorhossz. A még mozgó, célba nem ért járműveket a `remaining` tag bünteti. Véges időhorizont miatt az eredményt több időtartammal és több maggal is érdemes később ellenőrizni. Az átlagolás jelenleg egyenlő súlyú; konfidenciaintervallum nincs.

A `runs.csv` nyers futásszintű metrikákat és elérési utakat tárol. A `comparison.csv` magok fölötti átlagokat tartalmaz, ezért az átlagos áthaladásszám lehet törtszám. Az adaptív jelölt mellett szereplő `ns_green`/`ew_green` a hibás adat esetén használt fix visszaesési érték; az adaptív tényleges zöldhosszak az idősortól függnek.
