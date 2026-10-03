# Protokoll-Assistent

Transkribiert Besprechungsaufnahmen (mit Sprechertrennung) und erstellt daraus
anschliessend - als getrennter, unabhaengiger Schritt - mit einem frei
waehlbaren Sprachmodell ein Ergebnisdokument nach freier Wahl (Zusammenfassung,
Agenda, Prioritaetenliste, ...).

Es ist **eine** Anwendung. Fuer beide Arbeitsschritte gibt es je zwei Wege, und
die Wahl ist eine **Einstellung im Programm** - kein eigenes Programm, kein
zweiter Download, kein Neustart in eine andere Anwendung:

| Schritt | lokal | ueber eine Schnittstelle (API) |
|---|---|---|
| **Transkription** | faster-whisper + pyannote.audio, vollstaendig offline | Anbieter aus einer Liste waehlbar (OpenAI, Mistral, Azure, Groq, Scaleway, OpenRouter) oder eigener Endpunkt - siehe [API-Anbieter](#api-anbieter) |
| **Nachbearbeitung** | Ollama, dreistufig, vollstaendig offline | Anbieter aus einer Liste waehlbar (IONOS, STACKIT, Mistral, OpenAI, Anthropic, Azure, Google u. a.) oder eigener Endpunkt (Chat-Completions) |

Beides laesst sich unabhaengig voneinander einstellen: lokal transkribieren und
per API nachbearbeiten ist genauso moeglich wie umgekehrt.

**Was das fuer den Datenschutz heisst:** Im lokalen Modus verlaesst nichts das
Geraet. Sobald fuer einen Schritt eine Schnittstelle eingestellt ist, wird
dafuer Audio bzw. Transkript an den dort eingetragenen Anbieter uebertragen -
das Programm weist im Einstellungsdialog ausdruecklich darauf hin.

**Was das fuer die Installation heisst:** Wer ausschliesslich ueber eine
Schnittstelle arbeitet, braucht weder PyTorch noch ein KI-Modell auf der
Platte - der Start ist dann schnell und schlank. Die schwere Laufzeitumgebung
richtet sich nur dann selbst ein, wenn beim Start „Lokal" als
Transkriptionsmodus gespeichert ist.

> **Hinweis zur Versionsgeschichte:** Bis September 2026 waren das drei
> getrennte Programme (eine tkinter-„Cloud-Variante", eine lokale
> PySide6-Anwendung und ein Auswahlfenster davor). Sie sind zu dieser einen
> Anwendung zusammengefuehrt worden. Die tkinter-Variante ist entfallen; ihr
> Weg ueber eine Schnittstelle lebt als Einstellung weiter.

## Starten

```powershell
python -m protokoll_assistent.app
```

Oder bequemer ueber `protokoll_assistent\Start-Protokoll-Assistent.ps1`, den
Startmenue-Eintrag des Installers oder die Desktop-Verknuepfung.

Die Anwendung wird bewusst **als Modul** gestartet (`-m`), nicht ueber den
Dateipfad: Nur so findet Python das Paket.

## Ordnerstruktur

```
protokoll_assistent.spec       PyInstaller-Spezifikation (baut die Anwendung)
installer/                     Inno-Setup-Installer

protokoll_assistent/
  app.py                       Einstiegspunkt
  bootstrap.py                 richtet bei Bedarf die lokale ML-Umgebung ein
  gui/                         Oberflaeche (PySide6)
  services/                    Verarbeitungskette und API-Dienste
  utils/                       Pfade, Konfiguration, Diagnose, Logging
  tests/                       Testsuite
  einstellungen/               mitgelieferte Systemprompt-Vorlage
  konfiguration.json           Ihre Einstellungen (wird nicht versioniert)
  ausgabe/                     Volltranskript mit Sprechertrennung (TXT + JSON)
  aufnahmen/                   per Mikrofon aufgenommene WAV-Dateien
  arbeitsdaten/                Zwischenstaende langer Aufnahmen (fortsetzbar)
  logs/                        protokoll_assistent.log
```

Die Ordner werden beim Start automatisch angelegt, falls sie fehlen.

Der Projektordner selbst kann beliebig heissen und an einem beliebigen Ort
liegen (lokale Festplatte, USB-Stick, Netzlaufwerk, ...) - alle Skripte
ermitteln ihren Ordner automatisch anhand ihres eigenen Speicherorts.

## Installation unter Windows (Installer)

Der Installer aus dem
[Release-Bereich](https://github.com/Blickfeld-KevinLemaire/lokaler-protokoll-assistent/releases)
(`Protokoll-Assistent-Setup-<Version>.exe`) installiert ohne
Administratorrechte pro Benutzer, legt einen Startmenue-Eintrag an und laesst
sich normal ueber „Apps & Features" wieder entfernen.

Er bringt alles mit, was gebraucht wird - auch eine eigene
Python-Laufzeitumgebung fuer den lokalen Modus. Vorinstallieren muessen Sie
nichts.

Der Installer ist **nicht signiert**. Windows SmartScreen meldet sich deshalb
beim Start; ueber „Weitere Informationen" -> „Trotzdem ausfuehren" laesst er
sich starten.

## Installation aus dem Quellcode

```powershell
git clone https://github.com/Blickfeld-KevinLemaire/lokaler-protokoll-assistent.git
cd lokaler-protokoll-assistent
powershell -ExecutionPolicy Bypass -File protokoll_assistent\Einrichtung-Lokal.ps1
```

Fuer den reinen API-Betrieb genuegen die Pakete aus
`protokoll_assistent\requirements-anwendung.txt`:

```powershell
python -m pip install -r protokoll_assistent\requirements-anwendung.txt
python -m protokoll_assistent.app
```

## Voraussetzungen

* **Windows** - die einzige unterstuetzte Plattform.
* **Python 3.10 oder 3.11** (nur aus dem Quellcode; der Installer bringt ein
  eigenes mit).
* **FFmpeg** - wird fuer das Zuschneiden und Normalisieren der Audiodaten in
  *jedem* Modus gebraucht.
* **Nur fuer den lokalen Modus:** genug Platz fuer PyTorch und das
  Whisper-Modell; eine NVIDIA-GPU beschleunigt deutlich, CPU funktioniert
  auch (langsamer). Einzelheiten, empfohlene Modelle je Grafikkarte und die
  Fehlerbehebung stehen in
  [`protokoll_assistent/README.md`](protokoll_assistent/README.md).
* **Nur fuer den API-Modus:** ein API-Schluessel fuer den eingetragenen
  Endpunkt.

## API-Anbieter

Wer eine API nutzen will, waehlt in den Einstellungen (Reiter
*Transkription*, *Nachbearbeitung*, *Chatbot*) den Anbieter aus einer Liste;
Adresse und ein Modellvorschlag werden eingetragen, es fehlt nur noch der
Schluessel. **Ab Werk ist kein Anbieter gewaehlt** - ohne Auswahl wird nichts
uebertragen. Jeder andere Anbieter mit OpenAI-kompatibler Schnittstelle laesst
sich ueber „Eigener Endpunkt“ eintragen.

| Anbieter | Chat | Einbettungen | Transkription | Standort | Schluessel / Dokumentation |
|---|---|---|---|---|---|
| IONOS AI Model Hub | ja | ja | nein | Deutschland | [Doku](https://docs.ionos.com/cloud/ai/ai-model-hub/ai-model-hub) |
| STACKIT AI Model Serving | ja | ja | nein | Deutschland | [Doku](https://docs.stackit.cloud/products/data-and-ai/ai-model-serving/basics/introduction/) |
| Mistral AI | ja | ja | ja (Voxtral, mit Sprechern) | Frankreich/EU | [Schluessel](https://console.mistral.ai/api-keys) · [Doku](https://docs.mistral.ai/capabilities/audio_transcription) |
| Scaleway Generative APIs | ja | ja | ja (Whisper) | Frankreich/EU | [Schluessel](https://console.scaleway.com/iam/api-keys) · [Doku](https://www.scaleway.com/en/docs/generative-apis/reference-content/openai-compatibility/) |
| Microsoft Azure OpenAI | ja | ja | ja (Whisper) | Region waehlbar | [Portal](https://portal.azure.com/) · [Doku](https://learn.microsoft.com/en-us/azure/foundry/openai/reference) |
| OpenAI | ja | ja | ja (auch mit Sprechern) | USA | [Schluessel](https://platform.openai.com/api-keys) · [Doku](https://developers.openai.com/docs/guides/speech-to-text) |
| Anthropic (Claude) | ja | nein | nein | USA | [Schluessel](https://platform.claude.com/settings/keys) · [Doku](https://platform.claude.com/docs/en/api/openai-sdk) |
| Google Gemini | ja | ja | nein | USA | [Schluessel](https://aistudio.google.com/apikey) · [Doku](https://ai.google.dev/gemini-api/docs/openai) |
| Groq | ja | nein | ja (Whisper) | USA | [Schluessel](https://console.groq.com/keys) · [Doku](https://console.groq.com/docs/speech-to-text) |
| OpenRouter | ja | ja | ja (mit Sprechern ueber Azure) | Vermittler | [Schluessel](https://openrouter.ai/keys) · [Doku](https://openrouter.ai/docs/guides/overview/multimodal/stt) |

Die Modellnamen in der Anwendung sind Vorschlaege und aendern sich bei den
Anbietern oft; sie lassen sich im Dialog anpassen. Eine Sprechertrennung bei der
Transkription gibt es nur bei Mistral, OpenAI (Modell
`gpt-4o-transcribe-diarize`) und OpenRouter; bei den uebrigen kommt das
Transkript ohne Sprecher.

## API-Schluessel

Schluessel werden im Einstellungsdialog eingegeben. Auf Wunsch merkt sich die
Anwendung sie dauerhaft - dann liegen sie in der
**Windows-Anmeldeinformationsverwaltung**, nie als Klartext in einer Datei.
Ohne dieses Haekchen gilt der Schluessel nur fuer die laufende Sitzung.

In `konfiguration.json` steht ausschliesslich, *ob* gemerkt werden soll - nie
der Schluessel selbst.

## Bedienung

1. **Datei waehlen** - per Dialog, per Drag & Drop oder direkt ueber das
   Mikrofon aufnehmen.
2. **Einstellungen pruefen** - Sprache, Sprechertrennung, Offline-Modus; unter
   „Einstellungen" der Modus je Schritt und die Endpunkte.
3. **Transkription starten** - mit Fortschritt, Live-Vorschau und
   Restzeitschaetzung. Sprecher lassen sich anschliessend mit echten Namen
   versehen.
4. **Nachbearbeitung starten** - getrennt und unabhaengig, auch fuer ein
   frueher erzeugtes Transkript. Der Systemprompt laesst sich direkt im Fenster
   bearbeiten; eigene Vorlagen koennen benannt gespeichert werden.

### Ausgabedateien

* `ausgabe/<name>.txt` / `.json` - Volltranskript mit Sprechertrennung.
* Ergebnis der Nachbearbeitung als TXT und JSON, zusaetzlich als `.docx`.
* `arbeitsdaten/<hash>/` - Zwischenstaende langer Aufnahmen. Bricht ein Lauf
  ab, setzt der naechste dort fort, statt von vorne zu beginnen.

## Lange Aufnahmen

Lange Aufnahmen werden in Abschnitte („Chunks") zerlegt, die sich
ueberlappen; die Ueberlappung wird beim Zusammenfuehren wieder entfernt. Jeder
fertige Abschnitt wird sofort gesichert. Nach einem Abbruch (Absturz,
Stromausfall, geschlossenes Fenster) bietet die Anwendung an, die Verarbeitung
fortzusetzen - bereits transkribierte Abschnitte werden dann nicht erneut
berechnet.

## Lizenz und fremde Software

Der Quelltext ist oeffentlich lesbar, aber **nicht** zur Nutzung freigegeben -
siehe [`LICENSE`](LICENSE). Hinweise zu fremder Software stehen in
[`NOTICES.md`](NOTICES.md) und `lizenzen/`; beide werden mit dem Build
ausgeliefert.

PySide6 wird unter der **LGPL-3.0** verwendet. Der Build ist deshalb ein
One-Directory-Build, bei dem die Qt-Bibliotheken als eigene Dateien neben der
EXE liegen und sich austauschen lassen.

## Fuer die Weiterentwicklung

```powershell
uv sync                # Entwicklungsumgebung einrichten
uv run ruff check .    # Linting
uv run mypy            # Typpruefung
uv run pytest --cov    # Tests, bricht unter 85 % Abdeckung ab
```

Auf GitHub laufen dieselben Pruefungen automatisch, dazu CodeQL, gitleaks und
pip-audit. Einzelheiten, Regeln und die Gruende dahinter stehen in
[`CLAUDE.md`](CLAUDE.md).
