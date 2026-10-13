# Kleine Sprachmodelle auf dem Prozessor (Oktober 2026)

Gemessen am 13.10.2026. Anlass war die Frage, ob die automatische Auswertung
(das Protokoll aus dem Transkript) auch auf einem gewöhnlichen Bürolaptop **ohne
Grafikkarte** läuft – und ob dafür ein sehr kleines, stark quantisiertes Modell
(1,58-Bit-/„ternäres" Modell) der richtige Weg ist.

## Ergebnis in einem Satz

**Ein 1,58-Bit-Modell ist auf dem Prozessor nicht schneller, sondern langsamer.**
Das 1,58-Bit-Modell mit 4 Mrd. Parametern brauchte für eine Stunde Aufnahme
**85 Minuten**, das gleich große Qwen in gewöhnlicher 4-Bit-Quantisierung nur
**24 Minuten** – auf denselben 8 Kernen. Für „läuft auf jedem Bürolaptop" ist ein
gut quantisiertes **kleineres** Modell (LFM2.5-2.6B, 4 Bit) die bessere Antwort:
**16 Minuten**, brauchbare Zusammenfassung, ~4,6 GB Arbeitsspeicher. Trotzdem
bleibt der Arbeitsspeicher das eigentliche Nadelöhr: Auf einem 8-GB-Gerät ist es
eng (siehe unten).

## Aufbau

| | |
|---|---|
| Rechner | Laptop, Intel Core Ultra 7 255H (16 Kerne), 63,5 GB RAM, NVIDIA RTX PRO 500 (6 GB) |
| „Bürolaptop" nachgestellt | Prozessoraffinität auf **8 Kerne** (4 P- + 4 E-Kerne, Maske `0x0C3F`), **keine Grafikkarte** |
| Material | Podiumsdiskussion der Böll-Stiftung „Grüne Marktwirtschaft", **66 min**, 8.206 Wörter, 3 Sprecher |
| Transkription | einmal auf der Grafikkarte erzeugt (Whisper large-v3-turbo), dann für alle Läufe identisch wiederverwendet |
| Auswertung | die **echte** Kette der Anwendung (`pipeline_service.run_protocol`, Stufe 1–3), nur die Modellanfrage ausgetauscht – genau wie im API-Modus |
| Anfragen je Lauf | 10 (7 Abschnitte à 10 min, 2 Zwischenzusammenfassungen, 1 Gesamtprotokoll) |

Die 1,58-Bit-Modelle liefen über den `llama-server` des PrismML-Forks von
llama.cpp (nur dieser kann das PQ2_0-Format), LFM2.5 über den offiziellen
llama.cpp-Build, Qwen über Ollama. Alle rein auf dem Prozessor (`-ngl 0`,
`num_gpu 0`), 8 Threads.

## Zeit und Geschwindigkeit

| Modell | Format | Gerät | Dauer (66 min Audio) | Ausgabe Tok/s | Arbeitsspeicher |
|---|---|---|---|---|---|
| Qwen 3.5 **4B** | Q4_K_M | **Grafikkarte** | **4,5 min** | 43 | 4,2 GB VRAM |
| LFM2.5 **2,6B** | Q4 (QAD) | 8 Kerne CPU | **16 min** | 19 | **4,6 GB RAM** |
| Qwen 3.5 **4B** | Q4_K_M | 8 Kerne CPU | 24 min | 12 | ~5 GB RAM¹ |
| Ternary Bonsai **4B** | 1,58-Bit (PQ2_0) | 8 Kerne CPU | **85 min** | 5,6 | 7,5 GB RAM |
| Ternary Bonsai **1,7B** | 1,58-Bit (PQ2_0) | 8 Kerne CPU | abgebrochen² | 12 | 6,3 GB RAM |

¹ Qwen lief über Ollama; dessen Modellprozess ließ sich nicht sauber einzeln
messen. Gemessen: Gewichte 3,4 GB, beim Laden mit 16K-Kontext ~3,7 GB physisch,
unter Volllast vergleichbar den anderen Modellen (~5 GB). VRAM-Spitze auf der
Grafikkarte dagegen sauber gemessen (4,2 GB).

² Nach 5 von 10 Anfragen abgebrochen (Qualität, siehe unten). Hochgerechnet
~50 min.

**Warum das 1,58-Bit-Modell langsamer ist**, obwohl es weniger Bit je Gewicht
hat: Zwei Gründe, die zusammenwirken.

1. **Die Rechenkerne sind weniger ausgereift.** Der PrismML-Fork rechnet PQ2_0
   auf x86 deutlich langsamer als llama.cpp seine Q4_K_M-Kerne. Reine
   Prompt-Verarbeitung: 40 Tok/s (Bonsai) gegen 92 Tok/s (Qwen) gegen 126 Tok/s
   (LFM).
2. **Das Modell schreibt viel mehr.** Bonsai 4B erzeugte je Abschnitt bis zu
   4.594 Tokens Antwort, Qwen höchstens 845. Über den ganzen Lauf: ~19.500 gegen
   ~11.900 Ausgabe-Tokens. Langsamer je Token **und** mehr Tokens – beides
   addiert sich.

## Qualität

| Modell | Zusammenfassung? | Deutsch | Fakten | Urteil |
|---|---|---|---|---|
| Qwen 3.5 4B (GPU/CPU) | ja, ausführlich | sehr gut | stimmig (EEG 2,8 Mrd. €/21 Mrd. €, 40 % CO₂ bis 2020, Stern-Report) | **sehr gut** |
| LFM2.5-2.6B | ja, knapp | sehr gut, flüssig | im Kern richtig; „Büttekofer" (ASR-Fehler), „40 % Burden-Shareing" verstümmelt | **gut** (beste Wahl für den Prozessor) |
| Ternary Bonsai 4B | ja | gut | überwiegend richtig; **erfindet** „SPD-Bündesführer" | brauchbar, aber langsam und etwas wortreich |
| Ternary Bonsai 1,7B | **nein** | – | – | **unbrauchbar**: gibt das Transkript Zeile für Zeile wieder, inklusive Wiederholungen („Wir wissen heute, wir wissen heute") |

Das 1,7B-Modell „versteht" den Auftrag „fasse zusammen" nicht – es kopiert den
Text. Das ist auch der Grund für die vielen Ausgabe-Tokens und die lange
Laufzeit. Deshalb abgebrochen.

## Arbeitsspeicher: das eigentliche Nadelöhr auf 8 GB

Nicht die Geschwindigkeit entscheidet auf einem Bürolaptop, sondern der
Arbeitsspeicher. Gemessene Spitzen unter Volllast (CPU, 16K-Kontext):

| Modell | Spitze RAM |
|---|---|
| LFM2.5-2.6B Q4 | 4,6 GB |
| Qwen 3.5 4B Q4 | ~5 GB |
| Ternary Bonsai 4B | 7,5 GB |

Dagegen ein typischer 8-GB-Bürolaptop im Alltag:

| Zustand | belegt |
|---|---|
| Windows 11, frisch gestartet | ~2,5–3,5 GB |
| + Teams/Outlook | ~4–4,5 GB |
| + Browser mit einigen Tabs | **~5–6 GB** |

**Das heißt: Auf 8 GB bleibt im Alltag nur ~2–3 GB frei – zu wenig für die
lokale Auswertung mit einem 4B-Modell.** Windows würde auf die Auslagerungsdatei
ausweichen; eine ohnehin 16–24-minütige Auswertung würde dadurch unbrauchbar
langsam. Faustregel aus den Messungen:

* **8 GB RAM → lokale Auswertung nicht realistisch.** Entweder der API-Weg oder
  ein deutlich kleineres Modell samt kleinerem Kontext (siehe unten).
* **16 GB RAM → der 4B-Weg auf dem Prozessor passt** (6 GB Modell + 6 GB System
  lassen ~4 GB Luft).

### Kontext kleiner wählen spart Arbeitsspeicher

Der Arbeitsspeicher hängt am Kontextfenster (dem KV-Speicher). Gemessen für
einen **10-Minuten-Abschnitt** (Stufe 1):

| | Qwen | Bonsai |
|---|---|---|
| Eingabe des dichtesten Abschnitts (Systemprompt + Transkript) | 4.812 Tokens | 5.427 Tokens |
| davon Text | 13.381 Zeichen (~1.650 Wörter/10 min) | dieselben |
| Antwort tatsächlich | bis 845 Tokens | bis 4.594 Tokens |

Dieser dichteste Abschnitt liegt nahe an der natürlichen Obergrenze für 10 min
deutsche Rede. **Worst Case also ~6.000 Eingabe-Tokens** je Abschnitt (Reserve
für andere Tokenizer und sehr schnelle Sprecher). Die Anwendung fordert aber
**16K** Kontext an – fast nur wegen der festen Antwort-Reserve von 10.240 Tokens
(`ollama_service.kontext_fuer_protokoll`), die für die Abschnitte viel zu groß
ist.

**Für knappen Arbeitsspeicher: 8K Kontext für Stufe 1 und 2 genügt** (~6K
Eingabe + knappe Antwort) und halbiert den KV-Speicher (~1 GB weniger). Nur das
**Gesamtprotokoll** (Stufe 3, es verdichtet die ganze Stunde) braucht das große
Fenster. Das ist eine mögliche, noch nicht umgesetzte Einstellung.

## Empfehlung

1. **Grafikkarte vorhanden → Qwen 3.5 4B auf der Grafikkarte** (4,5 min). Dabei
   bleibt es für die Anwendung.
2. **Nur Prozessor, ≥16 GB RAM → LFM2.5-2.6B (4 Bit)** als lokales Modell: 16 min,
   brauchbare Zusammenfassung, ~4,6 GB. Qwen 4B auf dem Prozessor geht auch, ist
   aber langsamer.
3. **Nur Prozessor, 8 GB RAM → der lokale Weg lohnt nicht.** Besser der API-Weg.
   Wer es dennoch lokal will: LFM2.5-2.6B mit auf 8K reduziertem Kontext und ohne
   nebenher laufende Programme.
4. **1,58-Bit-Modelle bringen hier keinen Vorteil.** Weder schneller noch
   sparsamer als ein gleich großes Q4-Modell; das kleine 1,7B-Modell fasst gar
   nicht zusammen. Lohnt erst, wenn die Rechenkerne dafür (llama.cpp-Upstream,
   noch offen) ausgereift sind.

### Umgesetzt in der Anwendung

Aus dieser Empfehlung ist eine Einstellung geworden: In der Ersteinrichtung lässt
sich für das Protokoll zwischen **Qwen3.5 4B** (beste Qualität) und **LFM2.5 2.6B**
(schneller, weniger Arbeitsspeicher) wählen; die Hardware-Einschätzung schlägt je
nach Grafikkarte und Arbeitsspeicher das passende vor. Auf einem Gerät ohne
Grafikkarte mit knappem Arbeitsspeicher (8 GB) empfiehlt sie für das Protokoll den
Online-Dienst. LFM2.5 wird über denselben Ollama-Weg geladen wie die übrigen Modelle
(Modell-Id `hf.co/LiquidAI/LFM2.5-2.6B-GGUF:Q4_K_M`); da es intern „denkt", ruft die
Anwendung es über `/api/chat` auf, damit der Gedankengang nicht im Protokoll landet.
Mit echten Modellen auf der Grafikkarte über die Ende-zu-Ende-Tests geprüft (Qwen und
LFM).

### Lizenzhinweis

LFM2.5 steht unter der **LFM Open License v1.0**: kostenlose kommerzielle Nutzung
nur bis 10 Mio. USD Jahresumsatz. Qwen (Apache-2.0) und die Ternary-Bonsai-Modelle
(Apache-2.0) sind unbeschränkt. Bei einer Produktentscheidung zu beachten.

## Hinweise zur Messung

* Alle Modelle bekamen dasselbe Transkript und denselben Auftrag (freie
  Zusammenfassung, kein eigener Systemprompt).
* Die Sampling-Einstellungen folgten der Empfehlung des jeweiligen Anbieters
  (LFM: `temp 0,1`, `top-k 50`, `repeat-penalty 1,1`; die übrigen: Vorgaben des
  jeweiligen Servers). Gleiche Zeiten sind deshalb nur grob vergleichbar; die
  Größenordnungen sind eindeutig.
* Der Detailgrad der Zusammenfassung schwankt von Lauf zu Lauf (greedy ist nicht
  exakt deterministisch über verschiedene Backends). Ein knapperer Lauf lässt
  Zahlen weg, ohne falsch zu sein.
