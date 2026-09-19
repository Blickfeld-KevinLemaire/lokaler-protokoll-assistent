# Hinweise zu Software von Dritten

Der Protokoll-Assistent benutzt Software anderer Urheber. Dieser Text nennt
sie, ihre Lizenzen und die Pflichten, die sich daraus ergeben.

Die vollstaendigen Lizenztexte liegen im Ordner [`lizenzen/`](lizenzen/) und
werden zusammen mit der Anwendung ausgeliefert.

Die Lizenz fuer den Protokoll-Assistenten selbst steht in [`LICENSE`](LICENSE)
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
  (`lokale_windows_app/services/export_service.py`).

### lxml (6.1.3)

* Lizenz: BSD-3-Clause — Copyright (c) Infrae und Mitwirkende
* Enthaelt libxml2 und libxslt (MIT).
* Wird von python-docx benoetigt.

### typing-extensions (4.16.0)

* Lizenz: Python Software Foundation License, Version 2

### PyInstaller (6.22.3) — nur der Startlader

* Lizenz: GPL-2.0 **mit Ausnahmeregelung**
* Die Ausnahme in der PyInstaller-Lizenz erlaubt ausdruecklich, die damit
  erzeugten Programme unter einer beliebigen Lizenz weiterzugeben — auch
  unter einer proprietaeren. Die GPL erstreckt sich also **nicht** auf den
  Protokoll-Assistenten.
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

## 2. Nur in der Cloud-Variante

### sv-ttk (2.6.1)

* Lizenz: MIT — Copyright (c) rdbende
* Erscheinungsbild der tkinter-Oberflaeche. Optional: fehlt das Paket, laeuft
  die Anwendung mit dem Standard-Design weiter.

---

## 3. Vom Anwender selbst installiert (wird nicht mitgeliefert)

Diese Bestandteile richtet der Anwender auf seinem Rechner ein. Sie werden
nicht von uns weitergegeben; ihre Lizenzen gelten zwischen dem Anwender und
dem jeweiligen Urheber.

| Bestandteil | Lizenz | Hinweis |
|---|---|---|
| FFmpeg | LGPL-2.1+ oder GPL-2.0+, je nach Build | Die ueblichen Windows-Builds sind GPL. Deshalb wird FFmpeg **nicht** mitgeliefert, sondern vom Anwender bereitgestellt oder auf seinen Wunsch heruntergeladen. |
| PyTorch, torchaudio | BSD-3-Clause | in `.venv-whisperx` |
| WhisperX | BSD-4-Clause | in `.venv-whisperx` |
| faster-whisper, CTranslate2 | MIT | in `.venv-whisperx` |
| pyannote.audio | MIT | in `.venv-whisperx` |
| huggingface_hub, transformers | Apache-2.0 | in `.venv-whisperx` |
| Ollama | MIT | eigenstaendiges Programm |

---

## 4. Modelldateien

Modellgewichte sind keine Programmbibliotheken und stehen unter eigenen
Bedingungen. Sie werden **nicht** mitgeliefert; der Anwender laedt sie selbst
und stimmt dabei den jeweiligen Bedingungen zu.

| Modell | Bedingungen |
|---|---|
| `pyannote/speaker-diarization-community-1` | Zugang ueber Hugging Face, Zustimmung zu den dortigen Nutzungsbedingungen erforderlich (Token). |
| Whisper-Modelle (faster-whisper/CTranslate2) | MIT (Modell von OpenAI unter MIT) |
| Llama 3.1 und andere Ollama-Modelle | Je Modell unterschiedlich. Llama 3.1 steht unter der *Meta Llama 3.1 Community License* mit eigenen Auflagen. Vor einer kommerziellen Nutzung bitte je Modell pruefen. |

---

## 5. Was bei einer kommerziellen Verwertung zu pruefen ist

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
`lokale_windows_app/requirements-local-gui.txt`.
