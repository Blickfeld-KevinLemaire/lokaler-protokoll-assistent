# Ende-zu-Ende-Test mit echten Modellen (Oktober 2026)

Gemessen am 04.10.2026 mit den neuen Ende-zu-Ende-Tests (`tests/e2e/`). Anlass
war der Wechsel auf Qwen3.5 als Sprachmodell; die Tests sollten zeigen, ob die
lokale Kette mit echten Modellen auf einem 6-GB-Laptop trägt.

## Ergebnis

**Die Kette trägt – aber erst nach vier Korrekturen, die die Tests gefunden
haben.** Zwei davon steckten schon vor dem Modellwechsel in `main` und machten
lokale Protokolle langer Aufnahmen unvollständig oder unmöglich, eine dritte
ließ den ganzen Rechner abstürzen. Die Unit-Tests konnten keinen dieser Fehler
sehen, weil sie kein echtes Modell aufrufen.

| Fund | Auswirkung | Behebung |
|---|---|---|
| `generate_json` setzte keine Kontextgröße, Ollama nahm 4096 Tokens | Transkriptanfang still verworfen (`truncated = 1`, 22-mal in einem Lauf); Gesamtprotokolle brachen mitten im JSON ab | Kontext je Aufruf: 16K für Abschnitte, 32K für das Gesamtprotokoll (`ollama_service.kontext_fuer_protokoll`) |
| `MAX_KONTEXT_ZEICHEN` (Stufe 3) passte nicht zum Kontext | Gesamtprotokoll einer Stunde scheiterte auch mit 16K | gemessen ~3 Zeichen je Token statt 4; ein Test koppelt beide Grenzen |
| pyannote auf der GPU im selben Prozess wie Whisper | **Bluescreen `HYPERVISOR_ERROR`**, dreimal identisch | Sprechertrennung auf der GPU in einem eigenen Prozess (`services/diarisierung_prozess.py`) |
| Offene Fragen, Fakten, Termine als Objekte | Rohdaten `{'frage': …}` im Protokoll | `export_service.listeneintrag_als_text`; Systemprompt verlangt Text |
| Systemprompt erzwang Aufgaben | zehn erfundene Aufgaben bei einer Podiumsdiskussion | Liste bleibt leer, wenn niemand etwas zugesagt hat |
| Test-Fixture entfernte `HF_TOKEN` auch für E2E | Sprechertrennung lief in den E2E-Tests nie | Token wird beim Laden des Testmoduls erfasst |

## Aufbau

| | |
|---|---|
| Rechner | Laptop, NVIDIA RTX PRO 500 Blackwell (6 GB), 63,5 GB RAM, 16 Kerne, Windows 11 mit Speicherintegrität (VBS/HVCI) |
| Transkription | Whisper `large-v3-turbo` über faster-whisper (CTranslate2, CUDA 12.8) |
| Sprechertrennung | `pyannote/speaker-diarization-community-1` (PyTorch 2.11 cu128) |
| Protokoll, Chat | `qwen3.5:4b-q4_K_M` über Ollama 0.35.1, `think: false`; Suche `bge-m3` |
| Material 1 | gespielte Besprechung, 89 s, drei deutsche Windows-Stimmen, Fakten bekannt (`tests/e2e/besprechung.py`) |
| Material 2 | Podiumsdiskussion der Böll-Stiftung „Grüne Marktwirtschaft", 66 min, nicht im Repository |

Gestartet wurde die Verarbeitung über den Servermodus
(`python -m protokoll_assistent.server --einmal`) – derselbe Code wie in der
Anwendung, ohne Fenster.

## Dauer und Auslastung (66 Minuten Material)

| Schritt | Dauer | Gerät |
|---|---|---|
| Audio vorbereiten | 3 s | CPU |
| Transkription, 7 Abschnitte à 10 min | 2:49–2:55 min (~23× Echtzeit) | GPU |
| Sprechertrennung auf der CPU | 25 min | CPU |
| Sprechertrennung auf der GPU, eigener Prozess | *siehe Nachtrag* | GPU |
| Abschnittsanalysen (7) | ~5 min (~42 s je Abschnitt, 42 Tokens/s) | GPU, 16K Kontext |
| Zwischenzusammenfassungen (2) | ~4 min | GPU |
| Gesamtprotokoll | ~8 min (Eingabe 11.726, Ausgabe 10.211 Tokens) | 32K Kontext: 24 % CPU / 76 % GPU, 21 Tokens/s |

Mit 32K Kontext passt das 4B-Modell auf 6 GB nicht mehr ganz in den
Grafikspeicher und schreibt nur halb so schnell; deshalb nimmt die Anwendung
32K nur für das Gesamtprotokoll. Grafikspeicher im Lauf: bis 5,8 von 6 GB.

## Qualität

**Gespielte Besprechung:** Alle Fakten kommen an – Termin, Budget, beide
Aufgaben mit Verantwortlichen und Fristen, offene Frage, Folgetermin.

**Transkript der Podiumsdiskussion:** 8.211 Wörter, saubere Sätze; Fehler fast
nur bei Eigennamen („Machnick" statt Machnig, „Büttekofer" statt Bütikofer,
„Niklas Stern" statt Nicholas Stern, „ortoliberal" statt ordoliberal).

**Sprechertrennung:** Die Podiumsdiskussion ergab automatisch drei Sprecher
(9,4 / 29,8 / 23,3 min Redezeit) – Moderation und zwei Gäste. Die gespielte
Besprechung ergab automatisch nur einen: Drei sehr gleichmäßige Computerstimmen
in 89 s fasst pyannote zusammen. Mit vorgegebener Sprecherzahl 3 trennt es
richtig; der Test gibt die Zahl deshalb vor.

**Protokoll:** inhaltlich stark, Zahlen stimmen (EEG-Umlage 2,8 Mrd. €, 40 %
CO2-Ziel bis 2020). Zu lang (28 Themen für eine Stunde).

**Chatbot** (gleiches Transkript):

| Frage | Grundlage | Zeit | Ergebnis |
|---|---|---|---|
| Zusammenfassung, Positionen | ganzer Text, 4 Abschnitte | 225 s | sehr gut |
| CO2-Bepreisung | Ausschnitte | 21 s | richtig, knapp |
| konkrete Vorschläge | Ausschnitte | 11 s | falsch („keine") – verteilt über die Stunde |
| Kritik, von wem | ganzer Text | 201 s | Inhalt gut, Zuordnung teils falsch (ohne Sprechertrennung) |
| Eintrittspreis (steht nicht drin) | Ausschnitte | 11 s | richtig abgelehnt |

## Der Absturz (`HYPERVISOR_ERROR`)

Dreimal – am 19.09. um 19:59 und am 04.10. um 13:43 und 13:49 – ging der
Laptop mit Bluescreen `0x00020001` aus, jedes Mal mit **denselben Parametern**
`(0x28, 0x1, 0x29b92701, 0xfc801000)`. Ein Speicherabbild entstand nicht
(`volmgr 161`).

**Ablauf vor dem Absturz** (Zwischendateien im Arbeitsordner): Whisper
transkribierte fehlerfrei auf der GPU, das Transkript wurde geschrieben, dann
legte die Pipeline die leere `sprecher_embeddings.json` an und lud pyannote auf
die GPU – danach kam keine Datei mehr. Am 19.09. war die Sprechertrennung zum
ersten Mal auf echter Hardware eingerichtet worden.

**Gegenprobe:** In einem frischen Prozess, in dem nur PyTorch die Karte benutzt
(Whisper und Ollama vorher entladen, 0 MiB belegt), lief dieselbe
Sprechertrennung stabil: 89 s Audio in 7 s.

**Schluss:** Der Fehler entsteht im Zusammenspiel von pyannote/PyTorch mit der
CUDA-Umgebung von CTranslate2 im selben Prozess, bei aktiver
Speicherintegrität. Die Ursache liegt in Treiber oder Hypervisor
(Treiber 32.0.15.9658, das Update am 19.09. half nicht), ausgelöst durch diese
Anwendung – und trifft damit jeden mit derselben Kombination. Die Pipeline
startet die Sprechertrennung auf der GPU deshalb in einem eigenen Prozess und
gibt vorher Whisper frei; scheitert der Prozess, rechnet sie auf der CPU.
Ausgeschlossen: die PCIe-Meldungen (WHEA 17, bei jedem Start seit Wochen) und
die `nvidia-smi`-Abfragen (am 19.09. nicht aktiv).

## Nachtrag: Lauf mit Sprechertrennung im eigenen Prozess

Derselbe Lauf mit dem neuen Weg (Sprechertrennung auf der GPU im eigenen
Prozess, Whisper vorher freigegeben, Ollama nur bei knappem Grafikspeicher
entladen): **kein Absturz**, alle Tests grün (7 bestanden, 1 übersprungen –
der Oberflächentest der Transkription läuft nur im Python der
Laufzeitumgebung), 0 Kürzungen in Ollama.

| Schritt (66 min Material) | CPU, im Prozess | GPU, eigener Prozess |
|---|---|---|
| Transkription | 2:55 min | 2:53 min |
| Sprechertrennung | 25 min | **5:04 min** |
| Protokoll (drei Stufen) | 21 min | 31 min |
| erkannte Sprecher | 3 | 3 (identische Redezeiten) |

Gespielte Besprechung mit vorgegebener Sprecherzahl 3: drei Sprecher (6, 9 und
8 Abschnitte).

Das Protokoll dauerte länger, weil die Zwischenanalysen mit
Sprecherangaben größer wurden (39 statt 35 KB), die Grenze von 40.000 Zeichen
überschritten und damit eine zusätzliche Verdichtungsrunde auslösten (9 min).
Bei einer Stunde Material entfallen so drei Viertel der Zeit auf das Protokoll.
Nächster Hebel: ein Systemprompt, der das Protokoll knapper hält (28 Themen
für eine Stunde sind zu viel) – das verkürzt die Ausgaben aller drei Stufen.

## Reproduktion

```powershell
# einmalig: Ollama mit qwen3.5:4b-q4_K_M und bge-m3; HF_TOKEN in der .env
$env:PROTOKOLL_E2E = "1"
$env:PROTOKOLL_E2E_AUFNAHME = "<Pfad zu einer echten Aufnahme>"   # optional, 3-Minuten-Ausschnitt
uv run pytest protokoll_assistent/tests/e2e -m e2e
# die ganze Aufnahme nur bei Änderungen an langen Aufnahmen:
$env:PROTOKOLL_E2E_LANG = "1"
```

Die Aufnahme der Podiumsdiskussion liegt bewusst nicht im Repository.
