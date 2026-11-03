# Tesztelés

A projekt gyökeréből:

```bash
uv run --no-sync python -m pytest
uv run --no-sync python -m ruff check .
```

Windows alatt a `scripts/check.ps1` a teszteket, a Ruffot és a Python bytecode-fordítást is futtatja.

## Ellenőrzési szintek

- `pytest tests/unit`: konfigurációvalidáció, járműigény, fázissorrend és időkorlátok, detektálási sémák, régiók, becslés és rangsorolás. Nem igényel SUMO-t vagy modellfájlt.
- `pytest -m sumo`: valódi hálózatgenerálás, TraCI-futtatás, ismételhetőség, üres/túlterhelt hálózat és többmagos összehasonlítás. Hiányzó SUMO esetén kimarad.
- `pytest tests/integration/test_dashboard.py`: indulás, forgatókönyvváltás, szimulációindítás és ugyanazon eredmény ismételt megnyitása. A szimulációs teszthez SUMO kell.
- `pytest tests/unit/test_video.py`: ID-megerősítés, tiltott kategóriák kiszűrése, időrések, ismételt ID és kategóriaváltás.
- `pytest tests/unit/test_traffic_lights.py`: színek és kétértelmű jelzés, állapotmegerősítés, eltűnés, kézi típus és a közlekedőszámlálótól való elválasztás. A színváltás szintetikus képeken tesztelt; ez nem valós jelzőlámpás pontosságmérés.
- `pytest tests/integration/test_video_pipeline.py`: rövid videó dekódolása és H.264 exportja, előrehaladási callback, dashboard-futtatás és hibánál encoderlezárás. A felismerés ebben a tesztben helyettesített; FFmpeg és a vision függőségek szükségesek.

Az integrációs tesztek külön ideiglenes projektmásolatot használnak. Nem módosítják a projekt hálózati fájljait, és nem hagynak tesztfutásokat az `outputs/` alatt.

A biztonsági tesztek a fázissorrendet, a minimum/maximum zöldet, a sárgát és az összpiros időt ellenőrzik, hibás vagy hiányzó soradat mellett is. A szimulációs tesztek ellenőrzik a járműmérleget és a hálózatba még be nem jutott járművek beszámítását. Az összehasonlítás nem feltételezi, hogy az adaptív vezérlés jobb a fixnél.

A valódi YOLO-inferencia modellfüggő kézi ellenőrzés. Saját képpel:

```bash
uv run --no-sync python -m smarttraffic_ai detect --input sajat-kep.jpg
```

A tesztek nem töltenek le modellt vagy adatkészletet. A felismerési pontosság méréséhez külön annotált kameraképek szükségesek.

Az élő ág tesztjei hálózat nélkül ellenőrzik az Időkép-oldal feloldását, a `blob:` hibajelzést, a HLS-szegmens ütemezett dekódolását, az indítást/leállítást, az új számlálási munkamenetet és a hibás feldolgozó lezárását. Valódi kamerás próbához a dashboard **Videóelemzés → Élő forrás** nézetében indíts rövid elemzést; a kamera elérhetősége és tartalma változhat.

A YouTube-tesztek hálózat és telepített yt-dlp nélkül ellenőrzik a linkek normalizálását, a lejátszási listák elutasítását, a H.264 HLS-formátum kiválasztását, a 720p korlátot és a hiányzó forrás/futtató hibajelzését. A valódi YouTube-próba külön történik, mivel az élő videó és a külső szolgáltatás elérhetősége változhat.
