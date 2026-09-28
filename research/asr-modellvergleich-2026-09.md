# ASR-Modellvergleich: Whisper large-v3-turbo gegen Parakeet und Qwen3-ASR

Gemessen am 28.09.2026. Anlass war die Frage, ob eines der neueren
Erkennungsmodelle `large-v3-turbo` ablösen sollte, das die Anwendung im
lokalen Modus benutzt (`services/model_service.py`, `WHISPER_MODEL_NAME`).

## Ergebnis

**Nein — der bestehende Stand bleibt die richtige Wahl.** Whisper ist auf
deutschem Besprechungsmaterial **3,4-mal genauer** als der beste Herausforderer
und dabei fast so schnell wie das schnellste Modell im Feld. Keines der drei
geprüften Modelle bietet einen Grund für einen Wechsel.

## Messwerte

Ausschnitt von 10 Minuten, 24 Abschnitte, 583,5 s reine Sprache.
Hardware: NVIDIA RTX PRO 500 Blackwell (6 GB), 16 CPU-Kerne, Windows 11.

| Modell | Gerät | WER | CER | E/E/A | Echtzeit­faktor | Laden | Speicher |
|---|---|---|---|---|---|---|---|
| **faster-whisper large-v3-turbo** | GPU | **2,17 %** | 1,02 % | 15/3/9 | 27,5× | 2,2 s | 2,11 GB VRAM |
| faster-whisper large-v3-turbo | CPU | 3,05 % | 1,76 % | 18/8/12 | 3,9× | 3,6 s | 1,56 GB RAM |
| Qwen/Qwen3-ASR-1.7B-hf | GPU | 7,30 % | 4,99 % | 28/49/14 | 3,5× | 7,6 s | 4,93 GB VRAM |
| Qwen/Qwen3-ASR-1.7B-hf | CPU | 7,30 % | 4,99 % | 28/49/14 | 1,3× | 7,2 s | 9,17 GB RAM |
| Qwen/Qwen3-ASR-0.6B | GPU | 9,46 % | 5,61 % | 57/47/14 | 4,0× | 5,4 s | 1,86 GB VRAM |
| Qwen/Qwen3-ASR-0.6B | CPU | 9,54 % | 5,62 % | 58/47/14 | 2,9× | 3,9 s | 4,50 GB RAM |
| nvidia/parakeet-tdt-0.6b-v3 | GPU | 16,04 % | 7,44 % | 123/43/34 | **33,6×** | 4,7 s | **1,52 GB VRAM** |
| nvidia/parakeet-tdt-0.6b-v3 | CPU | 16,04 % | 7,44 % | 123/43/34 | 20,4× | 4,7 s | 3,54 GB RAM |

E/E/A = Ersetzungen / Einfügungen / Auslassungen.
Whisper läuft mit den Einstellungen der Anwendung (float16 auf der GPU, int8
auf der CPU, `word_timestamps=True`, Sprache `de`).

Hochgerechnet auf eine volle Aufnahme von 66 Minuten:

| Modell | GPU | CPU |
|---|---|---|
| parakeet-tdt-0.6b-v3 | 2,0 min | 3,2 min |
| **large-v3-turbo** | **2,4 min** | **16,9 min** |
| Qwen3-ASR-0.6B | 16,4 min | 22,9 min |
| Qwen3-ASR-1.7B-hf | 18,7 min | 51,0 min |

## Warum Parakeet trotz des Tempos ausscheidet

Parakeet ist das schnellste und sparsamste Modell im Feld — und trotzdem
unbrauchbar für unbeaufsichtigte Läufe: **es lässt sich nicht auf eine Sprache
festlegen.** Whisper bekommt `language="de"`, Qwen bekommt `language="German"`,
Parakeet-v3 hat gar keinen solchen Parameter: weder im Prozessor noch in der
`generation_config.json`. Es erkennt die Sprache selbst.

Auf diesem Material kippte es in **2 von 24 Abschnitten** vollständig ins
Englische:

> „Over marktkräfte alien will this not gain. It will not be a static
> interventionism. But what it will gain is what are the incentives …"

Lässt man diese beiden Abschnitte bei allen Modellen weg, fällt Parakeet von
16,04 % auf 9,34 % — **6,7 Prozentpunkte allein durch den Sprachwechsel**.
Selbst dann bleibt es rund sechsmal schlechter als Whisper (1,59 % auf
demselben Rest). Ein Modell, das unvorhersehbar die Sprache wechselt, ist für
Protokolle nicht brauchbar, und es gibt keinen Schalter, der das abstellt.

## Zeitstempel und Sprechertrennung

`speaker_merge_service` schneidet `segment["start"]`/`["end"]` mit den
pyannote-Sprecherabschnitten. Ein Erkennungsmodell muss also Zeiten liefern.

| Modell | Zeitstempel | Kosten |
|---|---|---|
| large-v3-turbo | Wort und Segment, nativ | keine — gemessen 27,5× mit **und** ohne `word_timestamps` |
| parakeet-tdt-0.6b-v3 | Token-Ebene aus den TDT-`durations` | keine, fallen im selben `generate` an |
| Qwen3-ASR (beide) | **nur über ein zweites Modell** (`Qwen3ForcedAligner`) | zusätzliches Laden, zweiter Durchlauf; laut Modellkarte nur bis ~5 min Sprache |

Die Qwen-Modelle wären also ausgerechnet dort am teuersten, wo die Anwendung
sie braucht — zusätzlich dazu, dass sie ohnehin die langsamsten sind.

Nebenbefund: `word_timestamps=True` kostet Whisper praktisch nichts
(27,5× mit, 27,5× ohne; auf der CPU 3,92× gegen 4,02×). Die Einstellung in
`transcription_service.py` ist also nicht der Grund für die CPU-Laufzeit.

## Methode

* **Material**: `boell_thema_gruene_marktwirtschaft.mp3` (66,3 min, 64 kbit/s
  mono), Ausschnitt 10:00–20:00, auf 16 kHz mono normalisiert. Die Datei
  selbst liegt bewusst nicht im Repository (siehe `.gitignore`).
* **Gleiche Abschnitte für alle**: Silero-VAD schneidet den Ausschnitt
  **einmal** in 24 Abschnitte (höchstens 28 s, an Sprechpausen). Jedes Modell
  bekommt exakt dieselben Abschnitte — sonst misst man die Segmentierung mit
  und nicht die Erkennung.
* **Referenz**: Es gibt kein amtliches Transkript. Die Referenz entstand als
  Mehrheitsentscheid der vier Modelle (ROVER) über 94 strittige Bereiche,
  anschließend Korrektur gelesen: 76 Bereiche entschied die Mehrheit, 7
  blieben unentschieden, 11 wurden von Hand korrigiert (jede mit Begründung).
* **Normalisierung**: Groß-/Kleinschreibung und Satzzeichen zählen nicht.
  Zahlen werden auf Zahlwörter gebracht, damit „2 Grad" gegen „zwei Grad"
  nicht als Fehler zählt; dasselbe für Ordnungszahlen („21." gegen
  „einundzwanzigsten"). Ohne diesen Ausgleich liegen alle Werte etwa 0,5 bis
  1,1 Prozentpunkte höher, die Rangfolge ändert sich nicht.
* **Zeitmessung**: Laden und Transkription getrennt; auf der GPU wird der
  zweite, warme Lauf berichtet. Der Grafikspeicher wird über
  `torch.cuda.mem_get_info` gemessen, nicht über den Torch-Allokator — sonst
  meldet CTranslate2 (faster-whisper) 0 GB, weil es daran vorbei allokiert.

## Grenzen dieser Messung

* **Whisper stellt das ROVER-Gerüst** und ist dadurch strukturell bevorteilt:
  außerhalb der strittigen Bereiche ist die Referenz Wort für Wort Whisper.
  Gegenprobe nur auf den 94 strittigen Bereichen, wo das Gerüst keinen Vorteil
  gibt: Whisper 80,9 %, Qwen-1.7B 60,6 %, Qwen-0.6B 50,0 %, Parakeet 42,6 % —
  **dieselbe Rangfolge**. Whisper führt also nicht deshalb, weil es die
  Referenz gestellt hat. Die 2,17 % sind dennoch eher eine Untergrenze als ein
  absoluter Wert; ein echtes Referenztranskript würde alle vier Zahlen anheben.
* **Eine Aufnahme, ein Sprecher, zehn Minuten.** Ein Vortrag in ruhiger
  Umgebung ist nicht dasselbe wie eine Besprechung mit Zwischenrufen und
  Dialekt. Die Rangfolge ist deutlich genug, um belastbar zu sein, die
  absoluten Werte sind es nicht.
* **Qwen-0.6B lief über das Toolkit** (`qwen-asr`), weil das Repository nicht
  im -hf-Format vorliegt. Dessen Mehraufwand je Aufruf steckt in der
  gemessenen Zeit — das Modell selbst könnte über einen anderen Weg schneller
  sein. Auffällig: die 0,6B war langsamer als die größere 1.7B über
  `transformers`.

## Reproduktion

Die Messskripte liegen nicht im Repository, weil sie sonst in Linting,
Typprüfung und Abdeckungsmessung geraten würden (siehe Regel 2 in
`CLAUDE.md`). Der Aufbau ist oben vollständig beschrieben; benötigt werden
`torch` (CUDA 12.8 für Blackwell), `faster-whisper`, `transformers >= 5.13`
für Parakeet und Qwen3-ASR-1.7B-hf sowie `qwen-asr` für Qwen3-ASR-0.6B —
Letzteres in einer **eigenen** Umgebung, weil es `transformers` auf 4.57
herunterzieht und damit die 1.7B unbrauchbar macht.
