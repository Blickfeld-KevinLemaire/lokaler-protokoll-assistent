# Konzept: Live-Übertragung und laufende Transkription

Stand: 13.10.2026. Das ist ein **Konzept**; umgesetzt sind die Übertragung (Phase 1, noch nicht auf einem Gerät getestet),
auf der **PC-Seite** die blockweise Live-Transkription, die automatische Auswertung und der Status fürs Gerät
(Phase 2 und 3, siehe unten) und für das **S3 mit Bildschirm** das Senden während der Aufnahme mit Statusanzeige
(siehe „Umsetzung am S3“ unten); S3-AUDIO und C6 sind noch offen. Es beschreibt, wie die Aufnahmegeräte
(`esp32-s3/lcd`, `esp32-s3/audio`, später auch `esp32-c6`) und die Protokoll-Software zusammenarbeiten sollen.

## Ziel

Ist ein Gerät im WLAN der Software, schickt es die Aufnahme **während der Aufnahme** in kleinen Stücken an den PC.
Dort wird sofort transkribiert. Wenn die Aufnahme zu Ende ist, soll das Ergebnis so schnell wie möglich vorliegen:

1. Der Nutzer gibt vorher einen **Auftrag** vor (z. B. „Wir haben ein Meeting. Die wichtigsten ToDos: wer macht was bis wann?“).
   Er dient als Systemprompt der Auswertung, so wie er heute in der Software von Hand eingegeben wird.
2. Nach Abschluss zeigt das Gerät **„Transkription erfolgreich“ mit grünem Häkchen** (S3 mit Bildschirm) bzw. einen grünen Ring (S3 ohne Bildschirm).
3. Über „Frag mein Meeting“ kommt die Antwort auf den Auftrag zurück aufs Gerät, zuerst als Text, in einem späteren Schritt per KI-Sprachausgabe.

## Entscheidungen (12.10.2026)

| Frage | Entscheidung |
|---|---|
| Chunk-Länge | **15 Sekunden** für die Übertragung |
| Überlappung | bei der **Transkription** die vorhandenen 10 s zwischen den 600-s-Chunks (Phase 2, statt eigener 2–3 s an Zwangsschnitten); die Übertragung braucht keine (siehe unten) |
| Verbindung weg | Das Gerät **behält seine lokale Kopie** (SD oder Flash, egal) bis der PC „fertig“ meldet. Es geht nichts verloren. |
| Gerät nicht im WLAN der Software | Wie heute: normale Aufnahme, später als ganze Datei hochladen; die Software zerlegt sie selbst in Chunks. |
| Ordner | **Pro Meeting getrennt**, gruppiert nach Tag. Keine gemeinsame Ablage aller Chunks. |
| Zugang | **Token** pro Gerät, **umgesetzt**: in der Software erzeugt, einmal angezeigt, nur als Hash gespeichert; es legt auch den Gerätenamen fest. Orte (Heimnetz, Büro …) als Profile kommen später. Der PC öffnet den Dienst nur auf Wunsch (Opt-in). |
| Übertragung | **Ein Protokoll für beides**, umgesetzt: wiederaufnehmbarer Upload mit Byte-Versatz nach [`GERAETE-SCHNITTSTELLE.md`](../../protokoll_assistent/GERAETE-SCHNITTSTELLE.md). Es trägt die ganze Datei, die offline entstanden ist, und später genauso das Anhängen während der Aufnahme. Eine eigene Sitzungs-Schnittstelle braucht Phase 1 nicht. |
| Auftrag wählen | Am PC **oder** am Gerät per Dropdown aus einer vom PC gelieferten Liste |
| Wartezeit nach dem Ende | so kurz wie möglich (Maßnahmen unten) |

## Ablauf

**Online (Gerät erreicht die Software):**

1. Gerät holt die Liste der Aufträge, Nutzer wählt einen (oder der PC hat einen vorgewählt).
2. Gerät fragt mit `GET /api/v1/aufnahmen/<Name>` das nächste erwartete Byte ab (umgesetzt; eine eigene Sitzung braucht es dafür nicht).
3. Das Gerät schreibt weiter wie bisher in seine lokale Datei (Ogg-Opus) und schickt alle 15 s die **neuen Bytes** dieser Datei
   (`PUT` mit `X-Offset`). Der PC hängt sie an. So entsteht dort die lückenlose, jederzeit abspielbare Aufnahme, ohne Nähte
   zwischen den Stücken. Die Software kann das; das S3 mit Bildschirm sendet so (S3-AUDIO und C6 noch nicht).
4. Jede Übertragung wird bestätigt. Fehlt eine, sendet das Gerät beim nächsten Mal ab dem letzten bestätigten Byte (**Wiederaufnahme**, umgesetzt).
5. Am Ende meldet das Gerät „Ende“ mit Gesamtgröße und SHA-256 (leeres `PUT` mit `X-Gesamtgroesse` und `X-SHA256`, umgesetzt).
   Erst wenn der PC „fertig“ meldet, darf das Gerät seine Kopie löschen.
6. Das Gerät fragt den Status ab (Polling, kein eigener Server nötig) und zeigt ihn an.

**WLAN fällt mitten in der Aufnahme aus:** Die Aufnahme läuft lokal ungestört weiter. Kommt das WLAN zurück, sendet das Gerät den
Rückstand ab dem letzten bestätigten Byte; die Transkription holt auf. Kommt es nicht mehr rechtzeitig zurück, macht das
Gerät beim nächsten Mal ab dem letzten bestätigten Byte weiter: derselbe Aufruf wie beim normalen Upload einer ganzen Datei.

**Offline (anderes WLAN, kein WLAN):** wie heute, eine Aufnahme, später als Datei hochladen.

## Ordner am PC

```
daten/geraete-eingang/
  2026-10-12/                              ein Ordner pro Tag
    091500_S3-Audio_Projekt-Weekly/        ein Ordner pro Meeting: Uhrzeit_Gerät_Titel
      sitzung.json                         Gerät, Auftrag, Start, Zustand, Token-Name
      aufnahme.opus                        lückenlos angehängt
      teile/000001.teil, 000002.teil …     empfangene 15-s-Stücke (nach Abschluss löschbar)
      transkript/live.jsonl, fertig.json   wachsendes bzw. fertiges Transkript
      auswertung/auftrag.md, protokoll.md, ergebnis.json
```

Ganze Dateien, die später nachgeliefert werden, landen wie heute im normalen Eingang und laufen durch die vorhandene Verarbeitung.
So arbeitet Phase 1 bisher für alle Aufnahmen: fertige Dateien als `<Gerät>_<Dateiname>` im Eingangsordner, Teilstände bis zum
Abschluss im versteckten Unterordner `.empfang/`. Die Ordner pro Meeting kommen mit den Aufträgen (Phase 3).

## Schnittstelle

Alle Aufrufe mit `Authorization: Bearer <Token>`. Der PC speichert nur einen Hash des Tokens. Der umgesetzte Teil ist
verbindlich in [`GERAETE-SCHNITTSTELLE.md`](../../protokoll_assistent/GERAETE-SCHNITTSTELLE.md) beschrieben; der Rest ist
eine Skizze.

| Aufruf | Zweck | Stand |
|---|---|---|
| `GET /api/v1/hallo` | Erreichbar? Gilt das Token? Liefert Version und größte Stückgröße; später auch die Liste der Aufträge | umgesetzt (ohne Aufträge) |
| `GET /api/v1/aufnahmen/<Name>` | nächstes erwartetes Byte | umgesetzt |
| `PUT /api/v1/aufnahmen/<Name>` | Bytes ab `X-Offset` anhängen; mit `X-Gesamtgroesse` und `X-SHA256` abschließen. Für die ganze Datei wie für das Anhängen während der Aufnahme | umgesetzt |
| `GET …/status` | `empfang`, `wartet`, `transkription`, `auswertung`, `fertig`, `fehler`, `unbekannt` | umgesetzt (Software und S3 mit Bildschirm) |
| `GET …/ergebnis` | Kurzfassung des Auftragsergebnisses für das Display | Skizze (Phase 4) |
| `POST …/frage` | „Frag mein Meeting“, später auch als Sprache | Skizze (Phase 4/5) |

Die früher skizzierten Sitzungs-Aufrufe (`POST /api/v1/sitzungen`, `…/teile`, `…/ende`) braucht es nicht: Der Upload mit
Byte-Versatz leistet dasselbe. Wo Auftrag und Status später hängen (an der Aufnahme oder an einer Sitzung), ist offen.

Der Dienst ist **in der Software abschaltbar** (Standard: aus). Bis dahin öffnete die Anwendung bewusst keinen Port;
`SECURITY.md` ist im Pull Request der Anwendung entsprechend nachgezogen. Das Token wird in der Software erzeugt, angezeigt und
lässt sich widerrufen; auf dem Gerät liegt es heute in `main/Wireless/server_config.h` (in `.gitignore`), **nie im Repository**.
Die Firmware liest alle Verbindungs-Einstellungen nur über `vermerk_konfig.h`, damit sie später ohne Änderung am Upload aus
dem NVS kommen können (z. B. per USB aus der Anwendung eingerichtet).

**Orte:** Das Gerät kennt mehrere Profile (WLAN-Name, Adresse der Software, Token) und wählt nach dem verbundenen WLAN.
Passt keines, zeichnet es nur lokal auf.

## Auftrag

Die Software hält eine Liste benannter Aufträge („Meeting: ToDos“, „Entscheidungen“ …). Wahl am PC oder am Gerät:
S3 mit Bildschirm per Dropdown, S3 ohne Bildschirm mit KEY3 (Wechsel durch die Liste, Anzeige am LED-Ring, später
Ansage). Der Auftrag geht als `ProtocolSettings.system_prompt` nur für diese Sitzung in die Auswertung, die gespeicherte
Vorlage bleibt unberührt.

## Wartezeit nach dem Ende: wo sie entsteht und was hilft

Nach dem Ende der Aufnahme bleiben (nach heutigem Stand) vier Schritte: letztes Stück, Sprechertrennung, Auswertung durch
das Sprachmodell, Export. Maßnahmen, geordnet nach erwartetem Nutzen:

1. **Blockweise verarbeiten, sobald ein Block da ist** (Phase 2): Die Software zerlegt heute schon in 600-s-Chunks mit 10 s Überlappung
   (`services/chunking_service.py`). Ist ein Block angekommen, laufen Transkription und Stufe 1 der Auswertung für ihn noch während des Meetings.
   Beim Ende ist nur noch der letzte Block offen. Ein zweites, feineres Schnittschema lohnt sich nicht (siehe Phase 2).
2. **Auswertung vorbereiten, solange das Meeting läuft:** Die Software fasst heute Gruppen von Chunks zusammen und führt sie am Ende zusammen. Die Teilzusammenfassungen können
   schon während des Meetings entstehen; am Ende fehlt nur der letzte Teil und die Zusammenführung.
3. **Modelle warm halten, aber auf die richtige Hardware verteilen:** Gemessen (siehe [`messung-phase0.md`](messung-phase0.md)) belegt Whisper ca. 3 GB und das 8B-Sprachmodell ca. 7 GB der 8 GB
   Grafikspeicher, **beide zusammen passen nicht**. Entweder läuft Whisper live auf dem **Prozessor** (3,2-fache Echtzeit reicht für 15-s-Stücke) und die Grafikkarte gehört dem Sprachmodell,
   oder es kommt ein 4B-Modell zum Einsatz, das neben Whisper passt. Außerdem muss Ollama das Modell nach dem letzten Aufruf entladen: Sonst scheitert die nächste Transkription mit „CUDA out of memory“.
4. **Sprechertrennung entkoppeln:** pyannote arbeitet heute über die ganze Aufnahme. Entweder reicht die Zeit (messen), oder Sprecher-Merkmale werden laufend je
   Sprechabschnitt berechnet und am Ende nur noch gruppiert.
5. **Früh melden:** Das Häkchen erscheint, sobald das **Auftragsergebnis** da ist. Word-Datei, SRT & Co. entstehen danach im Hintergrund.
6. **Zwei Stufen:** erst „Transkript fertig“, dann „Auswertung fertig ✓“. Der Nutzer sieht den Fortschritt, statt zu warten.
7. **Kurzer Auftrag, kurze Antwort:** ein auf ToDos zugeschnittener Auftrag erzeugt weniger Text als ein volles Protokoll und ist schneller.

**Gemessen (Phase 0, siehe [`messung-phase0.md`](messung-phase0.md)):** Bei 73 Minuten Aufnahme dauert die Verarbeitung heute ca. 25 Minuten, davon 84 % Sprachmodell
(Transkription 79 s, Sprechertrennung 143 s). Das Sprachmodell ist der Engpass, nicht die Transkription.

## Phasen (überarbeitet)

| Phase | Inhalt | Ergebnis |
|---|---|---|
| **0 – Messen** (erledigt, [`messung-phase0.md`](messung-phase0.md)) | Zeit je Schritt der vorhandenen Verarbeitung auf diesem PC bei 8 und 73 Minuten | Das Sprachmodell ist der Engpass; Whisper und das 8B-Modell passen nicht zusammen auf die Karte; Fehler „CUDA out of memory“ bei zwei Aufnahmen kurz nacheinander gefunden |
| **1 – Übertragung** (umgesetzt; Upload-Code in QEMU gegen den echten Empfang getestet, noch nicht auf einem Gerät) | Dienst in der Software (Opt-in, Token je Gerät, Token-Verwaltung), wiederaufnehmbarer Upload nach [`GERAETE-SCHNITTSTELLE.md`](../../protokoll_assistent/GERAETE-SCHNITTSTELLE.md); Firmware (`components/vermerk_upload/`): 256-KiB-Stücke mit Byte-Versatz, SHA-256 beim Abschluss, Wiederaufnahme auch nach Neustart, lokale Kopie bleibt bis „fertig“, wachsende Wartezeit je Datei, danach vorhandene Verarbeitung | Ganze Aufnahmen kommen sicher an, nichts geht verloren. Dasselbe Protokoll trägt später das Anhängen während der Aufnahme |
| **2 – Blockweise Verarbeitung während des Meetings** (PC-Seite umgesetzt: `services/live_service.py`; Firmware am S3 mit Bildschirm umgesetzt, S3-AUDIO und C6 offen) | Die vorhandenen 600-s-Chunks (`services/chunking_service.py`, 10 s Überlappung) verarbeiten, sobald ein Block angekommen ist: Transkription und Stufe 1 der Auswertung je Block (gemessen im Mittel 73 s je Block) laufen während des Meetings. Whisper auf dem Prozessor oder kleineres Sprachmodell, Sprachmodell nach Gebrauch entladen. **Kein** eigenes Schnittschema mit 5–30-s-Stücken: nach Phase 0 sind 84 % der Zeit Sprachmodell, die Transkription nur ca. 79 s von 25 min. Firmware: Anhängen während der Aufnahme (am S3 mit Bildschirm umgesetzt, siehe Risiken) | spart Transkription und Stufe 1 nach dem Ende (bei 73 min ca. 590 s Stufe 1 + 79 s Transkription); vermeidet den Speicherfehler |
| **3 – Auftrag und schnelle Auswertung** (PC-Seite umgesetzt, mit einem festen Auftrag in den Einstellungen; Statusanzeige am S3 mit Bildschirm umgesetzt; Auswahl am Gerät, S3-AUDIO und C6 offen) | Aufträge (Dropdown am PC/Gerät), knappes Auftragsergebnis statt vollem Protokoll, früher Status, „Transkription erfolgreich ✓“ | Der beschriebene Ablauf; Wartezeit grob 2–5 min statt ca. 25 min (zu bestätigen) |
| **4 – Ergebnis aufs Gerät** | Kurzfassung/ToDos auf dem Display, „Frag mein Meeting“ als Text | Rückmeldung am Gerät |
| **5 – Sprache** | Frage per Mikrofon, KI-Sprachausgabe der Antwort | später |

## Technische Risiken und offene Punkte

* **Lesen während des Schreibens** (gelöst am S3 mit Bildschirm mit dem RAM-Ringpuffer, siehe unten; die Einschätzung blieb): Liest das Gerät seine Datei für die Übertragung, während der Encoder noch schreibt,
  müssen die Ogg-Seiten (ca. 1 s) vollständig geschrieben und gesichert sein, bevor sie gesendet werden; FAT und der Puffer von `fwrite` machen das
  unzuverlässig. Besser: Der Encoder gibt jede fertige Ogg-Seite zusätzlich über einen kleinen RAM-Ringpuffer an den Sender, der sie mit
  `PUT` (`X-Offset`) anhängt. Läuft der Ring über (WLAN weg), fällt der Sender auf das Lesen der Datei ab dem letzten bestätigten Byte zurück,
  wenn die Aufnahme beendet ist. Die Prüfsumme für den Abschluss rechnet der Sender mit, wie heute beim Upload.
* **RAM:** Beim C6 knapp (ca. 115 KB frei beim Aufnehmen, Upload-Puffer heute schon nur 4 KB); der Ring muss dort klein bleiben (wenige KB, bei
  24 kbit/s sind das wenige Sekunden). Bei den S3 mit 8 MB PSRAM deutlich entspannter.
* **Stromverbrauch:** Alle 15 s Senden ist für den Funk günstig, wenn das Gerät dazwischen im Ruhezustand bleibt.
* **Zeit:** Die Sitzungsordner brauchen die Uhrzeit. Der PC vergibt sie; die Geräte müssen keine Uhr stellen.
* **Sicherheit:** HTTP im eigenen Netz mit Token je Gerät ist umgesetzt; `SECURITY.md` ist im Pull Request der Anwendung nachgezogen (Port nur auf Wunsch).
  Mitlesen im selben WLAN verhindert das Token nicht. Für fremde Netze ist TLS nötig (auf dem ESP32 machbar, kostet RAM, auf dem C6 knapp).
* **Umsetzung am S3 mit Bildschirm** (`components/vermerk_upload/vermerk_live.c`, `vermerk_ring.c`):
  * Der Encoder gibt jede fertige Ogg-Seite über einen Haken in einen **Ringpuffer im PSRAM** (1 MB, ca. 5,7 min bei 24 kbit/s;
    Reserve 512 oder 256 KB, wenn weniger frei ist). Der Haken kopiert nur. Der Puffer ist lock-frei (ein Erzeuger, ein
    Verbraucher) und überschreibt nie Unbestätigtes; die Logik ist auf dem PC getestet (`test/host/`).
  * Der Upload-Manager, der während der Aufnahme sonst ruht, sendet alle 15 s die neuen Bytes (`PUT` mit `X-Offset`, höchstens
    64 KB je Anfrage; bei Rückstand sofort weiter). Vor dem ersten Stück fragt er den Stand ab; ist er nicht 0, wird nicht live
    gesendet. Nach dem Stopp macht der normale Upload dort weiter, wo die Software steht, und schließt ab (Größe, SHA-256).
  * Das Live-Senden endet still bei Ringpuffer-Überlauf (Ziel lange weg), bei einer Lücke (die Software kennt weniger, als
    schon verworfen ist) und bei dauerhafter Ablehnung (Token, Name). **Nichts geht verloren**, die Aufnahme liegt immer ganz
    auf der SD-Karte.
  * Nach „fertig“ fragt das Gerät alle 3 s `GET …/aufnahmen/<Name>/status` ab und zeigt „TRANSKRIPTION WIRD VERARBEITET“, am Ende
    ca. 4 s ein grünes Häkchen über den ganzen Bildschirm, danach dauerhaft „✓ TRANSKRIPTION ERFOLGREICH“ (grün) bis zur nächsten
    Aufnahme bzw. „VERARBEITUNG FEHLGESCHLAGEN“ (rot).
  * Geprüft: Host-Tests (Status-Leser gegen die **echten** Antworten der Software, Entscheidung für Live-Stücke, Ringpuffer inkl.
    Zähler-Überlauf), Bau für S3 mit Bildschirm und S3-AUDIO. Auf dem Gerät ist die Aufnahme mit Live-Senden noch zu prüfen.
  * Offen: S3-AUDIO (LED-Ring statt Display: grüner Ring bei „fertig“) und C6 (kein PSRAM: kleiner Ringpuffer im internen RAM
    oder Lesen der Datei); Auswahl des Auftrags am Gerät.
* **Stand der Umsetzung:** Phase 1 und die PC-Seite von Phase 2/3 sind in der Anwendung; das S3 mit Bildschirm sendet während der
  Aufnahme und fragt den Status ab (siehe oben). Die PC-Seite ist mit echtem Whisper (CPU) und einer echten Geräteaufnahme geprüft,
  die Firmware mit Host-Tests und im Bau; der Ablauf Gerät – Netz – PC noch nicht auf einem Gerät. Der Rest dieser Datei ist ein
  Konzept und ändert weder die Anwendung noch die Firmware.
* **Wirkung der Live-Transkription:** Sie arbeitet mit einem gleitenden Fenster (`services/live_service.py`): ab 20 s neuem Audio wird vom
  letzten sicheren Punkt bis jetzt transkribiert (höchstens 45 s), fertige Sätze gelten als bestätigt, das abgeschnittene Ende wird beim
  nächsten Mal neu mitgerechnet. Das Transkript steht so mit etwa 20 bis 40 s Verzögerung bereit. Die Verarbeitung der fertigen Datei
  (weiter in 600-s-Chunks mit 10 s Überlappung, damit Zusammenführung und Auswertung unverändert bleiben) übernimmt die bestätigten
  Segmente und rechnet nur den Rest. Auch die **Teilzusammenfassungen** der Auswertung (Stufe 1 und 2 des Sprachmodells) werden
  schon während der Aufnahme berechnet (`services/live_auswertung_service.py`): sobald der Text eines Auswertungsabschnitts (Standard 180 s statt 600 s, damit nach dem Ende nur wenig offen bleibt) feststeht, auf der
  Grafikkarte neben Whisper auf dem Prozessor. Jedes Ergebnis wird nur bei übereinstimmender Eingabe (Modell, Auftrag, Text) übernommen;
  dafür bekommt das Modell den Text ohne Sprecherangaben, weil die Sprechertrennung erst am Ende vorliegt.
