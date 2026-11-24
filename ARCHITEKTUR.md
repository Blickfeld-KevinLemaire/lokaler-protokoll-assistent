# Architektur der neuen Oberfläche

Stand: November 2026, Branch `feature/neue-oberflaeche`. Dieses Dokument
beschreibt das Zielbild und die Regeln, nach denen gebaut wird. Was hier steht,
gilt vor älteren Beschreibungen in `CLAUDE.md`, soweit es die Oberfläche
betrifft. Nach dem Zusammenführen wird `CLAUDE.md` angepasst.

## Zielbild

```
              Svelte-Oberfläche (oberflaeche/, statisch gebaut, überall dieselbe)
      Tauri-Fenster (Windows) ─┐                    ┌─ Browser (im Netz / Container)
                               │   HTTP + SSE       │
       ┌───────────────────────┴────────────────────┴──────────────────┐
       │ api/        FastAPI: Zugang je Rolle, Routen, Ereignisstrom    │
       │ ablauf/     Steuerung ohne Qt: EINE Auftragswarteschlange für   │
       │             Oberfläche, Aufnahmegeräte und Eingangsordner      │
       │ services/   Verarbeitung (unverändert: Whisper, pyannote, …)  │
       │ Empfang :8765 für Aufnahmegeräte (GERAETE-SCHNITTSTELLE.md)     │
       └────────────────────────────────────────────────────────────────┘
            ▲ ESP32 #1      ▲ ESP32 #2      ▲ ESP32 #3
```

Ein Backend, eine Oberfläche, zwei Hüllen:

| | Windows-Anwendung | dazu „im Netz anbieten" | Container (Servermodus) |
|---|---|---|---|
| Programmschnittstelle | 127.0.0.1, Schlüssel je Start | zusätzlich im Netz, Anmeldung | im Netz, Anmeldung |
| Fenster | Tauri | Tauri + Browser anderer Rechner | nur Browser |
| Dateien per Pfad, Ordner öffnen | ja | nur im Tauri-Fenster | nein: Hochladen/Herunterladen |
| Aufnahmegeräte | Schalter in den Einstellungen | ebenso | Umgebungsvariable/Einstellungen |

Die Oberfläche erkennt am Tauri-Objekt (`window.__TAURI_INTERNALS__`) und an
`/api/info` (`faehigkeiten`), was sie anbieten darf.

## Prozesse (Windows)

1. `VERMERK.exe` ist das Tauri-Fenster. Es wählt einen freien Port, erzeugt
   einen Schlüssel (`VERMERK_API_SCHLUESSEL`, nur in der Umgebung, nie auf der
   Befehlszeile) und startet den Dienst:
   * API-Modus: `vermerk-dienst.exe --rolle desktop --port N` (PyInstaller,
     One-Directory).
   * Lokaler Modus: Der Dienst richtet beim Start wie bisher die Rechenumgebung
     ein (`bootstrap.py`, mit Zustimmung) und startet sich in ihr neu als
     `python -m protokoll_assistent.api …` – Umgebung und Argumente erbt er.
2. Das Fenster wartet auf `/api/gesundheit`. Solange der Dienst-Prozess lebt,
   wird er nicht abgeschossen (die Einrichtung der Rechenumgebung kann lange
   dauern); nach 120 s zeigt das Fenster nur einen Hinweis.
3. Endet das Fenster, endet der Dienst (`VERMERK_ELTERN_PID`, Wache im Dienst).

## Pakete

| Ordner | Inhalt | darf importieren |
|---|---|---|
| `protokoll_assistent/services/`, `utils/` | Verarbeitung | weder Qt noch FastAPI |
| `protokoll_assistent/ablauf/` | Steuerung, Warteschlange, Geräteautomatik, Bibliothek | services, utils |
| `protokoll_assistent/api/` | FastAPI-Anwendung | ablauf, services, utils |
| `protokoll_assistent/server/` | Servermodus (Eingangsordner) | ablauf, services, utils – nie eine Oberfläche, nie Qt |
| `oberflaeche/` | SvelteKit-Oberfläche + `src-tauri/` (Fenster) | – |

Die alte Qt-Oberfläche (`protokoll_assistent/gui/`, `app.py`,
`protokoll_assistent.spec`) ist im November 2026 entfernt worden; PySide6 ist
keine Abhängigkeit mehr.

## Regeln (viele davon Lehren aus einem ähnlich gebauten Projekt)

### Prozess und Fenster
* Genau **ein** Überwachungsfaden für den Dienst, mit einem Neustart-Budget
  (3 Versuche, Abstand wächst), das erst nach einer gesunden Antwort
  zurückgesetzt wird. Nie mehrere Wächter, die sich gegenseitig neu starten.
* Nur den **selbst gestarteten** Prozess beenden – nie per Programmname
  (`taskkill /IM`). Keine fremden, verwaisten Dienste übernehmen.
* **Nur One-Directory-Builds**, nie One-File (jeder harte Abbruch hinterließ
  dort hunderte MB in `%TEMP%\_MEI…`; dazu Regel 7 in `CLAUDE.md`).
* Prozesssteuerung (Dienst starten/stoppen) ist **kein** Tauri-Befehl, den die
  Webseite aufrufen kann.
* `__COMPAT_LAYER` mit `RUNASADMIN` wird beim Start des Fensters entfernt;
  mitgeliefertes Python läuft mit `-B -s` (kein `__pycache__` im
  Programmordner, keine Nutzer-site-packages).
* Zum Entwickeln: `VERMERK_EXTERNER_DIENST=http://127.0.0.1:<port>` lässt das
  Fenster einen von Hand gestarteten Dienst benutzen und nie beenden.

### Programmschnittstelle
* **Kein Betrieb ohne Schlüssel**, auch nicht zum Entwickeln
  (`--entwicklung` erzeugt einen und legt ihn in `api_zugang.json` ab).
* Geschützt wird über eine Abhängigkeit am Router; neue Endpunkte sind von
  selbst geschützt. Ein Test ruft **jeden** Endpunkt aus der
  Schnittstellenbeschreibung ohne Anmeldung auf und erwartet 401.
* Literale Routen vor Routen mit Platzhaltern (`/export/formate` vor
  `/{kennung}`); ein Platzhalter verschluckt sonst das Literal.
* Ein Strom (`StreamingResponse`) liefert nur `str`/`bytes`. Ein `dict` fällt
  erst beim Senden auf und ergibt eine leere 200-Antwort.
* Lang laufende Arbeit nie in der Ereignisschleife: in die
  Auftragswarteschlange oder in einen Faden. Endpunkte mit Platten- oder
  Netzzugriff sind synchrone Funktionen.
* Hosts werden geprüft (`TrustedHostMiddleware`, Schutz gegen DNS-Rebinding);
  im Browser zusätzlich `SameSite=Strict`-Cookie und Kopfzeile
  `X-Vermerk-Anfrage: 1` bei ändernden Anfragen.
* Im Netz nur Pfade in freigegebenen Ordnern (`Dienste.pfad_pruefen`).
* `oberflaeche/openapi.json` ist der Vertrag zwischen Dienst und Oberfläche,
  eingecheckt; ein Test schlägt fehl, wenn er nicht zum Code passt
  (neu erzeugen: `uv run python -m protokoll_assistent.api openapi > oberflaeche/openapi.json`).

### Ereignisse
* Oberfläche lädt `/api/zustand` (enthält `letzte_nummer`) und abonniert dann
  `/api/ereignisse?seit=<nummer>`. Fehlen Ereignisse (Puffer übergelaufen),
  kommt `neu_laden`.
* Gelesen wird mit `fetch` + `ReadableStream`, **nicht** mit `EventSource`
  (das kann keine `Authorization`-Kopfzeile). Wiederverbinden nach 3 s mit
  `Last-Event-ID`. Bei 401/403 nicht endlos wiederholen.

### Oberfläche
* **Ein Startgatter**: Keine Anfrage, kein Abo, kein Abfragen, bevor Basis-URL
  und Schlüssel feststehen (im Tauri-Fenster per Befehl `zugang`). Alle
  Anfragen laufen über **ein** Modul, das die Kopfzeile setzt – kein loses
  `fetch` in Komponenten.
* Gestreamter Text wird gedrosselt gerendert; Markdown erst am Ende.
* In der gebauten Fassung gibt es keine Entwicklerwerkzeuge: `console.warn`/
  `console.error` und unbehandelte Fehler gehen begrenzt (höchstens 500 je
  Lauf) an das Protokoll des Fensters – `console.log` nicht (kann Inhalte
  enthalten).
* Keine Übersetzungen beim Import lesen; Texte sind Deutsch.
* Beispiel-`.env`-Dateien setzen keine Überschreibungen (nur auskommentiert).
* Alle Build-Werkzeuge lokal aus `package-lock.json`, nichts aus einem CDN.

### Build, Release, CI
* Version an **einer** Stelle pflegen und gegenprüfen: `pyproject.toml`,
  `protokoll_assistent/version.py`, `oberflaeche/package.json`,
  `oberflaeche/src-tauri/tauri.conf.json` und der Tag müssen übereinstimmen.
* PyInstaller: `optimize=0` (asserts bleiben), `upx=False`, `strip=False`.
* Vor jedem Release startet die CI den **gebauten** Dienst mit Schlüssel und
  ruft `/api/gesundheit` und `/api/info` auf (Rauchtest mit eingeschalteter
  Anmeldung – genau diese Fehler fand vorher niemand).
* `@tauri-apps/*` (npm) und die Rust-Crates auf demselben Major.Minor.
* Bündel-Ressourcen vor `cargo build` bereitstellen (Tauri prüft sie beim
  Kompilieren).

## Nutzer, Geräte und Daten

| | Windows-Anwendung | Servermodus |
|---|---|---|
| Menschen | einer | mehrere, eindeutig angemeldet |
| Anmeldung | Schlüssel je Start (Fenster); „im Netz anbieten": feste Zugangsschlüssel, derselbe eine Mensch | Name + Passwort **und/oder** persönliche Zugangsschlüssel – die Firma wählt; Microsoft-Anmeldung (Entra ID) später, App-Registrierung beim Kunden |
| Daten | wie bisher (`ausgabe/`, `aufnahmen/`) | je Nutzer `…/nutzer/<name>/`; Besprechungen teilbar mit Einzelnen oder allen (lesen, herunterladen, im Chat fragen; ändern nur der Besitzer) |
| Aufnahmegeräte | beliebig viele, alle gehören dem einen Menschen | jedes Gerät gehört einem Nutzer; seine Aufnahmen landen in dessen Ordner. Ohne Besitzer: allgemeiner Ordner, nur für Admins |
| Admin | – (der eine Mensch darf alles) | verwaltet Nutzer, Geräte, Einstellungen, Schlüssel; sieht Auftragstitel, aber keine fremden Inhalte |
| Warteschlange | eine | eine für alle; fremde Aufträge erscheinen als „Andere Verarbeitung" mit Stand, ohne Inhalt |

Die Geräte-Firmware ändert sich dafür nicht: Das Token bestimmt das Gerät, die
Zuordnung zum Nutzer steht nur auf dem Server. Geräte, die sich mehrere
Menschen teilen (Auswahl „wer bin ich" am Gerät), wären ein späterer,
eigener Schritt mit Firmware-Änderung.

Erster Admin im Container: `python -m protokoll_assistent.api nutzer-anlegen <Name> --admin`
(gibt einen Zugangsschlüssel einmal aus) oder vorübergehend `VERMERK_ZUGANG` setzen.

## Ersteinrichtung

Nur in der Windows-Anwendung (Rolle `desktop`, sonst 403); Endpunkte in
`api/routen_einrichtung.py`, Datenformen `Einrichtung*` in `api/modelle.py`.
Die Seiten führt die Oberfläche selbst; der Dienst liefert Zahlen und schreibt
dieselben Einstellungen wie früher der Qt-Assistent (`gui/ersteinrichtung.py`,
inzwischen entfernt).
Grundregel: **Nichts wird ohne `zustimmung: true` im Aufruf geladen.**

| Seite | Endpunkt | Was er tut |
|---|---|---|
| Start | `GET /api/einrichtung/stand` | `einrichtung_abgeschlossen`, `naechster_schritt` (`willkommen` / `neustart` / `mitschrift` / `fertig`), Arbeitsweise, `vorhanden`, `offen` (fehlende Bausteine), `neustart_noetig`, laufende Einrichtungsaufträge. Lädt nichts. |
| Willkommen | – | reiner Text |
| VERMERK Raum (optional) | `POST /api/geraete`, `PATCH /api/einstellungen {"geraete_empfang_aktiv": true}` | Gerät anlegen, Token einmal anzeigen. Das Beschreiben des Geräts per USB gibt es (noch) nicht über die Schnittstelle. |
| Ihr Computer | `GET /api/einrichtung/rechner[?neu=true]` | Hardware, je Schritt (`mitschrift`, `sprecher`, `protokoll`, `chat`) Stufe `gut`/`maessig`/`nicht` mit `dauer_von`/`dauer_bis` in `einheit` und `ort`, Empfehlung `lokal`/`gemischt`/`api`/`null`, machbare Modelle mit `empfohlen`. Einmal je Dienst ermittelt. |
| Arbeitsweise | `POST /api/einrichtung/entscheidung` | `{transkription, nachbearbeitung, chatbot: "lokal"\|"api", sprachmodell?, whisper_modell?, zustimmung_rechenumgebung}`. Ein Online-Dienst wird nie vorausgewählt. |
| Online-Dienst | `POST /api/einrichtung/anbieter` | `{bereich, anbieter, endpunkt?, modell?, schluessel?, merken}` – trägt Adresse und Modell des Anbieters ein (Liste: `GET /api/einstellungen/anbieter`). |
| Was nötig ist | `GET /api/einrichtung/kosten[?transkription=…&nachbearbeitung=…&chatbot=…]` | Bausteine mit Download/Platz in GB, Summe, Downloaddauer bei 50 Mbit/s, `platz_knapp`, `zustimmung_noetig`, Ollama-Lizenzlinks. Mit Parametern nur Vorschau. |
| Einrichtung | `POST /api/einrichtung/ffmpeg`, `/ollama`, `/modelle` | Aufträge (`einrichtung_ffmpeg`/`_ollama`/`_modelle`, Vorrang −5); Fortschritt wie bei jedem Auftrag über `/api/ereignisse`. Ollama: vom Hersteller laden, Signatur „Ollama Inc." prüfen, still installieren, Dienst starten (nie mitgeliefert). Ein zweiter Aufruf liefert den laufenden Auftrag. |
| Mitschrift | `POST /api/einrichtung/modelle {whisper, sprechertrennung, hf_token?}` | Whisper und pyannote – nur, wenn der Dienst schon in der Rechenumgebung läuft (sonst 409). `angaben.teile` zeigt, was einzeln gelang. |
| Fertig | `POST /api/einrichtung/abschliessen` | `einrichtung_abgeschlossen`; Antwort wie `stand` mit `neustart_noetig` und `online_ohne_anbieter`. |
| „Später" | `POST /api/einrichtung/spaeter {nicht_mehr_fragen}` | bricht wartende Einrichtungsaufträge ab; mit `nicht_mehr_fragen` gilt die Einrichtung als abgeschlossen, ohne Zustimmung wird die Rechenumgebung zurückgestellt. |

**Rechenumgebung und Neustart.** PyTorch & Co. richtet `bootstrap.py` beim
nächsten Start des Dienstes ein – nur mit Zustimmung (`entscheidung` mit
`zustimmung_rechenumgebung: true` setzt `einrichtung_fortsetzen="transkription"`;
ohne Zustimmung `lokale_einrichtung_zurueckgestellt=true`). Steht in einer
Antwort `neustart_noetig: true`, sagt die Oberfläche „Die App startet kurz neu";
den Dienst neu zu starten ist Sache des Fensters. Danach meldet `stand`
`naechster_schritt: "mitschrift"`.

## Was bewusst so bleibt
* Die Geräteschnittstelle (`GERAETE-SCHNITTSTELLE.md`, Port 8765) ändert sich
  nicht – die Firmware verlässt sich Byte für Byte darauf.
* Inno Setup bleibt der Installer (er liefert auch Python und Quelltext für
  den lokalen Modus); das Tauri-Fenster ist darin eine weitere Datei.
* Deutsche Bezeichner, keine Umbenennung bestehender Dateien.
