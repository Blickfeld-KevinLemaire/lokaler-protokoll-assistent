# Sicherheit

## Eine Schwachstelle melden

Bitte melden Sie Sicherheitsluecken **nicht** ueber ein oeffentliches Issue.

Nutzen Sie stattdessen den Punkt **"Report a vulnerability"** im Reiter
*Security* dieses Repositorys. Die Meldung ist dann nur fuer die
Verantwortlichen sichtbar.

Wir melden uns innerhalb von 14 Tagen zurueck. Bitte geben Sie an:

* welche Version bzw. welchen Commit Sie geprueft haben,
* wie sich das Problem nachstellen laesst,
* welche Auswirkung Sie sehen.

Bitte geben Sie uns Zeit fuer eine Korrektur, bevor Sie die Luecke
veroeffentlichen.

## Was in diesem Projekt sicherheitsrelevant ist

Die Anwendung verarbeitet **Besprechungsaufnahmen** — also personenbezogene
Daten, oft von Menschen, die der Aufnahme nur im Rahmen der Besprechung
zugestimmt haben. Entsprechend gelten hier ein paar Punkte besonders:

* **Aufnahmen und Transkripte gehoeren niemals ins Repository.** Die Ordner
  `ausgabe/`, `aufnahmen/`, `arbeitsdaten/`, `sprecherprofile/` und `chatverlaeufe/` sind
  ausgeschlossen, ebenso Medien- und Protokolldateien ueberall im Baum.
* **Sprecherprofile sind biometrische Daten.** Ein gespeicherter
  Stimmabdruck (`sprecherprofile/profile.json`) erlaubt, eine Person in
  anderen Aufnahmen wiederzuerkennen. Die Profile entstehen nur nach
  ausdruecklicher Bestaetigung, bleiben ausschliesslich auf dem Rechner, gehen
  nie in den API-Modus und nie in den Installer, und lassen sich in der
  Anwendung loeschen. Bei der Deinstallation bleiben sie absichtlich stehen —
  wie die uebrigen Anwenderdaten. Die Funktion gibt es nur im lokalen Modus.
* **Schluessel und Token stehen nie im Code und nie in einer versionierten
  Datei.** Einzige Ausnahme: `HF_TOKEN` darf in der von Git ignorierten `.env`
  im Projektordner stehen (Vorlage `.env.beispiel`); wer sie anlegt, schuetzt
  sie wie jede Datei mit Zugangsdaten. Sonst kommen sie aus Umgebungsvariablen (`HF_TOKEN`), aus
  einer verdeckten Eingabe (`getpass`), oder — nur wenn der Anwender das
  ausdruecklich anhakt — dauerhaft ueber die Windows-Anmeldeinformations-
  verwaltung (Paket `keyring`, einziger Zugriffspunkt:
  `protokoll_assistent/services/secret_store.py`). Die Konfigurationsdatei
  (`protokoll_assistent/konfiguration.json`) enthaelt dabei nur ein
  Häkchen, ob gemerkt werden soll — nie den Schluessel selbst. Ohne dieses
  Häkchen gilt ein eingegebener Schluessel nur fuer die laufende Sitzung.
  Das gilt auch fuer den Hugging-Face-Zugang, den die Ersteinrichtung abfragt
  (Eintrag `hf_token`); `utils/hf_env.py` liest ihn dort als dritte Quelle nach
  Umgebungsvariable und `.env`.
* **Die Ersteinrichtung laedt und startet den Ollama-Installer** — nur nach
  ausdruecklicher Zustimmung des Anwenders (Haken, standardmaessig leer) und
  nur, wenn Ollama noch nicht installiert ist
  (`protokoll_assistent/services/ollama_einrichtung_service.py`). Geladen wird
  ausschliesslich ueber HTTPS von `ollama.com`; Weiterleitungen sind nur zu
  `github.com` und dessen Speicher fuer Release-Dateien erlaubt. Groesse und
  Dateiformat werden geprueft, und ausgefuehrt wird die Datei nur, wenn ihre
  Authenticode-Signatur gueltig ist und von „Ollama Inc.“ stammt — sonst nicht
  (auch dann nicht, wenn sich die Signatur nicht pruefen laesst). Installiert
  wird still, nur fuer das eigene Benutzerkonto und ohne Administratorrechte;
  der Installer wird danach geloescht. Ollama startet anschliessend mit Windows
  und ist nur auf diesem Rechner erreichbar (127.0.0.1:11434). Uebertragen wird
  dabei nur die Download-Anfrage selbst, keine Aufnahme und kein Text.
* **Ohne Zustimmung keine schwere Laufzeitumgebung.** Die gut 5 GB fuer PyTorch
  und CUDA laedt `bootstrap.py` bei einer frischen Installation erst, nachdem
  der Anwender in der Ersteinrichtung zugestimmt hat
  (`bootstrap.laufzeit_beim_start_einrichten`).
* **Im lokalen Modus werden keine Audio- oder Videodaten uebertragen.**
  Bleibt das so, ist das eine Zusage an die Anwender — Aenderungen daran
  gehoeren ausdruecklich in die Release-Hinweise.
* **Der Chatbot „Frag mein Meeting“ ueberträgt im API-Modus Texte.** Fragen, die
  passenden Textstellen und - fuer die Suche - die Texte der ausgewaehlten
  Transkripte und Zusammenfassungen gehen an den eingetragenen Endpunkt. Im
  lokalen Modus (Ollama auf 127.0.0.1) verlaesst nichts den Rechner. Die
  berechneten Suchvektoren liegen als Zwischenspeicher im Ordner
  `arbeitsdaten/chat_index/`, der nicht versioniert wird. Gespeicherte Chats
  (Fragen, Antworten, Quellen) liegen lokal in `chatverlaeufe/`; sie werden
  nicht versioniert, nicht ausgeliefert und nie uebertragen.
* **Der Servermodus (Container) speichert Aufnahmen und Ergebnisse im Klartext**
  in den eingebundenen Ordnern (`daten/`, nicht versioniert). Zugriffsschutz,
  Plattenverschluesselung und ein Loeschkonzept sind Sache des Betreibers. Ohne
  `PROTOKOLL_EMPFANG=1` oeffnet der Dienst keinen Port (siehe naechster Punkt).
  Der optionale Webhook uebertraegt nur Dateiname,
  Status und Ordnerpfade, nie Inhalte; sein Token und `HF_TOKEN` kommen aus der
  Umgebung (nie ins Image, nie ins Repository, nie ins Log).
* **Empfang fuer die WLAN-Aufnahmegeraete oeffnet einen Port – nur auf Wunsch.**
  In der Anwendung (Einstellungen → „Aufnahmegeräte“) und im Servermodus
  (`PROTOKOLL_EMPFANG=1`) ist er ab Werk **aus**. Eingeschaltet lauscht ein
  HTTP-Dienst (Standardport 8765) im lokalen Netz und nimmt Aufnahmen der
  eingetragenen Geraete an
  (`protokoll_assistent/services/geraete_empfang_service.py`, Schnittstelle in
  `protokoll_assistent/GERAETE-SCHNITTSTELLE.md`):
  * Jede Anfrage braucht das Token des Geraets (256 Bit). Gespeichert wird nur
    dessen SHA-256 (`konfiguration.json` bzw. `PROTOKOLL_EMPFANG_GERAETE`); das
    Token selbst wird beim Anlegen einmal angezeigt und nie protokolliert. Das
    Token bestimmt den Geraetenamen – ein Geraet kann sich nicht als ein
    anderes ausgeben.
  * Angenommen werden nur Audiodateien mit einfachem Namen (keine Pfade), in
    Stuecken von hoechstens 4 MB, Dateien bis 2 GB und nur bei genug freiem
    Platz; hoechstens acht Verbindungen gleichzeitig, 30 s Zeitlimit.
  * Eine Datei erscheint im Eingangsordner erst, wenn Groesse und SHA-256 der
    ganzen Datei stimmen. Teilstaende liegen im versteckten Ordner `.empfang/`
    und werden nach sieben Tagen ohne Fortschritt geloescht.
  * **Die Uebertragung ist nicht verschluesselt.** Wer im selben WLAN den
    Datenverkehr mitschneidet, kann die Aufnahme mithoeren. Der Empfang ist
    deshalb nur fuer das eigene, vertrauenswuerdige Netz gedacht; fuer fremde
    oder offene Netze braeuchte es TLS (noch nicht umgesetzt).
  * `X-Geraete-Id` (Werks-MAC) und `X-Firmware` dienen nur der Zuordnung und
    Fehlersuche, nie der Anmeldung.
  * **Einrichtung ueber USB** (`services/geraete_usb_service.py`): Die Anwendung
    schreibt WLAN-Name, WLAN-Passwort, eigene Adresse und ein frisch erzeugtes
    Token ueber das USB-Kabel ins Geraet (NVS). Das Passwort wird nirgends
    gespeichert oder protokolliert, vom Token nur der Hash. Das Geraet gibt
    Passwort und Token nie wieder aus. Wer ein Geraet per USB in der Hand hat,
    kann es neu einrichten – das ist gewollt (physischer Zugriff). Das NVS des
    ESP32 ist ohne Flash-Verschluesselung auslesbar: Wer ein Geraet mitnimmt,
    kommt an WLAN-Passwort und Token. Ein verlorenes Geraet deshalb in der
    Anwendung entfernen (Token ungueltig) und das WLAN-Passwort aendern.
* **Kein API-Anbieter ist voreingestellt.** Endpunkte und Modelle sind ab Werk
  leer; erst wenn der Anwender in den Einstellungen einen Anbieter waehlt (oder
  einen eigenen Endpunkt eintraegt), geht etwas dorthin. Ohne Auswahl bricht die
  Verarbeitung mit einem Hinweis ab, statt irgendwohin zu senden. Die Liste der
  Anbieter und ihre Adressen stehen in `protokoll_assistent/services/api_anbieter.py`.
* **Im API-Modus wird die Aufnahme bzw. das Transkript uebertragen** an einen
  vom Anwender gewaehlten Endpunkt — fuer Transkription und Nachbearbeitung
  getrennt umschaltbar. Ist fuer einen Schritt der API-Modus aktiv, zeigt die
  Oberflaeche durchgehend einen Datenschutz-Hinweis: Fuer diese externe
  Schnittstelle kann keine Vertraulichkeit garantiert werden, die
  Verantwortung dafuer liegt beim Anwender. Dieser Hinweis darf nicht
  entfallen.

## Was automatisch geprueft wird

Bei jedem Push auf jeden Branch (`.github/workflows/ci.yml`):

| Pruefung | Womit |
|---|---|
| Zugangsdaten im Code **und in der Historie** | gitleaks |
| Bekannte Schwachstellen in Abhaengigkeiten | pip-audit |
| Unsichere Muster im Code | Sicherheitsregeln (`S`) von ruff |
| Statische Codeanalyse | CodeQL (`.github/workflows/codeql.yml`) |

Zusaetzlich laeuft die Schwachstellenpruefung jede Nacht erneut
(`.github/workflows/nightly.yml`), weil neue Luecken auch ohne Aenderung am
Code bekannt werden. Dependabot meldet verwundbare Abhaengigkeiten und
schlaegt woechentlich Aktualisierungen vor.

## Unterstuetzte Versionen

Das Projekt ist noch jung. Sicherheitskorrekturen gibt es fuer den aktuellen
Stand des `main`-Branches.
