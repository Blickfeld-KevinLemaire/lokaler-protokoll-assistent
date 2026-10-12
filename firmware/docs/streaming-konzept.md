# Konzept: Live-Übertragung und laufende Transkription

Stand: 12.10.2026. Das ist ein **Konzept, noch nicht umgesetzt**. Es beschreibt, wie die Aufnahmegeräte
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
| Überlappung | bei der **Transkription** ca. 2–3 s dort, wo mitten in der Sprache geschnitten werden muss; die Übertragung braucht keine (siehe unten) |
| Verbindung weg | Das Gerät **behält seine lokale Kopie** (SD oder Flash, egal) bis der PC „fertig“ meldet. Es geht nichts verloren. |
| Gerät nicht im WLAN der Software | Wie heute: normale Aufnahme, später als ganze Datei hochladen; die Software zerlegt sie selbst in Chunks. |
| Ordner | **Pro Meeting getrennt**, gruppiert nach Tag. Keine gemeinsame Ablage aller Chunks. |
| Zugang | **Token** pro Gerät und Ort (Heimnetz, Büro …), später individuell einrichtbar. Der PC öffnet den Dienst nur auf Wunsch (Opt-in). |
| Auftrag wählen | Am PC **oder** am Gerät per Dropdown aus einer vom PC gelieferten Liste |
| Wartezeit nach dem Ende | so kurz wie möglich (Maßnahmen unten) |

## Ablauf

**Online (Gerät erreicht die Software):**

1. Gerät holt die Liste der Aufträge, Nutzer wählt einen (oder der PC hat einen vorgewählt).
2. Gerät legt eine **Sitzung** an. Der PC antwortet mit Sitzungsnummer und dem nächsten erwarteten Byte.
3. Das Gerät schreibt weiter wie bisher in seine lokale Datei (Ogg-Opus) und schickt alle 15 s die **neuen Bytes** dieser Datei.
   Der PC hängt sie an. So entsteht dort die lückenlose, jederzeit abspielbare Aufnahme, ohne Nähte zwischen den Stücken.
4. Jede Übertragung wird bestätigt. Fehlt eine, sendet das Gerät beim nächsten Mal ab dem letzten bestätigten Byte (**Wiederaufnahme**).
5. Am Ende meldet das Gerät „Ende“ mit Gesamtgröße. Erst wenn der PC „fertig“ meldet, darf das Gerät seine Kopie löschen.
6. Das Gerät fragt den Status ab (Polling, kein eigener Server nötig) und zeigt ihn an.

**WLAN fällt mitten in der Aufnahme aus:** Die Aufnahme läuft lokal ungestört weiter. Kommt das WLAN zurück, sendet das Gerät den
Rückstand ab dem letzten bestätigten Byte; die Transkription holt auf. Kommt es nicht mehr rechtzeitig zurück, wird beim
nächsten Mal die Sitzung ergänzt oder die ganze Datei normal hochgeladen.

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

## Schnittstelle (Skizze)

Alle Aufrufe mit `Authorization: Bearer <Token>`. Der PC speichert nur einen Hash des Tokens.

| Aufruf | Zweck |
|---|---|
| `GET /api/v1/hallo` | Erreichbar? Liefert Version, Liste der Aufträge, gewünschte Chunk-Länge |
| `POST /api/v1/sitzungen` | Sitzung anlegen (Gerät, Auftrag, Codec); Antwort: Sitzungsnummer, nächstes Byte |
| `PUT /api/v1/sitzungen/{id}/teile` | Bytes ab `X-Offset`, mit Prüfsumme; Antwort: nächstes Byte |
| `POST /api/v1/sitzungen/{id}/ende` | Aufnahme beendet, Gesamtgröße und Dauer |
| `GET /api/v1/sitzungen/{id}/status` | `läuft`, `transkription`, `sprecher`, `auswertung`, `fertig`, `fehler` + Fortschritt |
| `GET /api/v1/sitzungen/{id}/ergebnis` | Kurzfassung des Auftragsergebnisses für das Display |
| `POST /api/v1/sitzungen/{id}/frage` | „Frag mein Meeting“, später auch als Sprache |

Der Dienst ist **in der Software abschaltbar** (Standard: aus). Bis heute öffnet die Anwendung bewusst keinen Port
(`SECURITY.md`); das muss dort entsprechend nachgezogen werden. Das Token wird in der Software erzeugt, angezeigt und lässt
sich widerrufen; auf dem Gerät liegt es in einer Konfigurationsdatei bzw. im NVS, **nie im Repository**.

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

1. **Laufend transkribieren** (Phase 2): Whisper schafft auf der RTX 3060 Ti ca. 35-fache Echtzeit. Beim Ende ist nur noch das letzte Stück offen (unter 1 s).
2. **Auswertung vorbereiten, solange das Meeting läuft:** Die Software fasst heute Gruppen von Chunks zusammen und führt sie am Ende zusammen. Die Teilzusammenfassungen können
   schon während des Meetings entstehen; am Ende fehlt nur der letzte Teil und die Zusammenführung.
3. **Modelle warm halten:** Beim Start der Sitzung Whisper und das Ollama-Modell laden und im Speicher lassen (`keep_alive`). Sie passen zusammen in 8 GB VRAM
   (Whisper ca. 2,3 GB, Sprachmodell ca. 3 GB), es wird nichts ausgetauscht. Spart die Ladezeit.
4. **Sprechertrennung entkoppeln:** pyannote arbeitet heute über die ganze Aufnahme. Entweder reicht die Zeit (messen), oder Sprecher-Merkmale werden laufend je
   Sprechabschnitt berechnet und am Ende nur noch gruppiert.
5. **Früh melden:** Das Häkchen erscheint, sobald das **Auftragsergebnis** da ist. Word-Datei, SRT & Co. entstehen danach im Hintergrund.
6. **Zwei Stufen:** erst „Transkript fertig“, dann „Auswertung fertig ✓“. Der Nutzer sieht den Fortschritt, statt zu warten.
7. **Kurzer Auftrag, kurze Antwort:** ein auf ToDos zugeschnittener Auftrag erzeugt weniger Text als ein volles Protokoll und ist schneller.

Die tatsächliche Verteilung wird in Phase 0 an einer echten Aufnahme gemessen, bevor etwas umgebaut wird.

## Phasen (überarbeitet)

| Phase | Inhalt | Ergebnis |
|---|---|---|
| **0 – Messen** | Zeit je Schritt der vorhandenen Verarbeitung auf diesem PC, auch hochgerechnet auf 60 Minuten; Entscheidung zur Sprechertrennung | Zahlen statt Vermutungen |
| **1 – Übertragung** | Dienst am PC (Opt-in, Token, Sitzungsordner pro Tag/Meeting), Sender im Gerät (15-s-Stücke, Bestätigung, Wiederaufnahme, lokale Kopie bleibt), Statusanzeige, danach vorhandene Verarbeitung; Token-Verwaltung in der Software | Aufnahme ist beim Ende schon am PC; nichts geht verloren |
| **2 – Laufende Transkription** | Schnitte an Sprechpausen (5–30 s, 2–3 s Überlappung bei Zwangsschnitt), wachsendes Transkript | Wartezeit nach dem Ende sinkt stark |
| **3 – Auftrag und schnelle Auswertung** | Aufträge (Dropdown am PC/Gerät), Teilzusammenfassungen während des Meetings, Modelle warm, früher Status, „Transkription erfolgreich ✓“ | Der beschriebene Ablauf |
| **4 – Ergebnis aufs Gerät** | Kurzfassung/ToDos auf dem Display, „Frag mein Meeting“ als Text | Rückmeldung am Gerät |
| **5 – Sprache** | Frage per Mikrofon, KI-Sprachausgabe der Antwort | später |

## Technische Risiken und offene Punkte

* **Lesen während des Schreibens:** Das Gerät liest seine Datei für die Übertragung, während der Encoder noch schreibt. Die Ogg-Seiten (ca. 1 s) müssen vollständig
  geschrieben und gesichert sein, bevor sie gesendet werden. Alternative: fertige Seiten zusätzlich in einem kleinen RAM-Puffer an den Sender geben.
* **RAM:** Beim C6 knapp (ca. 115 KB frei beim Aufnehmen), bei den S3 mit 8 MB PSRAM deutlich entspannter.
* **Stromverbrauch:** Alle 15 s Senden ist für den Funk günstig, wenn das Gerät dazwischen im Ruhezustand bleibt.
* **Zeit:** Die Sitzungsordner brauchen die Uhrzeit. Der PC vergibt sie; die Geräte müssen keine Uhr stellen.
* **Sicherheit:** HTTP im Heimnetz mit Token ist ein Anfang. Für fremde Netze ist TLS nötig (auf dem ESP32 machbar, kostet RAM). Offen mit Jens abzustimmen, weil `SECURITY.md` bisher keinen offenen Port vorsieht.
* **Diese Datei ist nur ein Konzept.** Es ändert weder die Anwendung noch die Firmware.
