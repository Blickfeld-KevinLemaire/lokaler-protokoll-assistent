# VibeVoice-ASR-Streaming gegen Whisper und pyannote

Gemessen am 13.10.2026. Anlass war die Frage, ob Microsofts neues Modell
[`microsoft/VibeVoice-ASR-Streaming-1.5B`](https://huggingface.co/microsoft/VibeVoice-ASR-Streaming-1.5B)
den lokalen Weg der Anwendung ablösen kann. Heute arbeiten dort zwei Modelle
nacheinander: **faster-whisper large-v3-turbo** schreibt mit, **pyannote
community-1** trennt die Sprecher. VibeVoice verspricht beides in einem Modell:
„wer hat was gesagt", fortlaufend, während die Aufnahme läuft.

## Ergebnis

**Nein – der bestehende Weg bleibt die richtige Wahl, auf der Grafikkarte wie auf
dem Prozessor.** VibeVoice macht auf deutschem Material **rund sechs- bis zehnmal
so viele Fehler** wie Whisper und verwechselt Sprecher, braucht dabei mehr
Speicher und ist deutlich langsamer.

| | Bestand (Whisper + pyannote) | VibeVoice-ASR-Streaming-1.5B |
|---|---|---|
| Wortfehlerrate (10 min, GPU) | **1,8 %** | 17,5 % (8 Bit) / 20,0 % (4 Bit) |
| Wortfehlerrate unquantisiert (5 min) | **3,0 %** | 18,0 % |
| Sprecher erkannt (2 Fenster à 3 Personen) | **3 von 3**, beide Fenster | 2 von 3, beide Fenster |
| 66 min Aufnahme, Grafikkarte | **~9 min** (gemessen) | ~19 min (4 Bit), ~61 min (8 Bit) |
| 66 min Aufnahme, nur Prozessor | **~42 min** | ~63 min (int8), ~108 min (fp32) |
| Spitzenspeicher | 2,2 GB VRAM (Whisper), 4,6 GB (pyannote), nie gleichzeitig | 4,4 GB VRAM (4 Bit) bzw. 12,3 GB RAM (fp32) |
| Zeitstempel | Wort und Segment | **keine** |
| Aufnahmelänge | beliebig | trainiert für **höchstens ~8 min** |

Der Abstand ist kein Fehler im Aufbau. Microsofts eigene Zahlen und eine
unabhängige Rangliste zeigen dasselbe (siehe „Warum das neuere Modell schlechter
ist").

## Das Modell

| | |
|---|---|
| Veröffentlicht | 02.09.2026, MIT-Lizenz, Gewichte offen |
| Aufbau | zwei Audio-Encoder (akustisch, semantisch) aus dem VibeVoice-TTS-Baukasten + Sprachmodell Qwen2.5 1,5B |
| Parameter | **2,81 Mrd.** (Whisper large-v3-turbo: 0,81 Mrd.) |
| davon ungenutzt | 0,34 Mrd. für einen akustischen **Decoder**, der nur für die Sprachsynthese gebraucht wird, aber mitgeladen wird |
| Sprachen | 10, darunter Deutsch |
| Ausgabe | Fließtext mit „Speaker 0:", „Speaker 1:" …, **ohne Zeitstempel** |
| Arbeitsweise | Stücke von 2,9 s plus 0,5 s Vorausschau; die Nummerierung der Sprecher beginnt in jeder Aufnahme neu |
| Länge | laut Technischem Bericht für Aufnahmen bis ~8 min ausgelegt |

Die Bezeichnung „1.5B" meint nur das Sprachmodell. Mit den Audio-Encodern sind es
fast 3 Mrd. Parameter, rund 5,6 GB in bf16. Das passt nicht vollständig auf die
6-GB-Karte des Testrechners; auf der Grafikkarte lief das Modell deshalb mit
8 bzw. 4 Bit (bitsandbytes, nur das Sprachmodell quantisiert, Audio-Encoder in
bf16).

## Messwerte

### Erkennungsgenauigkeit

Ausschnitt 10:00–20:00 der Böll-Aufnahme, ein Sprecher, 1.255 Wörter Referenz,
**dieselbe Referenz wie im ASR-Vergleich vom September**
(`asr-modellvergleich-2026-09.md`).

| Modell | Gerät | WER | CER | E/E/A | Echtzeitfaktor | Speicher |
|---|---|---|---|---|---|---|
| **faster-whisper large-v3-turbo** | GPU | **1,83 %** | 0,80 % | 14/3/6 | 27,5× | 2,1 GB VRAM |
| faster-whisper large-v3-turbo | CPU (int8) | 2,55 % | 1,35 % | 17/5/10 | 3,9× | 1,6 GB RAM |
| Qwen3-ASR-1.7B (Sept.) | GPU | 6,53 % | 4,11 % | 28/40/14 | 3,5× | 4,9 GB VRAM |
| Qwen3-ASR-0.6B (Sept.) | GPU | 8,61 % | 4,66 % | 54/39/15 | 4,0× | 1,9 GB VRAM |
| Parakeet-tdt-0.6b-v3 (Sept.) | GPU | 15,46 % | 6,95 % | 119/39/36 | 33,6× | 1,5 GB VRAM |
| VibeVoice-Streaming-1.5B, 8 Bit | GPU | 17,45 % | 9,82 % | 112/67/40 | 1,1× | 4,9 GB VRAM |
| VibeVoice-Streaming-1.5B, 4 Bit | GPU | 20,00 % | 11,09 % | 134/64/53 | 3,8× | 4,4 GB VRAM |

E/E/A = Ersetzungen / Einfügungen / Auslassungen. VibeVoice bekam die zehn
Minuten als zwei Hälften à 5 min (innerhalb der 8-min-Grenze). Ein Lauf über die
ganzen 10 min am Stück ergab ebenfalls 20,0 %; die Grenze kippt also nicht schon
bei 10 min.

**Unquantisiert und auf dem Prozessor** – nur die erste Hälfte (629 Wörter), weil
ein fp32-Lauf für die ganzen 10 min unverhältnismäßig lange dauert:

| Modell | Gerät | WER | davon echte Fehler¹ | Echtzeitfaktor | Speicher |
|---|---|---|---|---|---|
| **Whisper turbo** | GPU | **3,0 %** | 2,9 % | 27,5× | 2,1 GB VRAM |
| Whisper turbo | CPU (int8) | 4,1 % | 3,8 % | 3,9× | 1,6 GB RAM |
| VibeVoice **fp32 (unquantisiert)** | CPU | 18,0 % | 15,7 % | 0,61× | 12,3 GB RAM |
| VibeVoice 8 Bit | GPU | 18,9 % | 16,9 % | 1,1× | 4,9 GB VRAM |
| VibeVoice 4 Bit | GPU | 20,5 % | 18,4 % | 3,5× | 4,4 GB VRAM |
| VibeVoice int8 (dynamisch) | CPU | 21,5 % | 19,6 % | 1,05× | 18,7 GB RAM² |

¹ Ohne Abweichungen, die nur aus der wortgetreuen Schreibweise stammen (siehe
unten).
² Spitze beim Quantisieren, solange die fp32-Gewichte noch im Speicher liegen.

Die Quantisierung kostet VibeVoice also 1–3,5 Prozentpunkte – der Abstand zu
Whisper beträgt aber 15. **Auch unquantisiert macht VibeVoice rund sechsmal so
viele Fehler.**

### Was die Fehler sind

Von Hand gegen die Referenz gelesen. Der Text von VibeVoice ist lesbar und im
Groben richtig – aber an den Stellen falsch, auf die es im Protokoll ankommt:

| Gesagt (Referenz) | VibeVoice |
|---|---|
| „an **Dramatik** zugenommen" | „**ein Artikel** zugenommen" |
| „Zielgröße zu **nennen, dass wir** 2050 …" | „Zielgröße zu **setzen**, 2050 …" |
| „CO2 **weltweit** einsparen" | „CO zwei, **die wir halt** einsparen" |
| „Ziele der **Europäischen** Union" | „Ziele der Union" |
| „8 % bis **2012**" | „bis **eintausendzwölf**" |
| „Burden-Sharing **40 %**" | „**einzig** Prozent" |
| „**Ich will** das mal … klar **machen**" | „**Wenn** das mal … klar **macht**" |

Zwei falsche Zahlen in fünf Minuten sind für ein Protokoll schwerer als die reine
Fehlerquote vermuten lässt.

VibeVoice schreibt außerdem **wortgetreu**: „äh", „ähm", Wiederholungen („äh ist
äh ist", „an der der"). Whisper glättet das. Weil die Referenz auf Whisper
aufbaut, zählen solche Stellen gegen VibeVoice, obwohl sie gesprochen worden sein
können. Deshalb wurden sie getrennt gezählt (Füllwörter, unmittelbare
Wiederholungen, Partikeln wie „halt", „also", „so"): **nur 23 von rund 250
Abweichungen** gehen darauf zurück. Der Rest sind echte Erkennungsfehler.

### Sprechertrennung

Zwei Fenster à 8 min mit Sprecherwechseln, je drei Personen (Moderator und zwei
Diskutanten). Weil VibeVoice keine Zeitstempel liefert, wurden die Wörter beider
Transkripte über den Text einander zugeordnet und die Sprecher Wort für Wort
verglichen.

| Fenster | pyannote | VibeVoice | Übereinstimmung |
|---|---|---|---|
| 26–34 min | 3 Sprecher | **2 Sprecher** | 86,6 % |
| 45–53 min | 3 Sprecher | **2 Sprecher** | 81,2 % |

Am Inhalt nachgeprüft (Übergaben des Moderators, „Ja, danke Ralf"): **pyannote
liegt in beiden Fenstern richtig.** VibeVoice erkennt die Sprecherwechsel an den
richtigen Stellen, legt aber jeweils zwei Personen zusammen:

* 26–34 min: Frage des Moderators und Antwort von Bütikofer unter **einem** Label.
* 45–53 min: Bütikofers Eingangsbeitrag (192 Wörter) unter demselben Label wie
  Machnig; Bütikofers Zwischenruf („das war nicht mein Eindruck …") beim
  Moderator.

Die Übereinstimmung von 81–87 % klingt besser, als es ist: Sie entsteht, weil
die längsten Beiträge richtig zugeordnet sind.

Dazu kommt ein grundsätzliches Hindernis: VibeVoice nummeriert die Sprecher in
jeder Aufnahme neu und ist für höchstens ~8 min ausgelegt. Eine Besprechung von
einer Stunde müsste in Stücke geteilt werden, und die Sprecher müssten **über die
Stücke hinweg** zugeordnet werden – genau das, was pyannote heute erledigt. Ohne
Zeitstempel ließe sich VibeVoice auch nicht mit pyannote kombinieren
(`speaker_merge_service` braucht Wortzeiten).

### Geschwindigkeit und Speicher

Gemessen auf denselben 8-min-Fenstern, jede Stufe in einem eigenen Prozess (für
pyannote auf der GPU Pflicht, siehe Regel 1 in `CLAUDE.md`).

| | Gerät | Echtzeitfaktor | Laden | Spitzenspeicher |
|---|---|---|---|---|
| Whisper turbo | GPU | 22,7–25,4× | 3–4 s | 2,2 GB VRAM |
| pyannote community-1 | GPU | 11,6–13,3× | 6–15 s | 4,6 GB VRAM |
| Whisper turbo | CPU | 3,0× | 4 s | 2,0 GB RAM |
| pyannote community-1 | CPU | 3,4× | 12 s | 2,7 GB RAM |
| VibeVoice 4 Bit | GPU | 3,1–4,1× | 6–7 s | 4,4–4,5 GB VRAM, 3,1 GB RAM |
| VibeVoice 8 Bit | GPU | 1,1× | 7–8 s | 4,9 GB VRAM, 3,2 GB RAM |
| VibeVoice fp32 | CPU | 0,61× | 2 s | 12,3 GB RAM |
| VibeVoice int8 | CPU | 1,05× | 8 s | 18,7 GB RAM (Spitze) |

Hochgerechnet auf die volle Aufnahme von 66 min:

| | Grafikkarte | nur Prozessor |
|---|---|---|
| **Bestand** (Whisper + pyannote) | **~9 min** (am selben Tag gemessen: 9:00 min im Servermodus) | **~42 min** (22 + 20 min) |
| VibeVoice | ~19 min (4 Bit) / ~61 min (8 Bit) | ~63 min (int8) / ~108 min (fp32) |

Die 8-Bit-Variante ist so langsam, weil `bitsandbytes` (LLM.int8) beim
Token-für-Token-Erzeugen viel Verwaltungsaufwand hat; 4 Bit (NF4) ist dreimal
schneller.

## Warum das neuere Modell schlechter ist

Das war die naheliegende Rückfrage: Ein Modell von 2026 sollte eins von 2024
schlagen. Geprüft und ausgeschlossen wurden zuerst Fehler im Aufbau:

* **Eingabe:** identisch mit dem offiziellen Demo-Skript (24 kHz, 16-Bit-PCM ÷
  32768, keine Normalisierung – so steht es auch in `preprocessor_config.json`).
* **Quantisierung:** kostet nur 1–3,5 Punkte (siehe oben); fp32 ist kaum besser.
* **Schreibweise:** Füllwörter und Wiederholungen erklären nur 23 von ~250
  Abweichungen.

Die Gründe liegen im Modell selbst:

1. **Es ist für etwas anderes gebaut.** VibeVoice-Streaming soll *live*
   mitschreiben und dabei Sprecher erkennen. Dafür entscheidet es mit nur 0,5 s
   Vorausschau; Whisper sieht 30-Sekunden-Fenster in beide Richtungen. Microsoft
   misst selbst, dass die Streaming-Variante 0,75–3,5 Punkte WER schlechter ist
   als das hauseigene Offline-Modell. Für ein Protokoll **nach** der Besprechung
   bringt Streaming nichts.
2. **Starke Kompression des Tons.** Die Audio-Encoder stammen aus der
   Sprachsynthese und verdichten auf 7,5 Merkmale pro Sekunde. Whispers Encoder
   arbeitet mit 50 pro Sekunde.
3. **Wenig Deutsch im Training.** Der Großteil der Trainingsdaten (~420.000 h)
   ist Englisch und Chinesisch. Whisper wurde auf Millionen Stunden in rund 100
   Sprachen trainiert.
4. **Microsofts eigene Zahlen bestätigen es.** Der Technische Bericht nennt für
   das 1.5B-Modell auf Besprechungsdaten **im Mittel 29 % WER**; selbst das 7B-Modell
   kommt auf deutschen Besprechungen nur auf **21,8 %** und liegt damit knapp
   hinter Azure. Einen Vergleich mit Whisper enthält der Bericht nicht.
5. **Unabhängig bestätigt.** Auf der deutschen Rangliste des Open ASR Leaderboard
   (Hugging Face) liegt sogar das **große Offline-Modell** VibeVoice-ASR (~8 Mrd.
   Parameter) deutlich hinter Whisper turbo:

| Modell (Open ASR Leaderboard, Deutsch) | FLEURS | Common Voice |
|---|---|---|
| openai/whisper-large-v3 | 3,20 % | 4,79 % |
| Qwen/Qwen3-ASR-1.7B | 3,35 % | 4,60 % |
| **openai/whisper-large-v3-turbo** (Bestand) | **3,67 %** | **8,58 %** |
| nvidia/parakeet-tdt-0.6b-v3 | 4,16 % | 4,07 % |
| microsoft/VibeVoice-ASR (offline, ~8B) | 7,44 % | 20,97 % |

Das Streaming-Modell 1.5B ist dort nicht gelistet. Auffällig: Auf diesen
Datensätzen (vorgelesene Sätze) schlagen Qwen3-ASR und Parakeet Whisper turbo –
auf unserem echten Vortragsmaterial war es im September umgekehrt, und zwar
deutlich. Ranglisten auf vorgelesenen Sätzen übertragen sich nur bedingt auf
Besprechungen.

## Methode

* **Material**: `boell_thema_gruene_marktwirtschaft.mp3` (66,3 min, 3 Sprecher,
  Podiumsdiskussion). Für die Genauigkeit 10:00–20:00 (wie im September), für
  die Sprechertrennung 26:00–34:00 und 45:00–53:00 – die beiden Fenster mit echten
  Sprecherwechseln. VibeVoice bekam 24 kHz (sein natives Format), der Bestand
  16 kHz; beide aus derselben MP3 mit FFmpeg geschnitten. Die Aufnahme liegt nicht
  im Repository.
* **Referenz**: die korrekturgelesene Referenz vom September (Mehrheitsentscheid
  über vier Modelle, 11 Stellen von Hand korrigiert).
* **Normalisierung**: wie im September (Groß-/Kleinschreibung und Satzzeichen
  egal, Zahlen → Zahlwörter), **zusätzlich** drei Angleichungen, die sonst
  VibeVoice unfair belasten: „%" → „Prozent" („30%" gegen „dreißig Prozent"),
  „CO zwei" → „CO2", „neunzehnhundert…" → „eintausendneunhundert…". Sprecherlabels
  und Füllwörter („äh", „ähm") werden vor dem Vergleich entfernt. Das senkt
  **alle** Werte leicht, auch Whispers (2,17 % → 1,83 %); die Rangfolge der
  September-Modelle bleibt gleich.
* **VibeVoice**: offizieller Code (`microsoft/VibeVoice`, Stand 08.10.2026),
  `streaming_generate` wie im Demo-Skript, greedy (Temperatur 0), Stückgröße und
  Vorausschau aus der `preprocessor_config.json` des Checkpoints. Eigene
  Umgebung: torch 2.11 (CUDA 12.8), transformers 4.57.6, bitsandbytes 0.50.2.
* **Bestand**: über die Dienste der Anwendung selbst (`transcription_service`,
  `diarization_service`, `speaker_merge_service.assign_speakers_by_words`), mit
  der ML-Laufzeitumgebung der Anwendung; jede Stufe in einem eigenen Prozess.
* **Hardware**: Laptop, Intel Core Ultra 7 255H (16 Kerne), 63,5 GB RAM, NVIDIA RTX
  PRO 500 Blackwell (6 GB), Windows 11. CPU-Läufe auf allen 16 Kernen, nacheinander.
* **Speicher**: VRAM über `torch.cuda.mem_get_info` (Gerät, nicht Allokator),
  RAM als Arbeitssatz des Prozesses, jeweils als Spitze alle 0,2 s.

## Grenzen dieser Messung

* **Eine Aufnahme.** Ein Vortrag mit Podium ist nicht dasselbe wie eine
  Besprechung mit Zwischenrufen und Dialekt. Der Abstand (Faktor 6–10) ist groß
  genug, um belastbar zu sein; die absoluten Werte sind es nicht.
* **Whispers 1,8 % ist eine Untergrenze.** Die Referenz baut auf Whisper auf
  (siehe September-Bericht). Gegen ein unabhängiges Transkript lägen alle Werte
  höher, Whispers am meisten. Die öffentliche Zahl für Deutsch (3,7 % auf
  FLEURS) ist die vorsichtigere.
* **Sprechertrennung ohne amtliche Referenz.** Verglichen wurde gegen pyannote,
  die Abweichungen wurden am Inhalt entschieden. Zwei Fenster mit je drei Personen
  – eine Sprechertrennungs-Fehlerrate (DER) lässt sich daraus nicht angeben.
* **Nur das 1.5B-Streaming-Modell.** Die 7B-Varianten passen nicht auf die
  6-GB-Karte. Nach Microsofts eigenen Zahlen wären sie besser; einen direkten
  Vergleich mit Whisper auf Deutsch gibt es für sie nicht. Das große
  *Offline*-Modell liegt auf der deutschen Rangliste klar hinter Whisper turbo.

## Für Produktinformationen verwertbar

Der Bericht kann als Beleg für ein Datenblatt oder Werbematerial dienen. Was sich
daraus vertreten lässt – und wo Vorsicht geboten ist:

**Belegbar:**

* „Die Erkennung wird regelmäßig gegen neue Modelle geprüft." Seit September 2026
  vier Alternativen gemessen (Parakeet, Qwen3-ASR 0.6B und 1.7B,
  VibeVoice-Streaming), keine war auf deutschem Material besser.
* „Vollständig lokal, ohne Cloud." Erkennung und Sprechertrennung laufen auf dem
  eigenen Rechner – auf einem Laptop mit 6-GB-Grafikkarte eine Stunde Aufnahme in
  rund 9 Minuten, ohne Grafikkarte in rund 40 Minuten.
* „Erkennt, wer spricht." Im Test drei von drei Personen richtig getrennt.
* Genauigkeit: Für das eingesetzte Erkennungsmodell gibt es eine öffentliche,
  unabhängige Zahl – **3,7 % Wortfehler auf Deutsch** (FLEURS, Open ASR
  Leaderboard). Auf unserer Aufnahme lag sie in eigener Messung darunter.

**Mit Vorsicht:**

* Die eigenen Zahlen (1,8 %) stammen aus **einer** Aufnahme mit einer
  Whisper-nahen Referenz. Als Werbeaussage besser die öffentliche Zahl oder „unter
  5 % Wortfehler" verwenden.
* Die Erkennung leistet **OpenAI Whisper**, die Sprechertrennung **pyannote** –
  beides fremde Open-Source-Modelle (siehe `NOTICES.md`). Die Genauigkeit nicht als
  eigene Entwicklung darstellen; unsere Leistung ist die Auswahl, die Prüfung und
  die Verarbeitungskette darum.
* **Vergleichende Werbung** („genauer als Microsoft …") ist in Deutschland nur in
  engen Grenzen zulässig (§ 6 UWG: objektiv, nachprüfbar, vergleichbare
  Produkte). VibeVoice ist ein Forschungsmodell, kein konkurrierendes Produkt.
  Solche Aussagen nur nach rechtlicher Prüfung.

## Reproduktion

Die Messskripte liegen nicht im Repository (aus demselben Grund wie im
September: Linting, Typprüfung, Abdeckung). Der Aufbau ist oben vollständig
beschrieben. Benötigt werden eine **eigene** Umgebung für VibeVoice (`pip install
-e` des GitHub-Repositorys zieht `transformers < 5`, Gradio und weitere Pakete) und
`bitsandbytes` für die GPU-Varianten. Der Bestand läuft mit der
ML-Laufzeitumgebung der Anwendung.

## Quellen

* Modellkarte: <https://huggingface.co/microsoft/VibeVoice-ASR-Streaming-1.5B>
* Technischer Bericht: <https://arxiv.org/abs/2609.02812>
* Code: <https://github.com/microsoft/VibeVoice>
* Open ASR Leaderboard: <https://huggingface.co/spaces/hf-audio/open_asr_leaderboard>
  (Daten Deutsch: `hf-audio/multilingual_evals`, `multilingual_de.csv`)
* Whisper large-v3-turbo: <https://huggingface.co/openai/whisper-large-v3-turbo>
