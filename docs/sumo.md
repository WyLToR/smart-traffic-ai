# SUMO-hálózat és TraCI

A SUMO külön folyamatban futó mikroszkopikus forgalomszimulátor. A Python TraCI protokollon keresztül lépteti, lekérdezi és a szimulációs jelzőlámpát módosítja. Alapforrás: [TraCI dokumentáció](https://sumo.dlr.de/docs/TraCI/).

## Hálózat

A `build-network` létrehozza a `sumo/networks/intersection.nod.xml`, `.edg.xml`, `.con.xml` forrásokat és `netconvert` segítségével a `.net.xml` hálózatot. A középső `J` csomóponthoz 250 méterre északi, déli, keleti és nyugati végpont csatlakozik. Sebességhatár 13,89 m/s; irányonként egy be- és kivezető sáv van.

Csak N→S, S→N, E→W és W→E kapcsolat engedélyezett. Kanyarodó kapcsolatot az állapotgenerátor visszautasít. Az `in_N_0` jellegű sávazonosító a modell szerződésének része; más hálózat importálása külön illesztést igényel.

A parancs a három forgatókönyvhöz route fájlokat és közvetlenül GUI-ban megnyitható `sumo/configs/*.sumocfg` állományokat is létrehoz. Ezek kis, verziókövethető minták; a futás közben generált adatok az `outputs/` alatt maradnak.

## Jelzőlámpák

A vezérlő a `getControlledLinks("J")` alapján azonosítja az indexekhez tartozó irányokat. Nem feltételez fix indexsorrendet. Az engedélyezett ciklus:

1. Észak–dél zöld, kelet–nyugat piros.
2. Észak–dél sárga, kelet–nyugat piros.
3. Összpiros.
4. Kelet–nyugat zöld, észak–dél piros.
5. Kelet–nyugat sárga, észak–dél piros.
6. Összpiros, majd visszatérés az első fázisra.

Az állapotokat a `setRedYellowGreenState` alkalmazza. A minimum/maximum zöld és az átmeneti idők a `SignalConfig` által validáltak. Hiányzó, negatív vagy nem véges soradat esetén az adaptív algoritmus fix időzítésre esik vissza. A maximum zöld mindig véges, így egyik irány kiszolgálási lehetősége sem marad el. Túlterhelésben ez nem garantál korlátos teljes járművárakozást.

## Futás és mérés

A lépésköz 1 s. A futás pontosan a forgatókönyv időhorizontjáig tart, nem ürítjük ki utána a hálózatot. A teleportálás tiltott (`--time-to-teleport -1`), mert különben mesterségesen eltűnő torlódás torzítaná a mérést. A kapcsolat `finally` ágban záródik.

A sorhossz forrása a négy bejövő sáv [getLastStepHaltingNumber](https://sumo.dlr.de/pydoc/traci/_lane.html) értéke, 0,1 m/s alatti sebességgel. Ez járműdarabszám, nem méter. Az idősort a ténylegesen az adott lépésben érvényes fázissal együtt mentjük.

A `tripinfo.xml` a SUMO saját, ellenőrzésre használható kimenete, befejezetlen utak kiírásával. A projekt saját mintavételezett várakozási mutatója eltérhet a SUMO `waitingTime` definíciójától. A pontos exportmezők: [optimization.md](optimization.md).
