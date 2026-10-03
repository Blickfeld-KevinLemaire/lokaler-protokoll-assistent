# Servermodus (Container)

Läuft ohne Oberfläche, zum Beispiel auf einem Linux-Server: Eine Aufnahme kommt
in einem Ordner an, wird automatisch in Chunks verarbeitet, transkribiert und
zusammengefasst, und die Ergebnisse liegen danach in einem Ausgangsordner.

```
Aufnahmegerät ──►  daten/eingang/  ──►  Verarbeitung (Container)  ──►  daten/ausgang/<name>_<zeit>/
 (Freigabe, FTP,        │                 1. Audio vorbereiten            Transkript (TXT/JSON/SRT/VTT)
  USB-Kopie ...)        │                 2. in Chunks transkribieren     Protokoll (JSON/Markdown)
                        │                 3. Sprecher trennen             Word-Datei (Protokoll + Transkript)
                        ▼                 4. Protokoll erstellen          ergebnis.json
   verarbeitet/ oder fehler/                                              (+ optional Rückmeldung per Webhook)
```

Es ist dieselbe Verarbeitungskette wie in der Windows-Anwendung – nur ohne
Fenster. Transkription und Protokoll laufen vollständig lokal (Whisper,
pyannote, Ollama). Es gibt keinen offenen Port und keine Weboberfläche.

## Schnellstart

Voraussetzung: Docker mit Docker Compose. Für eine NVIDIA-Grafikkarte
zusätzlich das NVIDIA Container Toolkit.

```bash
cp .env.beispiel .env          # HF_TOKEN eintragen, Einstellungen prüfen
mkdir -p daten/eingang daten/ausgang

# nur Prozessor
docker compose up -d --build
# mit NVIDIA-Grafikkarte
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d --build

# Umgebung prüfen (FFmpeg, Pakete, Ordner, Ollama)
docker compose run --rm protokoll python3 -m protokoll_assistent.server --pruefen
docker compose logs -f protokoll
```

Beim ersten Start lädt der Dienst `ollama-modell` das Sprachmodell, und die
Transkription lädt beim ersten Lauf ihre Modelle (mehrere GB, danach im Volume
`modelle`). `HF_TOKEN` ist für die Sprechertrennung nötig; die Lizenz des
pyannote-Modells muss mit dem zugehörigen Hugging-Face-Konto einmal bestätigt
sein.

## Einstellungen

Alles über Umgebungsvariablen (in der `.env`, siehe `.env.beispiel`):

| Variable | Standard | Bedeutung |
|---|---|---|
| `PROTOKOLL_GERAET` | `cpu` (GPU-Datei: `cuda`) | Rechnet der Prozessor oder die Grafikkarte? |
| `PROTOKOLL_SPRACHE` | `de` | Sprache der Aufnahmen, `auto` = automatisch erkennen |
| `PROTOKOLL_WHISPER_MODELL` | `large-v3-turbo` | Transkriptionsmodell |
| `PROTOKOLL_OLLAMA_MODELL` | `qwen3:8b` | Sprachmodell für das Protokoll |
| `PROTOKOLL_SPRECHERTRENNUNG` | `1` | Sprecher trennen (braucht `HF_TOKEN`) |
| `PROTOKOLL_PROTOKOLL_ERSTELLEN` | `1` | Zusammenfassung erstellen; `0` = nur Transkript |
| `PROTOKOLL_MIN_SPRECHER`, `PROTOKOLL_MAX_SPRECHER` | – | Anzahl der Sprecher eingrenzen |
| `PROTOKOLL_STABIL_SEKUNDEN` | `30` | So lange muss eine Datei unverändert sein, bevor sie verarbeitet wird |
| `PROTOKOLL_ABFRAGE_SEKUNDEN` | `10` | Wie oft der Eingang angesehen wird |
| `PROTOKOLL_EXPORT_FORMATE` | – | Zusätzliche Formate: `docx, md, txt, html, srt, vtt, json` (PDF gibt es nur in der Windows-Anwendung) |
| `PROTOKOLL_WEBHOOK_URL`, `PROTOKOLL_WEBHOOK_TOKEN` | – | Rückmeldung an ein anderes System |
| `HF_TOKEN` | – | Hugging-Face-Token für die Sprechertrennung |

## Kopplung mit dem Aufnahmegerät

Der Dienst beobachtet nur einen **Ordner**. Wie die Aufnahme dorthin kommt,
hängt vom Gerät ab:

* **Das Gerät legt Dateien selbst ab** (Netzwerkfreigabe SMB/NFS, FTP/SFTP):
  `./daten/eingang` als Freigabe bzw. FTP-Ziel einrichten.
* **Das Gerät wird per USB angeschlossen:** Die Dateien werden in den
  Eingangsordner kopiert (von Hand oder per Skript).
* **Das Gerät lädt in eine Cloud hoch:** Der Cloud-Ordner muss auf dem Server
  gespiegelt vorliegen, damit er überwacht werden kann.

**Zurück zum Gerät:** Die Ergebnisse stehen im Ausgangsordner (`./daten/ausgang`).
Ob und wie das Gerät sie von dort abholt, bestimmt das Gerät:

* Es liest die Freigabe `./daten/ausgang` selbst (oder ein Skript kopiert dorthin).
* Der Webhook meldet jede fertige Aufnahme per HTTP-POST (JSON mit Dateiname,
  Status, Ausgabeordner und Dateiliste) an eine Adresse im Netz, zum Beispiel
  eine Steuerung des Geräts.

Das Gerät braucht dafür eine Möglichkeit, Dateien abzulegen und/oder Meldungen
zu empfangen. Eine gerätespezifische Anbindung (herstellereigene Schnittstelle)
ist nicht enthalten.

## Was bei den Dateien passiert

* **Fertig geschrieben?** Eine Datei wird erst angefasst, wenn sie bei zwei
  Abfragen gleich groß ist und seit `PROTOKOLL_STABIL_SEKUNDEN` nicht mehr
  verändert wurde. Unfertiges (`.part`, `.tmp`, versteckte Dateien) wird übersprungen.
* **Reihenfolge:** eine Aufnahme nach der anderen, die älteste zuerst.
* **Danach:** Die Aufnahme wandert nach `eingang/verarbeitet/` (oder bei einem
  Fehler nach `eingang/fehler/`). Geht das Verschieben nicht (schreibgeschützte
  Freigabe), merkt sich der Dienst die Datei und verarbeitet sie nicht noch einmal.
* **Neustart mitten in einer Aufnahme:** Der Dienst beendet sich auf `docker stop`
  sauber; die Aufnahme bleibt im Eingang und wird beim nächsten Start mit den
  vorhandenen Zwischenständen fortgesetzt.
* **Fehler bei einer Aufnahme** stoppen nie den Dienst. Fehlt nur das Protokoll
  (z. B. Ollama war nicht erreichbar), liegt das Transkript trotzdem vor, und
  `ergebnis.json` nennt den Grund unter `protokoll_fehler`.

`ergebnis.json` (im Ergebnisordner der Aufnahme):

```json
{ "status": "fertig", "datei": "sitzung.mp3", "ausgabe": "/daten/ausgang/sitzung_20261003_091500",
  "dateien": ["sitzung_lokal_transkript_….txt", "…"], "fehler": null, "protokoll_fehler": null,
  "dauer_sekunden": 412.3 }
```

## Datenschutz und Betrieb

* Aufnahmen, Transkripte und Protokolle liegen im Klartext in `./daten`. Zugriff
  auf diese Ordner (und die Freigabe) schützen, die Platte verschlüsseln und ein
  Löschkonzept für alte Aufnahmen festlegen – das ist Sache des Server-Betriebs.
* Der Webhook überträgt **keine Inhalte**, nur Dateiname, Status und Ordnerpfade.
  Das Token kommt aus der Umgebung und wird nicht geloggt.
* Es werden keine Ports geöffnet; die Anwendung nimmt keine Verbindungen an.

## Grenzen

* **Rechenleistung:** Ohne NVIDIA-Grafikkarte dauert eine Aufnahme auf dem
  Prozessor deutlich länger (je nach Modell etwa so lang wie die Aufnahme oder
  länger). Für längere Aufnahmen im Dauerbetrieb ist eine Grafikkarte sinnvoll.
* **Sprecher** erhalten Kennungen („Sprecher 1“), keine Namen; die Zuordnung zu
  Personen ist in der Oberfläche der Windows-Anwendung möglich.
* Ein Abbruch einer einzelnen Aufnahme von außen ist nicht vorgesehen; sie läuft
  bis zum Ende oder bis zum Stoppen des Containers.
