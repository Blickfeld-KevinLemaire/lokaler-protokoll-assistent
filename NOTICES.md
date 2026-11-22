# Hinweise zu Software von Dritten

VERMERK Desktop benutzt Software anderer Urheber. Dieser Text nennt
sie, ihre Lizenzen und die Pflichten, die sich daraus ergeben.

Die vollstaendigen Lizenztexte liegen im Ordner [`lizenzen/`](lizenzen/) und
werden zusammen mit der Anwendung ausgeliefert.

Die Lizenz fuer VERMERK Desktop selbst steht in [`LICENSE`](LICENSE)
und wird von diesem Text nicht beruehrt.

---

## 1. Im Programm enthalten (wird mit der EXE ausgeliefert)

### Qt 6 und PySide6 / shiboken6 (Version 6.11.2)

* Urheber: The Qt Company Ltd. und Mitwirkende
* Gewaehlte Lizenz: **GNU Lesser General Public License, Version 3**
  ([`lizenzen/lgpl-3.0.txt`](lizenzen/lgpl-3.0.txt))
* Die LGPL-3.0 baut auf der GPL-3.0 auf; deren Text liegt ebenfalls bei
  ([`lizenzen/gpl-3.0.txt`](lizenzen/gpl-3.0.txt)).
* Bezugsquelle: https://www.qt.io — https://pypi.org/project/PySide6/

PySide6 wird wahlweise unter LGPL-3.0, GPL-2.0 oder GPL-3.0 angeboten. Fuer
dieses Programm wird ausdruecklich die **LGPL-3.0** gewaehlt.

**Wie die Pflichten der LGPL-3.0 erfuellt werden**

| Pflicht | Umsetzung |
|---|---|
| Qt darf nur dynamisch eingebunden werden | Der Build ist ein One-Directory-Build (`exclude_binaries=True` + `COLLECT`). Die Qt-Bibliotheken liegen als eigene `.dll`- und `.pyd`-Dateien neben der EXE, nicht darin. |
| Anwender muessen Qt austauschen koennen | Die Dateien liegen offen im Programmordner und koennen durch eine andere Qt-Fassung derselben Hauptversion ersetzt werden. Es gibt keine Signatur- oder Integritaetspruefung, die das verhindert. |
| Qt darf nicht veraendert sein, sonst muessen die Aenderungen offengelegt werden | Qt und PySide6 werden unveraendert aus den offiziellen Paketen uebernommen. |
| Lizenztext und Hinweis muessen beiliegen | Dieser Text und der Ordner `lizenzen/`. |
| Kein Komprimieren/Strippen, das den Austausch erschwert | In der Build-Spezifikation sind `upx=False` und `strip=False` gesetzt. |

> Bitte diese vier Punkte nicht unbeabsichtigt aendern. Ein Wechsel auf einen
> One-File-Build, statisches Linken oder eine Integritaetspruefung der DLLs
> wuerde die LGPL-Bedingungen verletzen — dann waere eine kommerzielle
> Qt-Lizenz noetig.

### python-docx (1.2.0)

* Lizenz: MIT — Copyright (c) Steve Canny
* Wird fuer den Export als Word-Datei benutzt
  (`protokoll_assistent/services/export_service.py`).

### sounddevice (0.5.x) und PortAudio

* sounddevice — Lizenz: MIT — Copyright (c) Matthias Geier
* PortAudio — Lizenz: MIT — Copyright (c) Ross Bencina und Phil Burk
* Das Windows-Wheel von sounddevice bringt vorkompilierte PortAudio-DLLs mit
  (32-/64-Bit/ARM64, jeweils mit und ohne ASIO). Verwendet wird ausschliesslich
  die Standardvariante ohne ASIO; die ASIO-DLL wird nicht angesprochen, die
  proprietaere Steinberg-ASIO-SDK-Frage stellt sich damit nicht.
* Wird fuer die Mikrofonaufnahme (Voice Recording) benutzt
  (`mikrofon_aufnahme.py`) und lokale Variante
  (`protokoll_assistent/services/recording_service.py`).

### keyring (25.7.0)

* Lizenz: MIT — Copyright (c) Kang Zhang
* Wird benutzt,
  um API-Schluessel optional ueber die Windows-Anmeldeinformationsverwaltung
  dauerhaft zu speichern (`services/secret_store.py`) — nie als
  Klartext-Datei. Optional: Der Anwender kann Schluessel stattdessen nur fuer
  die laufende Sitzung eingeben, dann wird `keyring` gar nicht angesprochen.

### pyserial (3.5)

* Lizenz: BSD-3-Clause — Copyright (c) 2001-2020 Chris Liechti
* Wird benutzt, um die WLAN-Aufnahmegeraete ueber das USB-Kabel einzurichten
  (`services/geraete_usb_service.py`). Reines Python, ohne eigene DLL.

### truststore (0.10.5)

* Lizenz: MIT — Copyright (c) Seth Michael Larson und Quentin Pradet
* Laesst Python Zertifikate ueber die Pruefung des Betriebssystems (unter Windows: CryptoAPI) statt ueber den
  eigenen Speicher pruefen (`utils/netz.py`). Reines Python. Damit gelten auch Zertifikate von Firmennetzen,
  denen Windows traut.

### Hilfspakete von keyring und sounddevice

Sie kommen als Abhaengigkeiten mit und liegen als reines Python (cffi: mit einer kleinen Erweiterung) im Build:

* pywin32-ctypes (0.2.3) — BSD-3-Clause — Copyright (c) Enthought, Inc.
* jaraco.classes (3.4.0), jaraco.functools (4.6.0), jaraco.context (6.1.2), zipp (4.1.0),
  backports.tarfile (1.2.0) — MIT — Copyright (c) Jason R. Coombs
* more-itertools (11.1.0) — MIT — Copyright (c) Erik Rose
* importlib-metadata (9.0.1) — Apache-2.0 — Copyright (c) Jason R. Coombs
* cffi (2.1.1) — MIT-0 — Copyright (c) Armin Rigo, Maciej Fijalkowski
* pycparser (3.0) — BSD-3-Clause — Copyright (c) Eli Bendersky und Mitwirkende

### lxml (6.1.3)

* Lizenz: BSD-3-Clause — Copyright (c) Infrae und Mitwirkende
* Enthaelt libxml2 und libxslt (MIT).
* Wird von python-docx benoetigt.

### typing-extensions (4.16.0)

* Lizenz: Python Software Foundation License, Version 2

### Meet2Notes (0.6.2) — Vorbild, kein mitgelieferter Fremdcode

* Lizenz: MIT — Copyright (c) 2026 Meet2Notes contributors
  ([`lizenzen/meet2notes-mit.txt`](lizenzen/meet2notes-mit.txt))
* Aus Meet2Notes stammen die **Ideen** fuer: wortgenaue Sprecherzuordnung,
  wiederholte Verdichtung, Anhoeren/Export je Sprecher, dauerhafte
  Sprecherprofile und Protokollvorlagen mit festen Abschnitten. Die
  Umsetzung in VERMERK Desktop ist eigener Code auf Basis der
  vorhandenen Dienste (pyannote-Embeddings, FFmpeg, Ollama/API).
* Der Lizenztext liegt der Transparenz halber bei. Wird kuenftig Code oder
  Text unveraendert oder angepasst uebernommen, gehoert der Kopfkommentar
  der betroffenen Datei dazu.

### Open WebUI — Vorbild, kein Fremdcode

* Die Idee des Chatbots „Frag mein Meeting“ (Fragen an eigene Dokumente, mit
  Suche in Textabschnitten und Antwort eines lokalen Modells) kennt man aus
  Werkzeugen wie Open WebUI. Open WebUI ist eine Webanwendung mit eigener
  Lizenz (BSD-3-Clause mit Zusatzbedingungen zum Markennamen) und schweren
  Abhängigkeiten. Es wurde **kein Code daraus übernommen**; der Chatbot ist
  eine eigene, kleine Umsetzung in `services/chat_service.py`.

### Tauri 2 — das Fenster `VERMERK.exe` (ab 0.6.0)

* `tauri` 2.12.7, `tauri-build` 2.7.6, `tauri-runtime-wry` 2.12.5, `wry` 0.57.3,
  `tao` 0.37.3 und die Plugins `tauri-plugin-dialog` 2.8.4,
  `tauri-plugin-single-instance` 2.5.5, `tauri-plugin-log` 2.10.2
* Urheber: The Tauri Programme within The Commons Conservancy und Mitwirkende
* Lizenz: wahlweise **MIT** oder **Apache-2.0** (gewaehlt: MIT)
* Bezugsquelle: https://tauri.app — https://github.com/tauri-apps/tauri
* Weitere Rust-Bibliotheken in der EXE (vollstaendig in
  `oberflaeche/src-tauri/Cargo.lock`): ganz ueberwiegend MIT und/oder
  Apache-2.0, daneben Unicode-3.0, Zlib, BSD-3-Clause, 0BSD, CC0-1.0 und
  Unlicense — alles freizuegige Lizenzen ohne Offenlegungspflicht, verlangt
  wird nur der Urheberhinweis (dieser Text). Darunter u. a. `windows-sys`
  (Microsoft, MIT oder Apache-2.0), `webview2-com` (MIT), `serde`,
  `serde_json`, `log`, `time`, `base64`, `getrandom` (je MIT oder Apache-2.0).
* **MPL-2.0** (dateibezogenes Copyleft): `cssparser`, `cssparser-macros`,
  `selectors`, `dtoa-short` (ueber `tauri-utils`) und `option-ext` (ueber
  `dirs`). Sie werden **unveraendert** von crates.io uebernommen; ihr
  Quelltext ist dort in genau der Fassung aus `Cargo.lock` oeffentlich
  erhaeltlich. Werden sie je veraendert, muessen die geaenderten Dateien
  offengelegt werden — der uebrige Code nicht.
* Rust-Standardbibliothek: MIT oder Apache-2.0.

### Microsoft Edge WebView2 — wird nicht mitgeliefert

Das Fenster zeigt die Oberflaeche mit der WebView2-Laufzeit von Microsoft an.
Sie ist unter Windows 10 und 11 Bestandteil des Systems (Evergreen Runtime)
und wird **weder** in die EXE noch in den Installer gepackt. Es gelten die
Bedingungen von Microsoft zwischen Microsoft und dem Anwender. Fehlt sie auf
einem Rechner ausnahmsweise, laesst sie sich kostenlos von Microsoft
installieren: https://developer.microsoft.com/microsoft-edge/webview2/

### Der Dienst `dienst\vermerk-dienst.exe` (ab 0.6.0)

Der Dienst ist wie die bisherige EXE ein PyInstaller-Build (One-Directory,
siehe unten) und enthaelt **kein** Qt. Zusaetzlich zu den oben genannten
Paketen (python-docx, sounddevice, keyring, pyserial, truststore, lxml …):

| Paket | Fassung | Lizenz |
|---|---|---|
| FastAPI | 0.165.0 | MIT |
| Starlette | 1.10.0 | BSD-3-Clause |
| uvicorn | 0.54.0 | BSD-3-Clause |
| h11 | 0.16.0 | MIT |
| anyio | 4.16.0 | MIT |
| click | 8.5.1 | BSD-3-Clause |
| pydantic / pydantic-core | 2.14.4 / 2.50.5 | MIT |
| python-multipart | 0.0.34 | Apache-2.0 |
| ReportLab (PDF-Export) | 5.1.0 | BSD-3-Clause |
| Pillow (von ReportLab benutzt) | 13.0.0 | MIT-CMU (HPND) |

Die genauen Fassungen eines Builds stehen in `uv.lock`.

### PyInstaller (6.22.3) — nur der Startlader

* Lizenz: GPL-2.0 **mit Ausnahmeregelung**
* Die Ausnahme in der PyInstaller-Lizenz erlaubt ausdruecklich, die damit
  erzeugten Programme unter einer beliebigen Lizenz weiterzugeben — auch
  unter einer proprietaeren. Die GPL erstreckt sich also **nicht** auf den
  VERMERK Desktop.
* Siehe https://pyinstaller.org/en/stable/license.html

### Python

* Lizenz: Python Software Foundation License, Version 2
* Die Laufzeitumgebung wird mit ausgeliefert.

Das gilt an zwei Stellen:

1. **In den gebauten EXEs.** PyInstaller bettet die Laufzeitumgebung ein.
2. **Als eigener Ordner `python\` im Installer** (CPython 3.11.16). Damit
   muss der Anwender kein Python selbst installieren, um die vollstaendig
   lokale Anwendung zu benutzen. Verwendet wird ein unveraenderter,
   eigenstaendiger Build von
   [python-build-standalone](https://github.com/astral-sh/python-build-standalone)
   (dieselben Builds, die auch `uv` verteilt). Fassung und Pruefsumme stehen
   fest eingetragen in
   [`installer/python-laufzeit-holen.ps1`](installer/python-laufzeit-holen.ps1).
   Der PSF-Lizenztext liegt als `python\LICENSE.txt` im Programmordner bei.

Der mitgelieferte Build enthaelt ausserdem `pip` (MIT) mit seinen
mitgelieferten Abhaengigkeiten; deren Lizenztexte liegen unveraendert in
`python\Lib\site-packages\pip\_vendor\`.

---

## 2. Vom Anwender selbst installiert (wird nicht mitgeliefert)

Diese Bestandteile richtet der Anwender auf seinem Rechner ein. Sie werden
nicht von uns weitergegeben; ihre Lizenzen gelten zwischen dem Anwender und
dem jeweiligen Urheber.

| Bestandteil | Lizenz | Hinweis |
|---|---|---|
| FFmpeg | LGPL-2.1+ oder GPL-2.0+, je nach Build | Die ueblichen Windows-Builds sind GPL. Deshalb wird FFmpeg **nicht** mitgeliefert, sondern vom Anwender bereitgestellt oder auf seinen Wunsch heruntergeladen. |
| PyTorch, torchaudio | BSD-3-Clause | in `.venv-whisperx` |
| faster-whisper, CTranslate2 | MIT | Transkription; ersetzt seit 19.09.2026 WhisperX (siehe unten). Auf AMD-Karten die ROCm-Fassung von CTranslate2 (4.9.0, ebenfalls MIT) von dessen Release-Seite |
| AMD ROCm (`rocm`, `rocm-sdk-core`, `rocm-sdk-libraries-custom`, 7.2.1) | die Lizenzen der einzelnen ROCm-Bibliotheken von AMD; die pip-Pakete selbst nennen keine Lizenz (Stand 18.11.2026) – bei einer kommerziellen Verwertung pruefen | nur auf AMD-Karten, von AMD (`repo.radeon.com`) in die Laufzeitumgebung geladen; wird **nicht** mitgeliefert |
| PyAV (`av`) | BSD-3-Clause | Audio-Dekodierung fuer faster-whisper |
| pyannote.audio | MIT | in `.venv-whisperx` |
| huggingface_hub | Apache-2.0 | Modell-Download |
| Ollama | MIT | eigenstaendiges Programm. Wird **nicht** mitgeliefert: Die Ersteinrichtung laedt den offiziellen Installer auf Wunsch des Anwenders direkt vom Hersteller und installiert ihn fuer dessen Benutzerkonto. Grund: Ollama bringt Laufzeitbibliotheken von NVIDIA (CUDA) und AMD (ROCm) unter deren eigenen Bedingungen mit, die wir nicht weitergeben. Bedingungen des Herstellers: https://ollama.com/terms |

**Warum kein WhisperX mehr:** WhisperX ist eine Huelle um faster-whisper und
hat den gesamten Abhaengigkeitsbaum festgenagelt (`torch~=2.8.0`,
`huggingface-hub<1.0.0`). Dadurch waren 17 bekannte Sicherheitsluecken in
`torch`, `transformers` und `nltk` unvermeidbar, und keine davon liess sich
beheben -- WhisperX 3.8.6 ist die neueste Fassung. Ohne WhisperX loest
derselbe Funktionsumfang auf `torch` 2.14 auf; `transformers` und `nltk`
entfallen ganz, und `pip-audit` meldet keine Luecken mehr.

---

## 3. Modelldateien

Modellgewichte sind keine Programmbibliotheken und stehen unter eigenen
Bedingungen. Sie werden **nicht** mitgeliefert; der Anwender laedt sie selbst
und stimmt dabei den jeweiligen Bedingungen zu.

| Modell | Bedingungen |
|---|---|
| `pyannote/speaker-diarization-community-1` | Zugang ueber Hugging Face, Zustimmung zu den dortigen Nutzungsbedingungen erforderlich (Token). |
| Whisper-Modelle (faster-whisper/CTranslate2) | MIT (Modell von OpenAI unter MIT) |
| `bge-m3` (Suchmodell fuer „Frag mein Meeting“, ueber Ollama) | MIT (BAAI) |
| `hf.co/LiquidAI/LFM2.5-2.6B-GGUF:Q4_K_M` (LFM2.5-2.6B, Liquid AI, ueber Ollama) | **LFM Open License v1.0** — kommerzielle Nutzung bis 10 Mio. USD Jahresumsatz kostenlos, darueber ist eine Vereinbarung mit Liquid AI noetig. Wird wie die uebrigen Ollama-Modelle **nicht** mitgeliefert, sondern auf Wunsch des Anwenders zur Laufzeit ueber Ollama geladen (Modell-Id `hf.co/LiquidAI/LFM2.5-2.6B-GGUF:Q4_K_M`). |
| Ollama-Modelle | Je Modell unterschiedlich. Qwen3.5, Qwen3.8 und Gemma 4 aus der Auswahl stehen unter Apache 2.0, LFM2.5 unter der LFM Open License (eigene Zeile oben). Von Hand eingetragene Modelle (z. B. Llama oder Gemma 3) haben eigene Lizenzen mit eigenen Auflagen. Vor einer kommerziellen Nutzung bitte je Modell pruefen. |

---

## 4. Was bei einer kommerziellen Verwertung zu pruefen ist

Dieser Text ist eine technische Bestandsaufnahme und keine Rechtsberatung.
Vor einem Verkauf sollten vor allem diese Punkte geklaert werden:

1. **Die vier LGPL-Punkte oben bleiben eingehalten.** Sie sind beim heutigen
   Build erfuellt; ein Wechsel der Build-Form waere der wahrscheinlichste
   Weg, das zu verlieren.
2. **FFmpeg bleibt beim Anwender.** Sobald ein GPL-Build mitgeliefert wird,
   stellt sich die Frage der GPL-Wirkung auf das Gesamtpaket neu.
3. **Modellgewichte einzeln freigeben lassen.** Das ist der Punkt, der am
   haeufigsten uebersehen wird.

Stand: 19.09.2026. Die Versionsangaben beziehen sich auf `uv.lock` und
`protokoll_assistent/requirements-anwendung.txt`.
