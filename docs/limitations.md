# Korlátok és következő feladatok

- A hálózat egyetlen kereszteződés, irányonként egy sávval és csak egyenes haladással. Nincs kanyarodás vagy gyalogosforgalom.
- A három forgatókönyv feltételezett Poisson-érkezést használ, kezdetben üres hálózattal. A detektor járműkategóriáit az adapter nem képezi le külön SUMO-járműtípusokra.
- Egy állóképből nincs igazolt sebesség-, sorhossz- vagy érkezésbecslés. A forgatókönyv-adapter külön megadott intenzitásból dolgozik.
- A videó követett ID-ket számol, nem hitelesített különböző közlekedőket. Takarás után ugyanaz új ID-t kaphat; a nagyon rövid találatok a megerősítési küszöb miatt kimaradnak. A látható idő nem egyenlő a forgalmi várakozással.
- A jelzőlámpa színe képheurisztikával becsült, típusa kameránként megadott. Az általános YOLO-lámpatalálat típusa ismeretlen. Tükröződés, takarás vagy elcsúszó kijelölés hibás állapotot adhat; a program nem következtet ebből automatikusan szabálysértésre vagy forgalmi elsőbbségre.
- Nincs kamerás pontosságmérés, vonalátlépés-számlálás vagy finomhangolás. A régiók kameránként kalibrálandók. A videóeredményből még nem készül automatikus SUMO-forgatókönyv.
- Az élő kapcsolat HTTP(S)/RTSP forrást, egyszerű MPEG-TS HLS-t és az Időkép beágyazott HLS-lejátszóját kezeli. A böngészős `blob:` cím önmagában nem videóforrás. Titkosított, fMP4- és byte-range HLS nem támogatott. A szolgáltató késése és a mintavétel miatt a látható idő becslés. A kapcsolat megszakadása leállítja az elemzést; az új indítás külön számlálást kezd.
- Frissülő JPEG/PNG kameraképnél csak képenkénti észlelés készül. A 30 másodperces lekérés nem tesz lehetővé folyamatos követést, egyedi járműösszesítést vagy láthatósági időmérést; a két kép között elhaladó közlekedők kimaradhatnak. Kameranézet-váltáskor sem kapcsol össze azonosítókat. A pillanatkép lámpaszíne nem időben megerősített jelzés.
- A YouTube-bemenet nyilvánosan elérhető H.264 HLS-forrást használ, legfeljebb 720p felbontással. Nem minden videó kínál ilyen formátumot. A feloldás külön függőséget és JavaScript-futtatót igényel; a YouTube változásai vagy korlátozásai megszakíthatják. A forrás újraindításkor újra feloldódik, kapcsolatvesztéskor nincs automatikus újracsatlakozás.
- Az optimalizálás véges jelöltkészletet vizsgál, alapból két maggal. Az eredmény az időhorizonttól és a célfüggvény súlyaitól is függ.
- Túlterhelésben a maximum zöld sem garantál rövid várakozást. A projekt nem konfigurál balesetet vagy sávlezárást, bár a SUMO külön modellezéssel kezelhet ilyen helyzeteket.
- A dashboard helyi bemutatóalkalmazás. Nincs többfelhasználós kezelés vagy automatikus eredménytakarítás. Az eredmény-JSON helyi elérési utakat is tartalmaz.

Következő feladatok: régiókalibráció, majd a felismerés és forgalombecslés összevetése kézzel annotált adatokkal.

Külső képek és modellek felhasználási feltételeit a forrásnál kell ellenőrizni. A feltöltött képek helyben, az `outputs/` alatt maradnak; megőrzésükről a felhasználó gondoskodik. Nincs személyazonosítás vagy rendszámfelismerés.
