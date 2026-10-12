# Phase 0: Wo geht die Zeit der Verarbeitung hin?

Gemessen am 12.10.2026 mit der vorhandenen Verarbeitung (Servermodus, `--einmal`, Code von `main`) an zwei echten Aufnahmen.
Ziel: Zahlen statt Vermutungen für die Frage, wie kurz die Wartezeit nach dem Ende einer Aufnahme werden kann.

## Messaufbau

| | |
|---|---|
| Rechner | AMD Ryzen 5 5600X (6 Kerne / 12 Threads), NVIDIA RTX 3060 Ti mit 8 GB Grafikspeicher |
| Transkription | faster-whisper `large-v3-turbo`, GPU, float16, Sprache Deutsch (mit Pausenfilter) |
| Sprechertrennung | pyannote (community-1), GPU, eigener Prozess |
| Sprachmodell | Ollama `qwen3:8b` (das einzige auf diesem Rechner installierte Modell; der Server-Standard wäre `qwen3.5:4b-q4_K_M`) |
| Ablauf | Eingang → Audio vorbereiten → Chunks transkribieren → Sprecher trennen → Protokoll (3 Stufen) → Dateien |
| Isolierung | eigener Daten-, Eingangs- und Ausgangsordner; weder Einstellungen noch Ausgaben der Anwendung wurden berührt |

Die Aufnahmen stammen von den Aufnahmegeräten (Opus bzw. WAV, Mono/16 kHz bzw. Stereo, mehrere Sprecher, teils lange Pausen).

## Ergebnis

| Schritt | 7:44 min (1375 Wörter) | 73,0 min (5974 Wörter, 5 Sprecher) |
|---|---|---|
| Modell laden | 25,9 s | 9,6 s |
| **Transkription** | 14,7 s (31-fache Echtzeit) | 78,7 s (56-fache Echtzeit) |
| **Sprechertrennung** | 24,5 s | 142,9 s |
| Ausgabedateien (Transkript, Word) | 1,8 s | ca. 2 s |
| **Protokoll durch das Sprachmodell** | **112 s** | **ca. 1245 s (20,8 min)** |
| davon Stufe 1: Analyse je Chunk | 62 s | 588 s (8 Chunks, im Mittel 73 s je 10-Minuten-Block) |
| davon Stufe 2: Zwischenzusammenführung | – | 379 s |
| davon Stufe 3: Gesamtprotokoll | 51 s | 283 s |
| **Gesamt** | **ca. 180 s** | **ca. 1485 s (24,8 min)** |
| Anteil des Sprachmodells | 62 % | **84 %** |

Grafikspeicher: Während der Transkription und der Sprechertrennung belegt jeweils ca. 3 GB, während des Sprachmodells **7,0 bis 7,1 GB**
(Spitze 7,14 GB; im Leerlauf belegt Windows ca. 0,7 GB). Ollama meldet für `qwen3:8b` mit 16k Kontext 7,8 GB, davon 80 % auf der GPU und 20 % auf dem Prozessor.

Whisper auf dem **Prozessor** (int8, Greedy, 60 s echte Sprache): `large-v3-turbo` 3,2-fache Echtzeit, `small` 11-fach, `base` 34-fach.

## Was daraus folgt

1. **Das Sprachmodell ist der Engpass, nicht die Transkription.** Bei einer Stunde Meeting dauert die Auswertung ein Vielfaches der Transkription (21 min gegenüber 1,3 min).
   Wer die Wartezeit kürzen will, muss dort ansetzen. Laufende Transkription allein spart nur ca. 1–2 Minuten.
2. **Whisper und das 8B-Sprachmodell passen nicht gleichzeitig auf die Karte** (ca. 3 + 7 GB gegenüber 8 GB). Die frühere Annahme im Konzept („beide warm halten“) gilt nur mit einem 4B-Modell
   (ca. 3 GB). Mit dem 8B-Modell gibt es zwei Auswege: Whisper läuft **auf dem Prozessor** (3,2-fache Echtzeit reicht für 15-s-Stücke, die Grafikkarte gehört dem Sprachmodell),
   oder die Modelle werden nacheinander geladen.
3. **Die Analyse der 10-Minuten-Blöcke lässt sich in das Meeting vorziehen.** Ein Block braucht im Mittel 73 s, ein Block Meeting dauert 600 s. Es fehlt nur der Platz im Grafikspeicher (Punkt 2).
   Stufe 2 und 3 (zusammen 662 s bei 73 min) sind das, was nach dem Ende übrig bleibt, und mit einem auf den Auftrag zugeschnittenen, knappen Ergebnis (z. B. ToDo-Liste) sollten sie deutlich kürzer werden. Das ist noch nicht gemessen.
4. **Sprechertrennung braucht 143 s bei 73 min** (3,3 % der Dauer) und läuft heute erst am Ende. Danach wird sie der größte feste Block nach dem Ende. Sie braucht ca. 3 GB, also nicht gleichzeitig mit dem 8B-Modell.
5. **Fehler gefunden: Zwei Aufnahmen kurz nacheinander können abstürzen.** Ollama hält das Sprachmodell nach der letzten Anfrage noch ca. 5 Minuten im Grafikspeicher. Startet in dieser Zeit die nächste Transkription, meldet Whisper
   „CUDA out of memory“ und die Aufnahme landet im Fehlerordner. Reproduziert (zweiter Lauf direkt nach dem ersten). Abhilfe: das Sprachmodell nach dem letzten Aufruf entladen (`keep_alive: 0`) oder vor der Transkription entladen.

## Abschätzung für eine Stunde Meeting (noch nicht gemessen)

| Variante | Wartezeit nach dem Ende |
|---|---|
| heute (alles erst nach dem Ende) | ca. 25 min (gemessen bei 73 min) |
| Transkription laufend, Rest wie heute | ca. 23 min |
| zusätzlich Block-Analysen während des Meetings (Whisper auf dem Prozessor), knappes Auftragsergebnis | grob 4–5 min: letzter Block (bis 75 s) + Sprechertrennung (143 s) + Zusammenführung (grob 30–60 s) |
| zusätzlich Sprecher laufend | grob 2 min |

Die Zahlen für die unteren Zeilen sind Schätzungen aus den Einzelmessungen. Sie müssen in Phase 2/3 mit einem echten Lauf überprüft werden.
Wichtig für die Übertragbarkeit: Die gemessene Aufnahme hat nur ca. 82 Wörter pro Minute (viele Pausen). Ein dichtes Meeting hat eher 120–150; dann wird die Auswertung entsprechend länger.

## Offene Messungen

* Gleiche Messung mit einem **4B-Modell** (der Server-Standard `qwen3.5:4b-q4_K_M`): Geschwindigkeit, Qualität des Protokolls, passt es neben Whisper auf die Karte? Dafür müsste das Modell geladen werden (ca. 2,6 GB Download).
* Auftragsbezogene Auswertung (ToDos, wer/was/bis wann) statt vollem Protokoll: Dauer und Qualität.
* Sprechertrennung auf dem Prozessor und rollend, falls die Grafikkarte nicht frei ist.
