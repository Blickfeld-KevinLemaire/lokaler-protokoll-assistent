# Servermodus (Container)

Läuft ohne Oberfläche, zum Beispiel auf einem Linux-Server: Eine Aufnahme kommt
in einem Ordner an, wird automatisch transkribiert und
zusammengefasst, und die Ergebnisse liegen danach in einem Ausgangsordner.

```
Aufnahmegerät ──►  daten/eingang/  ──►  Verarbeitung (Container)  ──►  daten/ausgang/<name>_<zeit>/
 (Freigabe, FTP,        │                 1. Audio vorbereiten            Transkript (TXT/JSON/SRT/VTT)
  USB-Kopie ...)        │                 2. in Chunks transkribieren     Protokoll (JSON/Markdown)
                        │                 3. Sprecher trennen             Word-Datei (Protokoll + Transkript)
                        ▼                 4. Protokoll erstellen          ergebnis.json
   verarbeitet/ oder fehler/                                              (+ optional Rückmeldung per Webhook)
```

Es ist dieselbe Verarbeitungskette wie in der Windows-Anwendung. Transkription
und Protokoll laufen vollständig lokal (Whisper, pyannote, Ollama).

## Oberfläche im Browser, mehrere Nutzer (ab 0.6)

Der Container startet die Programmschnittstelle in der Rolle `server`
(`python3 -m protokoll_assistent.api --rolle server`) und liefert dieselbe
Oberfläche wie die Windows-Anwendung an Browser aus: `http://<server>:8780`.
Ohne Anmeldung geht nichts außer der Gesundheitsabfrage.

* **Nutzer:** Jeder meldet sich mit Name + Passwort oder mit einem persönlichen
  Zugangsschlüssel an (beides ist möglich, die Firma wählt). Jeder hat eigene
  Besprechungen und kann sie mit Einzelnen oder allen teilen. Admins verwalten
  Nutzer, Geräte und Einstellungen in der Oberfläche.
* **Erster Admin:**
  `docker compose exec protokoll python3 -m protokoll_assistent.api nutzer-anlegen <Name> --admin`
  gibt einmal einen Zugangsschlüssel aus. Alternativ für die Ersteinrichtung
  `VERMERK_ZUGANG` in der `.env` setzen (Notfallzugang mit Admin-Rechten) und
  danach wieder leeren.
* **Eingangsordner:** wie bisher; jede Datei wird ein Auftrag in der einen,
  gemeinsamen Warteschlange (auch Aufträge aus dem Browser und von Geräten
  laufen nie gleichzeitig). `PROTOKOLL_EINGANG_NUTZER` bestimmt, wem die
  Ergebnisse gehören (leer: nur Admins sehen sie).
* **Aufnahmegeräte:** werden in der Oberfläche angelegt und einem Nutzer
  zugeordnet; dessen Ordner bekommt die Aufnahmen. Die Variablen
  `PROTOKOLL_EMPFANG*` gelten nur noch für den alten Start ohne Oberfläche
  (`python3 -m protokoll_assistent.server`), der weiter funktioniert.
* **Daten:** Einstellungen, Nutzerliste und Freigaben liegen im Volume
  `intern` (`/daten/intern`).
* **Netz:** Port 8780 ist in der `docker-compose.yml` freigegeben. Für den
  Zugriff von außerhalb des eigenen Netzes gehört ein Reverse-Proxy mit TLS
  davor; erlaubte Hostnamen lassen sich mit `VERMERK_ERLAUBTE_HOSTS`
  (Komma-Liste) einschränken.

## Schnellstart

Dieselben Schritte auf jedem Rechner – mit NVIDIA-, AMD- oder Intel-Grafik oder
ganz ohne Karte, auf x86-64 wie auf ARM64. Welche Karte da ist, erkennt das
Skript selbst.

Voraussetzung: ein Linux-Rechner mit Docker und Docker Compose, für eine
Grafikkarte dazu deren Treiber (siehe [Grafikkarten](#grafikkarten); bei NVIDIA
auch das NVIDIA Container Toolkit).

```bash
# 1. Im Projektordner: Grafikkarte erkennen. Legt die .env an (aus .env.beispiel)
#    und traegt dort die passenden Compose-Dateien ein (COMPOSE_FILE).
./grafikkarte-erkennen.sh

# 2. In der .env den HF_TOKEN eintragen (fuer die Sprechertrennung).

# 3. Starten -- Compose nimmt die Dateien aus der .env.
mkdir -p daten/eingang daten/ausgang
docker compose up -d --build

# 4. Pruefen: Rechnet jeder Schritt dort, wo er soll?
docker compose exec protokoll python3 -m protokoll_assistent.api grafikkarte-pruefen
docker compose logs -f protokoll

# 5. Ersten Admin anlegen (gibt einen Zugangsschluessel einmal aus) und im Browser
#    http://<server>:8780 oeffnen.
docker compose exec protokoll python3 -m protokoll_assistent.api nutzer-anlegen <Name> --admin
```

Was das Skript tut und wann es scheitert:

* **Erkennung:** Es liest die Grafikkarten des Rechners aus `/sys`
  (PCI-Geräte der Klasse „Anzeige“ und `/sys/class/drm`), bei NVIDIA zur Not
  über `nvidia-smi`, dazu die Prozessor-Architektur. Bei mehreren Karten hat
  NVIDIA Vorrang, dann AMD, dann Intel.
* **Ergebnis:** In der `.env` stehen danach `COMPOSE_FILE` (z. B.
  `docker-compose.yml:docker-compose.amd.yml`) und bei AMD `VIDEO_GID` und
  `RENDER_GID` – die Gruppen genau der Geräte `/dev/kfd` und `/dev/dri/renderD*`.
  Alles andere in der `.env` bleibt, wie es ist.
* **Fehler statt Prozessor:** Ist eine Karte da, aber nicht nutzbar (bei NVIDIA
  fehlt das Container Toolkit, bei AMD `/dev/kfd`), bricht das Skript mit einer
  Erklärung ab und ändert die `.env` nicht.
* `--anzeigen` zeigt nur, was es eintragen würde; `--karte nvidia|amd|intel|keine`
  gibt die Wahl vor (z. B. `keine`, um bewusst auf dem Prozessor zu rechnen).
* Nach einem Wechsel der Karte: Skript erneut ausführen und
  `docker compose up -d --build`.
* Vergessen? Das Prozessor-Image warnt beim Start, wenn der Rechner eine Karte
  hat, die ungenutzt bleibt.

Ohne Skript geht es weiter wie bisher: die Zusatzdatei von Hand angeben, z. B.
`docker compose -f docker-compose.yml -f docker-compose.amd.yml up -d --build`.

Weitere Prüfungen: `docker compose run --rm protokoll python3 -m
protokoll_assistent.server --pruefen` (FFmpeg, Pakete, Ordner, Ollama).

## Grafikkarten

Je Hersteller gibt es eine Zusatzdatei. Sie baut das Image mit den passenden
Paketen und reicht die Karte in die Container. `./grafikkarte-erkennen.sh`
(siehe [Schnellstart](#schnellstart)) wählt sie selbst; von Hand:

| Karte | Zusatzdatei(en) | Transkription | Sprechertrennung | Zusammenfassung |
|---|---|---|---|---|
| NVIDIA (x86-64) | `docker-compose.gpu.yml` | Karte | Karte | Karte |
| NVIDIA (ARM64: DGX Spark, GH200) | `docker-compose.gpu.yml` **und** `docker-compose.gpu-arm.yml` | Karte | Karte | Karte |
| AMD (ROCm) | `docker-compose.amd.yml` | Karte | Karte | Karte |
| Intel (Arc, Prozessorgrafik) | `docker-compose.intel.yml` | Prozessor | Prozessor | Karte (Vulkan) |
| keine | – | Prozessor | Prozessor | Prozessor |

```bash
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d --build                               # NVIDIA
docker compose -f docker-compose.yml -f docker-compose.gpu.yml -f docker-compose.gpu-arm.yml up -d --build # NVIDIA ARM64
docker compose -f docker-compose.yml -f docker-compose.amd.yml up -d --build                               # AMD
docker compose -f docker-compose.yml -f docker-compose.intel.yml up -d --build                             # Intel
```

**Die Karte ist Pflicht.** Ein Image, das für eine Karte gebaut ist, startet nur,
wenn jeder Schritt aus der Tabelle sie auch nutzen kann. Sonst beendet sich der
Dienst und nennt im Log (`docker compose logs protokoll`) Schritt, Grund und
Abhilfe. Ohne diese Prüfung lief die Verarbeitung früher still auf dem
Prozessor weiter und dauerte nur ein Vielfaches. Fällt die Karte im Betrieb aus,
bricht ein Auftrag ab, statt auf dem Prozessor weiterzurechnen. Eine
Zusammenfassung, die Ollama auf dem Prozessor rechnen würde, gilt als Fehler;
das Transkript bleibt dabei erhalten. Wer bewusst auf den Prozessor ausweichen
will, setzt `PROTOKOLL_GRAFIKKARTE_PFLICHT=0`.

`grafikkarte-pruefen` (siehe Schnellstart) zeigt den Stand je Schritt, lädt dazu
das eingestellte Sprachmodell und meldet, wie viel davon im Grafikspeicher
liegt.

**Voraussetzungen auf dem Rechner:**

* **NVIDIA:** Treiber und [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html).
  Treiber ab 525, für Blackwell-Karten ab 570.
  Test: `docker run --rm --gpus all nvidia/cuda:12.6.3-base-ubuntu22.04 nvidia-smi`.
  Auf ARM64 wird CTranslate2 beim Bau aus dem Quelltext mit CUDA übersetzt
  (PyPI hat dort nur eine Prozessor-Fassung); der erste Bau dauert dadurch etwa
  10 bis 20 Minuten länger.
* **AMD:** der `amdgpu`-Treiber des Kernels (`/dev/kfd` und `/dev/dri` müssen
  da sein). ROCm 7.2 selbst bringen die Images mit – der Treiber im Kernel
  kommt aber immer vom Rechner, und auf ihn kommt es an:
  * Radeon RX 7000/9000 und Radeon PRO: Ubuntu 22.04 (mit HWE-Kernel) oder 24.04.
  * Ryzen AI Max (Strix Halo, gfx1151): ein aktueller Kernel, auf Ubuntu 24.04
    der HWE- oder OEM-Kernel (ab 6.14); Ubuntu 22.04 reicht dafür nicht.
    Erprobt mit einem Ryzen AI Max+ 395 unter Fedora 42 (Kernel 6.19).

  In die `.env` gehören die Gruppennummern von `video` und `render`:
  `getent group video render` (sie unterscheiden sich je Distribution).
* **Intel:** der Grafiktreiber des Kernels (`i915` oder `xe`, `/dev/dri`).
  Ollama rechnet über Vulkan; die Zusatzdatei schaltet dafür auch
  Prozessorgrafik frei (`OLLAMA_IGPU_ENABLE`), die Ollama sonst verwirft.
  Erprobt ist dieser Weg mit der Vulkan-Grafik eines AMD-Prozessors – mit einer
  Intel-Karte noch nicht.

**Wenn die Prüfung scheitert:**

* *„stürzt bei der ersten Rechnung auf der Karte ab (Signal 11)“* auf Fedora,
  RHEL, Rocky oder Alma: SELinux. Die Zusatzdateien für AMD und Intel setzen
  deshalb `security_opt: label:disable`; wer eigene Compose-Dateien benutzt,
  übernimmt das.
* *„Der Eingangsordner … ist nicht lesbar“*: Rechte des Ordners prüfen. Auf
  SELinux-Rechnern brauchen die Ordner `:z` (steht in der mitgelieferten
  `docker-compose.yml`; eigene Compose-Dateien übernehmen das).
* *„CTranslate2 findet keine Grafikkarte“* auf ARM64: Es fehlt
  `docker-compose.gpu-arm.yml`.
* *„… nicht vorhanden“* beim Sprachmodell: Der Dienst `ollama-modell` lädt es
  beim ersten Start noch herunter (`docker compose logs ollama-modell`).

Beim ersten Start lädt der Dienst `ollama-modell` das Sprachmodell, und die
Transkription lädt beim ersten Lauf ihre Modelle (mehrere GB, danach im Volume
`modelle`). `HF_TOKEN` ist für die Sprechertrennung nötig; die Lizenz des
pyannote-Modells muss mit dem zugehörigen Hugging-Face-Konto einmal bestätigt
sein.

## Einstellungen

Alles über Umgebungsvariablen (in der `.env`, siehe `.env.beispiel`):

| Variable | Standard | Bedeutung |
|---|---|---|
| `PROTOKOLL_GERAET` | `cpu` (Zusatzdateien NVIDIA/AMD: `cuda`) | Rechnet der Prozessor oder die Grafikkarte? (nur der alte Start `protokoll_assistent.server`) |
| `PROTOKOLL_GRAFIKKARTE_PFLICHT` | `1` | Mit einem Image für eine Grafikkarte: nicht starten bzw. abbrechen, statt auf dem Prozessor zu rechnen |
| `VIDEO_GID`, `RENDER_GID` | – | Nur AMD: Gruppennummern für `/dev/kfd` und `/dev/dri` (`getent group video render`) |
| `PROTOKOLL_SPRACHE` | `de` | Sprache der Aufnahmen, `auto` = automatisch erkennen |
| `PROTOKOLL_WHISPER_MODELL` | `large-v3-turbo` | Transkriptionsmodell |
| `PROTOKOLL_OLLAMA_MODELL` | `qwen3.5:4b-q4_K_M` | Sprachmodell für das Protokoll |
| `PROTOKOLL_SPRECHERTRENNUNG` | `1` | Sprecher trennen (braucht `HF_TOKEN`) |
| `PROTOKOLL_PROTOKOLL_ERSTELLEN` | `1` | Zusammenfassung erstellen; `0` = nur Transkript |
| `PROTOKOLL_MIN_SPRECHER`, `PROTOKOLL_MAX_SPRECHER` | – | Anzahl der Sprecher eingrenzen |
| `PROTOKOLL_STABIL_SEKUNDEN` | `30` | So lange muss eine Datei unverändert sein, bevor sie verarbeitet wird |
| `PROTOKOLL_ABFRAGE_SEKUNDEN` | `10` | Wie oft der Eingang angesehen wird |
| `PROTOKOLL_EXPORT_FORMATE` | – | Zusätzliche Formate: `docx, md, txt, html, srt, vtt, json` (PDF gibt es nur in der Windows-Anwendung) |
| `PROTOKOLL_WEBHOOK_URL`, `PROTOKOLL_WEBHOOK_TOKEN` | – | Rückmeldung an ein anderes System |
| `PROTOKOLL_EMPFANG` | `0` | Empfang für die WLAN-Aufnahmegeräte (öffnet einen Port, siehe unten) |
| `PROTOKOLL_EMPFANG_PORT` | `8765` | Port des Empfangs |
| `PROTOKOLL_EMPFANG_GERAETE` | – | `Name:SHA256` je Gerät, mit Komma getrennt |
| `HF_TOKEN` | – | Hugging-Face-Token für die Sprechertrennung |

## Kopplung mit dem Aufnahmegerät

Der Dienst beobachtet einen **Ordner**. Wie die Aufnahme dorthin kommt,
hängt vom Gerät ab:

* **Die eigenen WLAN-Aufnahmegeräte** (Firmware unter `firmware/`) laden selbst
  hoch, sobald der Empfang eingeschaltet ist – siehe nächster Abschnitt.

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

## Empfang für die WLAN-Aufnahmegeräte

Die Aufnahmegeräte laden ihre Aufnahmen in Stücken per HTTP hoch; abgebrochene
Übertragungen setzen beim letzten bestätigten Byte wieder an, und eine Datei
erscheint im Eingang erst, wenn ihre Prüfsumme stimmt. Die Schnittstelle steht
in [`../GERAETE-SCHNITTSTELLE.md`](../GERAETE-SCHNITTSTELLE.md).

1. Je Gerät ein Token erzeugen:

   ```bash
   docker compose run --rm protokoll python3 -m protokoll_assistent.server --token-erzeugen S3-Audio
   ```

   Das Token steht nur in dieser Ausgabe – in die `server_config.h` des Geräts
   eintragen (`VERMERK_SERVER_TOKEN`, Adresse `VERMERK_SERVER_BASE_URL`).
2. Die ausgegebene Zeile `S3-Audio:<Hash>` in der `.env` unter
   `PROTOKOLL_EMPFANG_GERAETE` eintragen (mehrere Geräte mit Komma),
   `PROTOKOLL_EMPFANG=1` setzen.
3. In der `docker-compose.yml` den Abschnitt `ports` beim Dienst `protokoll`
   einkommentieren und den Container neu starten.

Die fertigen Aufnahmen heißen `<Gerät>_<Dateiname>` (z. B.
`S3-Audio_H5_007.opus`) und laufen danach ganz normal durch die Verarbeitung.
Das Protokoll des Dienstes nennt bei jedem neuen Kontakt Gerät, Werks-Id,
Firmware und Adresse – praktisch für die Fehlersuche.

**Die Übertragung ist nicht verschlüsselt** – nur im eigenen Netz einschalten
(siehe `SECURITY.md`).

## Was bei den Dateien passiert

* **Fertig geschrieben?** Eine Datei wird erst angefasst, wenn sie bei zwei
  Abfragen gleich groß ist und seit `PROTOKOLL_STABIL_SEKUNDEN` nicht mehr
  verändert wurde. Unfertiges (`.part`, `.tmp`, versteckte Dateien) wird übersprungen.
* **Reihenfolge:** eine Aufnahme nach der anderen, die älteste zuerst.
* **Danach:** Die Aufnahme wandert nach `eingang/verarbeitet/` (oder bei einem
  Fehler oder nach einem Abbruch in der Oberfläche nach `eingang/fehler/`). Geht das Verschieben nicht (schreibgeschützte
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
* Was jemand in der Oberfläche unter „Transkripte“ löscht, ist nicht endgültig weg:
  Es liegt in `.papierkorb/<Zeit>_<Kennung>/` des jeweiligen Ausgabeordners (je Nutzer
  unter `nutzer/<name>/`). Zurückholen: den Ordner aus `.papierkorb/` zurück in den
  Ausgabeordner verschieben (Freigaben müssen danach neu gesetzt werden).
  Endgültig löschen: den Ordner leeren (z. B. regelmäßig, was älter als 30 Tage ist).
  Die Aufnahme im Eingang (`verarbeitet/`) bleibt davon unberührt.
* Der Webhook überträgt **keine Inhalte**, nur Dateiname, Status und Ordnerpfade.
  Das Token kommt aus der Umgebung und wird nicht geloggt.
* Ohne `PROTOKOLL_EMPFANG=1` werden keine Ports geöffnet und keine Verbindungen
  angenommen. Mit Empfang nur Anfragen mit gültigem Geräte-Token.

## Grenzen

* **Rechenleistung:** Ohne Grafikkarte dauert eine Aufnahme auf dem
  Prozessor deutlich länger (je nach Modell etwa so lang wie die Aufnahme oder
  länger). Für längere Aufnahmen im Dauerbetrieb ist eine Grafikkarte sinnvoll.
  Mit einer Intel-Karte rechnet nur die Zusammenfassung auf der Karte.
* **Sprecher** erhalten Kennungen („Sprecher 1“), keine Namen; die Zuordnung zu
  Personen ist in der Oberfläche der Windows-Anwendung möglich.
* Ein Abbruch einer einzelnen Aufnahme von außen ist nicht vorgesehen; sie läuft
  bis zum Ende oder bis zum Stoppen des Containers.
