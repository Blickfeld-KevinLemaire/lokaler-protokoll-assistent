# Changelog

Alle nennenswerten Änderungen an diesem Projekt werden in dieser Datei
festgehalten.

Das Format orientiert sich an [Keep a Changelog](https://keepachangelog.com/de/1.1.0/),
die Versionierung an [Semantic Versioning](https://semver.org/lang/de/).

## [Unreleased]

### Added

- **Ollama läuft im Hintergrund, solange Geräte liefern:** Ollama wird nicht mehr über seine Oberfläche gestartet
  (`ollama app.exe` beendete sich bei Tests mitten in einem Modell-Download selbst, Ollama 0.40.4), sondern als Dienst
  (`ollama serve`, unsichtbar, vom Programm gelöst). Fällt der Dienst weg, startet ihn jede Anfrage an das lokale Modell
  neu und wiederholt sich einmal, und eine Wache (alle 30 s, solange der Geräteempfang an ist und lokal ausgewertet wird)
  startet ihn bei Bedarf neu und meldet im Empfangshinweis, wenn das Sprachmodell fehlt. So klappt auch die
  Zusammenfassung vom Aufnahmegerät, wenn niemand am PC sitzt.
  Die Wache schweigt während der Ersteinrichtung (dort installiert sie Ollama und lädt die Modelle erst), und ein
  Hinweis „Sprachmodell fehlt“ oder „Ollama nicht erreichbar“ verschwindet wieder, sobald das Problem behoben ist –
  er blieb im ersten Durchlauf stehen, obwohl die Einstellungen das Modell als installiert zeigten.
- **Einrichtung: Sprachmodell wirklich geladen:** Fällt Ollama während des Downloads weg, startet der Dienst neu und der
  Download geht dort weiter (bis zu dreimal). „Fertig“ gilt erst, wenn das Modell bei Ollama liegt; sonst steht auf der
  letzten Seite deutlich, dass Protokoll und Zusammenfassung ohne das Modell nicht gehen.
- **Einrichtung hält Ollama nicht mehr fälschlich für installiert:** Ein stehengebliebener Deinstallationseintrag (nach
  einer von Hand gelöschten oder halb abgebrochenen Installation) genügte bisher; dann wurde nichts installiert, und die
  Nachbearbeitung scheiterte später. Jetzt zählt nur ein vorhandenes `ollama.exe` oder ein antwortender Dienst.
- **Rückfrage „Zusammenfassung erstellen?“ ohne Antwort bleibt nicht mehr hängen:** Beginnt das Gerät eine neue
  Aufnahme (oder startet es neu), bevor die Frage zur vorigen beantwortet ist, wartet die vorige nicht länger. Reicht
  die Grafikkarte für Sprachmodell und Whisper zugleich (oder läuft die Zusammenfassung über eine API), wird sie nach
  den neuen Aufnahmen zusammengefasst; sonst bleibt es beim Transkript, damit die neue Aufnahme nicht warten muss.
  „Nein“ am Gerät meldet das Gerät jetzt an die Software (`POST …/keine_zusammenfassung`) – eine abgelehnte
  Zusammenfassung entsteht so auch später nicht.
- **Firmware S3 mit Display: Hinweis nach einem Neustart:** Wird das Gerät zurückgesetzt oder aus- und wieder eingeschaltet (etwa
  durch einen versehentlichen Druck auf die Ein/Aus-Taste, die den Strom in der Hardware unterbricht und von der Firmware nicht
  abgefangen werden kann), zeigt die Statuszeile 8 Sekunden „NEUSTART“; war dabei eine Aufnahme aktiv, „NEUSTART: AUFNAHME
  GESICHERT“. Die Aufnahme bleibt auf der SD-Karte (die Firmware sichert alle 30 s) und wird wie jede andere hochgeladen. Ein
  gewollter Neustart per Software (USB-Einrichtung) zeigt nichts.
- **Firmware S3 mit Display: Auftrag wählen, Zusammenfassung freigeben, Fragen stellen:** Unter „AUFNAHME STARTEN“ steht
  eine Auswahlliste mit den Aufträgen der Software (Namen ohne Umlaute). Nach dem Transkript zeigt das Gerät den grünen Haken
  und fragt „ZUSAMMENFASSUNG ERSTELLEN?“ (JA/NEIN); nach „Ja“ erstellt die Software die Zusammenfassung, am Ende erscheint
  „ZUSAMMENFASSUNG FERTIG“. Danach lässt sich mit der **BOOT-Taste an der Seite** (gedrückt halten, sprechen, loslassen)
  eine Frage stellen; die Antwort erscheint als scrollbarer Text auf dem Display (Tippen schließt). Die Bedienung läuft
  im Upload-Task und legt große Puffer im PSRAM ab, weil der interne RAM knapp ist.
- **Fragen per Sprache zu einer Aufnahme (PC-Seite):** Ein Gerät kann nach dem Transkript eine gesprochene Frage stellen
  (`POST …/frage`, Stand über `GET /api/v1/fragen/<Kennung>`, Antwort als Ton über `…/ton`). Whisper (Prozessor)
  versteht die Frage, das lokale Sprachmodell beantwortet sie kurz aus Zusammenfassung und Transkript der Aufnahme,
  die Antwort kommt standardmäßig als kurze Liste fürs Display des Geräts (nur ASCII, `X-Ausgabe: anzeige`); eine
  Sprachausgabe (`X-Ausgabe: ton`) ist vorbereitet, die Engine wird von außen eingesetzt. Alles läuft lokal; die Antwort gehört nur dem fragenden Gerät.
- **Auftrag am Gerät wählen und Zusammenfassung nach dem Transkript freigeben (PC-Seite):** Neuer Aufruf
  `GET /api/v1/auftraege` (Namen der Vorlagen für eine Auswahlliste am Gerät), Kopfzeilen `X-Auftrag` und
  `X-Rueckfrage` beim Hochladen, neuer Zustand `transkript` und `POST …/zusammenfassung`. Der am Gerät gewählte
  Auftrag gilt für diese Aufnahme (auch für die Vorab-Auswertung). Mit Rückfrage meldet die Software nach dem
  Transkript „Transkription erfolgreich“ und erstellt die Zusammenfassung erst, wenn das Gerät sie freigibt;
  eine Freigabe geht neuen Aufnahmen in der Warteschlange vor. Geräte ohne diese Kopfzeilen laufen unverändert.
- **Zweites lokales Sprachmodell zur Wahl – LFM2.5 2.6B:** Neben Qwen3.5 4B
  steht jetzt LFM2.5 2.6B (Liquid AI) zur Auswahl – schneller und mit weniger
  Arbeitsspeicher (~4,6 GB statt ~5 GB), dafür etwas knapper als Qwen. Die
  Ersteinrichtung/Hardware-Einschätzung empfiehlt es für Rechner ohne
  Grafikkarte; auf 8-GB-Geräten mit dem Hinweis, dass der Arbeitsspeicher knapp
  ist und ein Online-Dienst meist besser passt. Es wird wie die übrigen Modelle
  über Ollama geladen (LFM Open License – kommerzielle Nutzung bis 10 Mio. USD
  Jahresumsatz kostenlos).
  In der Ersteinrichtung lässt sich das Sprachmodell für das Protokoll jetzt
  direkt auf der Seite „Arbeitsweise“ auswählen (nur die Modelle, die dieser
  Computer schafft; das empfohlene ist vorausgewählt). Auf einem 8-GB-Rechner
  ohne Grafikkarte empfiehlt die Ersteinrichtung außerdem die gemischte
  Arbeitsweise: Mitschrift lokal, Protokoll über einen Online-Dienst.
- **Live-Transkription und automatische Auswertung für Aufnahmegeräte (PC-Seite):**
  Schickt ein Gerät seine Aufnahme schon während der Aufnahme (Ogg-Opus, Stück für
  Stück), transkribiert die Anwendung sie laufend mit einem gleitenden Fenster
  (Whisper auf dem Prozessor, sobald 20 s neues Audio da sind): Fertige Sätze gelten
  als sicher, das abgeschnittene Ende wird im nächsten Fenster neu mitgerechnet. Das
  Transkript wächst so mit etwa 20 bis 40 s Verzögerung, auch in der Vorschau der
  Anwendung. Mit dem Ende der Aufnahme beginnt die Verarbeitung
  von selbst: Sie übernimmt die sicheren Segmente, transkribiert nur noch die letzten
  Sekunden und
  wertet nach dem Auftrag aus den Einstellungen aus – ohne Rückfragefenster. Das
  Gerät fragt den Stand über die neue Schnittstelle
  `GET /api/v1/aufnahmen/<Name>/status` ab (Zustände `empfang`, `wartet`,
  `transkription`, `auswertung`, `fertig` mit „Transkription erfolgreich",
  `fehler`). Einstellungen → Aufnahmegeräte: Schalter und Auftrag (eine
  Systemprompt-Vorlage); ab Werk an. Von den Geräten sendet bisher das S3 mit
  Bildschirm während der Aufnahme und zeigt den Stand an (siehe unten); S3-AUDIO
  und C6 noch nicht (siehe `firmware/docs/streaming-konzept.md`).
- **Auswertung schon während der Aufnahme vorbereiten:** Das Sprachmodell wertet jeden fertigen
  Abschnitt der laufenden Aufnahme (Standard 180 s, einstellbar 60–600 s; von Hand gestartete Auswertungen bleiben bei 600 s) sofort aus (Stufe 1) und führt feststehende Gruppen
  zusammen (Stufe 2), während Whisper auf dem Prozessor weiter transkribiert. Nach dem Ende fehlen
  nur noch die letzten Abschnitte und das Endergebnis; die Wartezeit sinkt bei längeren Meetings
  deutlich. Teilergebnisse werden nur übernommen, wenn ihre Eingabe (Modell, Auftrag, Text)
  genau zur fertigen Auswertung passt. Dafür enthält der Auswertungstext der automatischen
  Verarbeitung keine Sprecherangaben (im Transkript stehen sie weiterhin). Einstellungen →
  Aufnahmegeräte: „Auswertung schon während der Aufnahme vorbereiten“ (ab Werk an).
- **Firmware (S3 mit Bildschirm): Senden während der Aufnahme und Anzeige „Transkription erfolgreich“:**
  Das Gerät schickt die Aufnahme alle 15 s in Stücken an die Protokoll-Software (Ringpuffer im PSRAM, `PUT` mit `X-Offset`),
  während die Aufnahme läuft. Nach dem Stopp lädt es den Rest hoch und fragt den Verarbeitungsstand ab; das Display zeigt
  „TRANSKRIPTION WIRD VERARBEITET“, am Ende ca. 4 s ein grünes Häkchen mit „TRANSKRIPTION ERFOLGREICH“ über den ganzen
  Bildschirm und danach dauerhaft die Statuszeile „✓ TRANSKRIPTION ERFOLGREICH“ (bei Fehlern rot). Es geht nichts verloren: Die
  Aufnahme liegt immer ganz auf der SD-Karte, und der normale Upload macht dort weiter, wo die Software steht. Die zuletzt
  aufgenommene Aufnahme wird jetzt zuerst hochgeladen (vor älteren Dateien, auch wenn mehr als 32 davon warten), und das
  Prüfsummen-Lesen einer langen angefangenen Datei lässt sich abbrechen, sobald eine Aufnahme beginnt (vorher hielt es die
  SD-Karte minutenlang besetzt). Lehnt die Software die Statusabfrage ab (`4xx`, etwa eine ältere Version ohne `…/status`
  oder ein widerrufenes Token), fragt das Gerät nicht weiter nach, statt es bis zu 3 Stunden alle 3 s zu versuchen; nach
  einem gescheiterten Live-Stück wartet es den normalen Abstand von 15 s ab. Siehe `firmware/README.md`.

- **Aufnahmegeräte im WLAN laden selbst hoch:** Ist der Empfang eingeschaltet
  (Einstellungen → „Aufnahmegeräte“, im Servermodus `PROTOKOLL_EMPFANG=1`),
  landen die Aufnahmen der eigenen ESP32-Geräte ohne Umweg im Eingabeordner und
  erscheinen sofort in der Dateiliste. Jedes Gerät meldet sich mit einem eigenen
  Token an, das die Anwendung erzeugt und einmal anzeigt. Bricht die Verbindung
  ab, geht es beim letzten bestätigten Stück weiter statt von vorn; eine Datei
  erscheint erst, wenn ihre Prüfsumme stimmt, und eine doppelt gesendete
  Aufnahme wird nicht zweimal abgelegt. Die Einstellungen zeigen je Gerät, wann
  es sich zuletzt gemeldet hat – mit Werks-Id und Firmware. Ab Werk ist der
  Empfang aus; die Übertragung ist nicht verschlüsselt und nur für das eigene
  Netz gedacht (siehe `SECURITY.md`).
- **Aufnahmegeräte per USB einrichten:** Gerät per USB-Kabel anschließen,
  unter *Einstellungen → Aufnahmegeräte → Gerät per USB einrichten* WLAN-Name
  und Passwort eingeben – die Anwendung erkennt das Gerät (Board, Werks-Id,
  Firmware), erzeugt das Token und schreibt WLAN, eigene Adresse und Token in
  einem Zug ins Gerät. Niemand muss mehr Firmware kompilieren oder Token
  abtippen. Danach steht das Gerät mit seiner Id in der Liste, und eine Zeile
  für das Geräte-Inventar lässt sich kopieren. Meldet sich unter dem Namen
  eines Geräts plötzlich andere Hardware, zeigt die Liste eine Warnung.
- **VERMERK Raum gleich bei der Ersteinrichtung verbinden:** Direkt nach der
  Begrüßung fragt der Assistent, ob es ein VERMERK Raum gibt, und koppelt das
  Aufnahmegerät auf Wunsch per USB – Gerät anschließen, WLAN-Name und Passwort
  eingeben, fertig; der Empfang wird dabei eingeschaltet. Wer kein Gerät hat,
  überspringt den Schritt. Die Einrichtung unter *Einstellungen →
  Aufnahmegeräte* bleibt wie bisher möglich.

- **Neue Ersteinrichtung:** Beim ersten Start erklärt ein Assistent in
  einfachen Worten, was das Programm macht, zeigt für **diesen** Computer je
  Arbeitsschritt (Mitschrift, Sprechererkennung, Protokoll, Frag mein Meeting),
  ob er gut, langsam oder gar nicht geht und wie lange eine Stunde Aufnahme
  ungefähr dauert, und empfiehlt eine Arbeitsweise (alles lokal, gemischt oder
  online – online wird nie vorausgewählt). Danach steht genau da, was geladen
  wird, mit Download- und Platzbedarf; erst nach Zustimmung geht es los.
- **Ollama wird auf Wunsch automatisch installiert:** Der offizielle
  Installer kommt direkt vom Hersteller, wird auf seine Signatur
  („Ollama Inc.“) geprüft und still nur für das eigene Benutzerkonto
  installiert – ohne Administratorrechte, ohne Rückfragen. Ist Ollama schon da,
  wird nichts neu installiert. Ollama wird weiterhin nicht mit dem Programm
  ausgeliefert.
- **Hugging-Face-Zugang merken:** Die Ersteinrichtung fragt den Schlüssel für
  die Sprechererkennung mit Anleitung ab und merkt ihn auf Wunsch verschlüsselt
  in der Windows-Anmeldeinformationsverwaltung (nie in einer Datei).

- **Hugging-Face-Token aus `.env`:** Wer den Token nicht bei jedem Start als
  Umgebungsvariable setzen will, traegt ihn als `HF_TOKEN=...` in die `.env`
  im Programmordner ein (Vorlage `.env.beispiel`; die Datei ist von Git
  ignoriert). Eine gesetzte Umgebungsvariable hat Vorrang.
- **Frag mein Meeting:** Neuer Chatbot in der Seitenleiste. Links werden
  Transkripte und Zusammenfassungen angehakt, rechts stellt man Fragen; die
  Antworten stützen sich nur auf die ausgewählten Unterlagen und nennen ihre
  Quellen (Dokument und Uhrzeit). Dahinter arbeitet eine Suche in
  Textabschnitten (Einbettungen, zwischengespeichert) und ein Chatmodell.
- Neuer Reiter **Chatbot** in den Einstellungen: lokal (Ollama) oder API, mit
  Auswahl des Chatmodells und des Einbettungsmodells (BGE-M3, Nomic Embed
  Text, MixedBread, EmbeddingGemma oder eigener Name), Status und „Jetzt
  herunterladen“. Im API-Modus gibt es Endpunkt und Modell für Chat und
  Einbettungen sowie einen eigenen oder gemeinsamen Schlüssel; ein
  Datenschutzhinweis erscheint, weil dort Texte übertragen werden.
- **Frag mein Meeting – Hinweisleiste und Systemcheck:** Fehlt ein Modell, steht
  das als erster Hinweis oben auf der Seite, mit „Jetzt herunterladen“. Das
  Einbettungsmodell wird nur auf Wunsch geladen, nie von allein; der Hinweis
  verschwindet, sobald es da ist. Der Knopf „Systemcheck“ prüft Ollama bzw.
  den API-Zugang, die Modelle und macht je einen Probelauf für Suche und Antwort.
- **Gespeicherte Chats:** Jeder Chat wird automatisch gespeichert und steht links
  unter „Gespeicherte Chats“. Ein Klick öffnet ihn samt Nachrichten und den
  damals gewählten Unterlagen; Umbenennen und Löschen sind möglich.
  Die Dateien liegen lokal im Ordner `chatverlaeufe/` (nicht versioniert, nicht im Installer).
- **Frag mein Meeting – Grundlage wählbar:** Über dem Eingabefeld steht jetzt
  „Grundlage“. „Passende Ausschnitte“ (Standard) sucht wie bisher die Stellen,
  die zur Frage passen. „Ganzer Text“ gibt dem Modell alles – für
  Zusammenfassungen und Fragen, die die ganze Besprechung betreffen. Passt der
  Text nicht in eine Anfrage (lokal etwa 80.000 Zeichen, gut eine Stunde
  Besprechung), wird er in überlappenden Abschnitten gelesen; aus den Notizen
  je Abschnitt entsteht die Antwort. Dafür ist kein Einbettungsmodell nötig.
  Die Wahl wird gemerkt.
- **Rechner-Analyse als erster Schritt der lokalen Einrichtung:** Bevor etwas
  heruntergeladen wird, prüft das Programm Arbeitsspeicher, Prozessorkerne,
  die vorhandene Grafikkarte (egal von welchem Hersteller: NVIDIA, AMD, Intel,
  auch integrierte Grafik) und den freien Platz und bewertet jedes Modell
  (Transkription, Nachbearbeitung, Suche im Chat) mit „Läuft gut“, „Läuft
  langsam / knapp“ oder „Eher nicht geeignet“, samt Hinweisen und Empfehlung.
  Das empfohlene Sprachmodell wird für die Einrichtung vorausgewählt – eine
  bewusst getroffene Wahl in den Einstellungen bleibt unberührt. Es sind
  Schätzungen; jedes Modell lässt sich weiterhin wählen. Beschleunigen kann
  die Grafikkarte die Transkription nur bei NVIDIA (CUDA); eine Radeon-
  Einzelkarte kann Ollama bei der Nachbearbeitung helfen, wenn ihr Modell
  unterstützt wird, integrierte Grafik beschleunigt nichts – das erklärt die
  Analyse bei der erkannten Karte.
- **Systemtest: „Fehlendes nachladen“.** Fehlen FFmpeg, Ollama oder das
  Ollama-Modell, lädt ein Knopf sie herunter und zeigt den Grund, falls es
  scheitert; danach wird automatisch neu geprüft.

- **API-Anbieter zum Auswählen statt Voreinstellung:** In den Einstellungen
  (Transkription, Nachbearbeitung, Chatbot) wählt man den Anbieter aus einer
  Liste – IONOS, STACKIT, Mistral, Scaleway, Microsoft Azure, OpenAI, Anthropic
  (Claude), Google Gemini, Groq, OpenRouter oder „Eigener Endpunkt“ – und muss
  nur noch den API-Schlüssel eintragen. Adresse und Modellvorschlag werden
  eingesetzt; darunter stehen Standort, Hinweise und Links zum Schlüssel und
  zur Dokumentation. Die Transkription über eine API bleibt bei OpenRouter bzw.
  einem eigenen Endpunkt im selben Format (Audio im API-Aufruf, kein
  Dateiupload); die übrigen Anbieter gibt es für Nachbearbeitung und Chatbot.

- **Export in gängige Formate:** Der neue Knopf „Exportieren …“ (auf der
  Ergebnisseite und unter „Nachbearbeitung“) speichert Transkript, Protokoll
  oder beides in einem Dokument als Word, PDF, Markdown, Text, HTML oder
  OpenDocument – das Transkript zusätzlich als Untertitel (SRT, VTT) und JSON –
  in einen frei gewählten Ordner. Ziel und Formate werden für das nächste Mal
  gemerkt; vorhandene Dateien werden nie überschrieben.
- **Zusammengefasste Word-Datei von selbst:** Nach jeder Transkription entsteht
  neben den übrigen Ausgaben eine Word-Datei mit dem Transkript, nach der
  Nachbearbeitung eine mit Protokoll und Transkript in einem Dokument. Sie wird
  nach dem Umbenennen von Sprechern neu geschrieben. Scheitert das, bleibt die
  Verarbeitung gültig; der Grund steht im Protokoll.

- **Servermodus für Linux (Container):** Aufnahmen, die in einem Eingangsordner
  ankommen, werden automatisch in Chunks verarbeitet, transkribiert und
  zusammengefasst; Transkript, Protokoll und die zusammengefasste Word-Datei
  liegen danach in einem Ausgangsordner (`ergebnis.json` meldet den Ausgang,
  optional auch per Webhook). Läuft ohne Oberfläche per `docker compose`
  (Prozessor oder NVIDIA-Grafikkarte, Ollama als eigener Dienst); Einstellungen
  über Umgebungsvariablen. Anleitung: `protokoll_assistent/server/README.md`.
- **Ergebnis der Nachbearbeitung vor dem Export ansehen und überarbeiten:**
  Die Seite „Nachbearbeitung“ zeigt das fertige Protokoll (bzw. die
  Zusammenfassung) direkt an. Der Text lässt sich dort bearbeiten; „Änderungen
  speichern“ schreibt ihn in die Protokolldateien zurück und erneuert die
  zusammengefasste Word-Datei – immer mit dem Transkript, aus dem dieses
  Ergebnis entstanden ist. „Exportieren …“ schlägt das angezeigte Protokoll
  vor. Wer ungespeicherte Änderungen hat und eine neue Nachbearbeitung
  startet, exportiert oder das Fenster schließt, wird vorher gefragt. Solange
  eine Nachbearbeitung läuft, ist das Feld gesperrt, damit ihr Ergebnis
  nichts Getipptes überschreibt.

### Changed

- **Neue Reihenfolge in der Seitenleiste:** „Nachbearbeitung“ steht jetzt
  nach „Ergebnis und Sprecher“ – also in der Reihenfolge, in der man
  arbeitet: transkribieren, Sprecher benennen, Protokoll erstellen.
- Die Nachbearbeitung richtet sich jetzt ausschließlich nach dem
  Systemprompt. Bisher erzwang das Programm unabhängig davon immer dieselbe
  Besprechungsstruktur (Titel, Themen, Entscheidungen, Aufgaben, Termine,
  offene Fragen …) – in den Anfragen an das Modell, in der Prüfung der Antwort
  und in der Ausgabedatei. Jetzt antwortet das Modell frei nach dem Auftrag,
  und die Ausgabedatei (`.md`) enthält genau diesen Text.
- Ohne Systemprompt fasst das Modell so zusammen, wie es am sinnvollsten ist.
  Ein leeres Feld wird nicht mehr abgelehnt, und der Editor ist nicht mehr mit
  dem Besprechungs-Prompt vorbelegt. Dieser steht als Vorlage
  „Besprechungsprotokoll“ weiter zur Auswahl.
- Die `.json` neben dem Ergebnis enthält jetzt `ergebnis`, `systemprompt` und
  `ohne_systemprompt` statt der festen Protokollfelder.
- Die mitgelieferte Prompt-Datei mit fester JSON-Struktur ist leer; der
  Word-/PDF-Export und die Protokoll-Datei folgen dem Ergebnistext des Modells.
  Die Vorlagen „Formelles Protokoll“, „Projektbesprechung“, „Stand-up“,
  „Technische Besprechung“ und „Interview“ nennen ihre Abschnitte jetzt als
  Überschriften im Freitext statt als JSON-Felder. Protokolle aus früheren
  Läufen (feste Gliederung) lassen sich weiter exportieren.
- Die mehrstufige Verdichtung langer Transkripte (mehrere Runden bis zum
  Kontextlimit) arbeitet jetzt auf dem Ergebnistext.

- **OpenRouter ist nicht mehr voreingestellt.** Endpunkte und Modelle sind ab
  Werk leer, bis ein Anbieter gewählt wird; ohne Auswahl meldet das Programm
  „Kein Anbieter gewählt“, statt Aufnahmen oder Texte irgendwohin zu senden.
  Bereits gespeicherte Einstellungen bleiben erhalten und werden in der Liste
  richtig angezeigt.
- **Neues Standardmodell für die Nachbearbeitung: Qwen3.5 4B**
  (`qwen3.5:4b-q4_K_M`, etwa 3,3 GB) statt Qwen3 8B. Es ist trotz halber Größe
  leistungsfähiger und braucht weniger Speicher; das gilt auch für den Chatbot
  und den Servermodus.
- **Modellauswahl erneuert und verkleinert.** Zur Wahl stehen jetzt vier
  Modelle, alle unter Apache 2.0 und ausdrücklich in der Q4-Fassung:
  Qwen3.5 4B (Standard), **Qwen3.5 9B** (genauer, liegt in Tests vor dem
  bisherigen Qwen3 14B), **Gemma 4 12B** und für Rechner mit großer
  Grafikkarte (etwa 24 GB) **Qwen3.8 27B**. Entfallen sind Qwen3 4B, 8B und
  14B, Gemma 3, Llama 3.1 und Mistral Nemo; sie lassen sich weiterhin von Hand
  eintragen. Wer schon ein Modell gespeichert hat, behält es. Rechner mit
  weniger als etwa 7,8 GB Arbeitsspeicher bekommen bei der Einrichtung kein
  lokales Sprachmodell mehr empfohlen, sondern den Hinweis auf die API.
  Qwen3.5 und neuer brauchen ein aktuelles Ollama – bei einer älteren Fassung
  scheitert der Download.
- Die „Denkphase“ der Sprachmodelle wird jetzt über Ollama abgeschaltet
  (`think: false`). Das bisherige `/no_think` im Systemprompt verstehen
  Qwen3.5-Modelle nicht mehr; ohne die Änderung hätten sie vor jeder Antwort
  lange „nachgedacht“.
- **Aufgaben nur, wenn es welche gibt:** Der mitgelieferte Systemprompt sagt
  jetzt ausdrücklich, dass Forderungen, Meinungen und Vorschläge keine
  Aufgaben sind und die Liste bei Vorträgen, Diskussionen oder Interviews leer
  bleibt. Vorher dachte sich das Modell bei einer Podiumsdiskussion zehn
  „Aufgaben“ aus. Termine, offene Fragen und Fakten verlangt er als Text.

### Fixed

- **USB-Einrichtung fand kein Gerät („Das Paket 'pyserial' fehlt“):** Im lokalen Modus
  läuft die Anwendung in ihrer eigenen Rechenumgebung; dort fehlte `pyserial`. Bestehende
  Installationen ziehen das Paket beim nächsten Start nach. Ein Test prüft jetzt, dass jedes
  Paket der Anwendung auch in dieser Umgebung steht (zuvor schon bei `sounddevice` und
  `keyring` passiert).
- **Empfang: Stand nach einem Verbindungsabbruch stimmt:** Fragte ein Aufnahmegerät
  nach einem Abbruch mitten in einem Stück schon nach, während die Software noch auf
  den Rest dieses Stücks wartete, zählte der gemeldete Stand den halben Rest mit. Das
  Gerät setzte dort an und musste nach einer Ablehnung (409) zurück. Gemeldet wird
  jetzt nur noch, was vollständig angekommen ist.
- **Kein schwarzes Konsolenfenster mehr:** Im lokalen Modus stand neben der
  Oberfläche dauerhaft ein schwarzes Fenster offen – wer es schloss, beendete
  das ganze Programm. Die Oberfläche und alle Hilfsprogramme (ffmpeg,
  Sprechertrennung, Einrichtung, Modell-Download, Hardwareprüfung) starten
  jetzt unsichtbar. Schlägt `ollama pull` fehl, steht der Grund in der Meldung
  statt nur „fehlgeschlagen“. Wer die Anwendung aus einem Terminal startet,
  sieht die Ausgabe dort weiterhin.

- **Aufnahmegeräte: Antworten kommen sicher an.** Lehnte der Empfang eine
  Anfrage ab, ohne ihren Inhalt zu lesen (z. B. falsches Token), konnte das
  Gerät statt der Antwort nur „Verbindung zurückgesetzt“ sehen. Der Empfang
  schließt die Verbindung jetzt sanft (wie Webserver es tun), begrenzt in Zeit
  und Menge. Aufgefallen durch einen gelegentlich fehlschlagenden Test.

- **„CUDA out of memory“ bei der zweiten Transkription hintereinander:** Hielt
  Ollama noch das Sprachmodell der vorigen Auswertung (standardmäßig fünf
  Minuten), scheiterte Whisper auf Grafikkarten mit 8 GB. Die Prüfung, ob noch
  Platz ist, verließ sich auf den freien Speicher, den torch meldet – unter
  Windows ist der zu hoch (gemessen: 6,9 GB „frei“ bei 5,6 GB, die Ollama
  belegte), also wurde nie entladen. Jetzt zählt, was nach Abzug der
  Ollama-Modelle von der Karte bleibt; reicht es nicht für Whisper, nimmt
  Ollama das Modell heraus und lädt es für das Protokoll neu. Auf großen Karten
  bleibt das Modell geladen.

- Zwischenergebnisse der Nachbearbeitung werden je Systemprompt gespeichert.
  Zuvor galten sie nur je Transkript: Wer denselben Text mit einem anderen
  Systemprompt erneut auswertete, bekam das gespeicherte Ergebnis zum alten
  Auftrag zurück.
- Die Zwischenergebnisse gelten außerdem **je Modell**: Wer das Ollama- oder
  API-Modell wechselt, bekommt ein neues Ergebnis statt der gespeicherten
  Teilergebnisse des alten Modells.
- **Abgeschnittene Antworten werden erkannt:** Hört das Modell an der
  Längen- oder Kontextgrenze mitten im Text auf, meldet die Nachbearbeitung
  das als Fehler, statt den halben Text als Protokoll auszugeben oder als
  Zwischenergebnis zu speichern. „Frag mein Meeting“ ist davon nicht betroffen.
- **Lange Aufnahmen:** Beim Zusammenführen der Teilergebnisse bekommt das
  Modell nie mehr Text, als in seinen Kontext passt. Lässt sich ein Ergebnis
  nicht weiter verdichten, endet die Nachbearbeitung mit einer klaren Meldung,
  statt eine zu lange Anfrage zu schicken.
- **Filternde Aufträge („nur ToDos“):** Ein Abschnitt ohne passenden Inhalt
  bricht die Nachbearbeitung nicht mehr ab, er wird einfach übersprungen. Nur
  wenn kein einziger Abschnitt etwas liefert, gibt es eine Meldung.
- **Nach dem Update kein JSON mehr im Protokoll:** Wer den früher
  mitgelieferten Systemprompt (feste JSON-Struktur) nie verändert hat, bekommt
  beim Start den neuen Standard. Ein selbst bearbeiteter Prompt bleibt, wie er
  ist.
- Unvollständige Denkblöcke (`<think>` ohne Ende oder ein verwaistes
  `</think>`) landen nicht mehr im Protokoll.
- Ohne Systemprompt und bei langen Aufnahmen wissen die späteren Stufen jetzt,
  dass sie Teilergebnisse statt des Transkripts vor sich haben.

- **„Danach direkt das Protokoll erstellen“ wirkte nicht:** Nach der
  Transkription blieb das Fenster bei „Transkription abgeschlossen.“ stehen,
  das Protokoll startete nie. Die Anwendung wartete auf das Ende des
  Arbeits-Threads, das zu diesem Zeitpunkt meist schon vorbei war. Gefunden vom
  neuen Oberflächentest mit echten Modellen.
- **Frag mein Meeting, „Ganzer Text“ bei langen Unterlagen:** Wird der Text in
  Abschnitten gelesen, schloss ein Abschnitt mitunter „kein Termin genannt“,
  obwohl der nächste ihn nannte, und die Antwort übernahm das. Die Notizen je
  Abschnitt sind jetzt knapp und ziehen keine Schlüsse über Fehlendes; die
  Antwort wertet alle Notizen zusammen aus.
- **Kein Systemabsturz mehr bei der Sprechertrennung:** Auf einem Laptop mit
  NVIDIA-Karte und aktiver Speicherintegrität (VBS/HVCI) stürzte beim Start der
  Sprechertrennung der ganze Rechner ab (Bluescreen HYPERVISOR_ERROR) – ein
  Treiber-/Hypervisor-Problem, ausgelöst durch pyannote auf der GPU im selben
  Prozess wie Whisper. Die Sprechertrennung läuft auf der GPU jetzt in einem
  eigenen Prozess, erst nachdem Whisper fertig und entladen ist; scheitert der
  Prozess, rechnet sie auf der CPU. `PROTOKOLL_SPRECHERTRENNUNG_GERAET=cpu`
  erzwingt die CPU.
- **Grafikspeicher wird geteilt statt überbucht:** Reicht der freie
  Grafikspeicher vor der Transkription nicht für Whisper, entlädt Ollama zuerst
  seine Modelle und lädt das Sprachmodell für das Protokoll danach wieder. Ist
  genug frei, bleibt alles geladen.
- **Lokale Protokolle aus vollständigem Text:** Die Nachbearbeitung über
  Ollama lief mit dessen Standard-Kontext von 4096 Tokens. Ein
  10-Minuten-Abschnitt samt Anweisung passt da oft nicht hinein; Ollama hat
  dann still den Anfang des Transkripts verworfen, und bei längeren
  Protokollen brach die Antwort mitten im JSON ab („Pflichtfeld fehlt“ bzw.
  „es fehlt jedes inhaltliche Feld“). Jetzt wählt die Anwendung die Größe je
  Aufruf: 16.384 Tokens für die Abschnitte, 32.768 für das Gesamtprotokoll.
  So bleibt das Modell auch auf kleinen Grafikkarten (6 GB) für die meisten
  Schritte ganz im Grafikspeicher. Gefunden durch die neuen Ende-zu-Ende-Tests.
- **Protokoll ohne Rohdaten:** Lieferte das Modell offene Fragen, Fakten oder
  Termine als Objekte statt als Text, standen sie mit geschweiften Klammern
  im Protokoll (Markdown, Word, PDF). Jetzt erscheinen sie als Satz mit den
  übrigen Angaben in Klammern.
- Ein gescheiterter FFmpeg-Download (kein Netz, Proxy, beschädigtes Paket)
  wurde in der Einrichtung nur still ins Protokoll geschrieben und die
  Einrichtung meldete trotzdem „abgeschlossen“. Jetzt wird die Lücke
  benannt (FFmpeg, Ollama, pyannote, Ollama-Modell).
- Ollama wurde direkt nach der Installation nicht gefunden, weil der neue
  PATH erst für neu gestartete Programme gilt. Die üblichen
  Installationsorte unter Windows werden jetzt mit durchsucht.

### Security

- Abhängigkeiten mit bekannten Lücken angehoben: certifi 2026.10.23
  (PYSEC-2026-4320, steckt über requests in der ausgelieferten EXE),
  setuptools 84.2.1 (GHSA-xmj3-9gf7-h52w) und filelock 4.2.4 (sechs
  Meldungen, nur Entwicklungswerkzeug pip-audit). Für Python 3.10 gibt es
  keine bereinigte filelock-Version – sie verlangt 3.11; dort bleibt 4.1.0
  stehen, betrifft aber nur die Entwicklungsumgebung. Die tägliche
  Schwachstellenprüfung war deshalb seit dem 21.10. rot.

### Added

- Ollama-Modell wählbar: In den Einstellungen (Nachbearbeitung, lokal) gibt es
  jetzt eine Auswahl mit Qwen3 (4B, 8B, 14B), Gemma 3, Llama 3.1 und Mistral
  Nemo samt Größenangabe und Hinweis, dazu „Eigenen Modellnamen eingeben …“
  für jedes Modell aus der Ollama-Bibliothek. Der Status zeigt, ob das Modell
  installiert ist; „Jetzt herunterladen“ lädt es mit Fortschrittsanzeige
  nach. Vorausgewählt bleibt Qwen3 8B. Die lokale Ersteinrichtung lädt das
  hier eingestellte Modell, die Systemdiagnose prüft es, und die
  Nachbearbeitung meldet ein fehlendes Modell vor dem Start verständlich.

### Changed

- Seite „Transkription“ ohne Bildlauf: Links stehen Aufnahme und Datei, rechts
  die Einstellungen für den Lauf, das Fortsetzen und der Start. Aufnahmeknöpfe,
  Status und Pegel sitzen in einer Zeile, die Begrenzung der Sprecherzahl in
  einer Zeile, Erklärungen sind als Tooltips hinterlegt.

### Fixed

- Beim Speichern der Einstellungen erschien im lokalen Modus die Meldung, dass
  `keyring` fehlt, auch wenn der Anwender keinen Schlüssel merken wollte. Die
  Meldung kommt jetzt nur noch, wenn ein Schlüssel wirklich dauerhaft
  gespeichert werden soll. Zusätzlich installiert die selbst eingerichtete
  Laufzeitumgebung `keyring` jetzt mit, sodass das Merken dort funktioniert
  (beim nächsten Start einmalig mit Internetverbindung).

### Added

- Sehr lange Aufnahmen: Die Verdichtung der Teilanalysen (Stufe 2) läuft
  jetzt in mehreren Runden, bis das Ergebnis in den Kontext der
  Gesamtprotokoll-Stufe passt (höchstens 8 Runden). Vorher gab es genau eine
  Runde, und bei sehr langen Aufnahmen konnte das Kontextfenster des Modells
  überlaufen. Zwischenstände je Runde bleiben fortsetzbar.

- Sprecher anhören und exportieren: In der Sprechertabelle gibt es je
  Sprecher „▶ Anhören“ (kurze Hörprobe) und „Exportieren …“ (Audio als WAV
  und Text als TXT nur dieses Sprechers). Dafür speichert das JSON jetzt
  die Sprecherabschnitte (`sprecher_turns`) und den Pfad der aufbereiteten
  Audiodatei (`audio_pfad`). Transkripte aus älteren Versionen enthalten
  beides nicht; dort weist die Anwendung darauf hin, neu zu transkribieren.

- Dauerhafte Sprecherprofile (nur lokaler Modus): Stimmen lassen sich in der
  Sprechertabelle mit „Als Profil speichern“ merken, nach ausdrücklicher
  Bestätigung. In späteren Aufnahmen schlägt die Anwendung den Namen vor
  (mit Fragezeichen bei knapper Ähnlichkeit) und übernimmt ihn nur auf
  Klick. „Sprecherprofile verwalten …“ zeigt, benennt um und löscht Profile.
  Die Stimmabdrücke (biometrische Daten) liegen nur lokal im Ordner
  `sprecherprofile/`, der nicht versioniert und nicht in den Installer
  aufgenommen wird. Die Ähnlichkeitsschwelle (0,72) ist noch nicht an
  echten Aufnahmen abgestimmt.

- Fünf neue Protokollvorlagen mit festen Abschnitten und Erfindungsverbot:
  Formelles Protokoll, Projektbesprechung, Stand-up, Technische Besprechung
  und Interview. Sie legen fest, was in welches Feld des Protokolls gehört
  (z. B. Tagesordnungspunkte, Beschlüsse, Aufgaben mit Verantwortlichen und
  Fristen).

- Neue Dialoge: „Neue Transkription …“ fragt die Audioquelle ab (Mikrofon
  mit Geräteliste oder Mediendatei); vor „Transkription starten“ fragt
  „Verarbeitung wählen“ nach Sprechererkennung (automatisch oder bekannte
  Anzahl) und ob danach direkt das Protokoll mit einer Vorlage erstellt wird.

### Fixed

- Aufnahmegerät-Auswahl: Der Pfeil des Auswahlfelds öffnete bei leerer Liste
  nichts und sagte nicht, warum. Jetzt steht ein Platzhalter „Kein
  Aufnahmegerät verfügbar“ darin, der Grund steht darunter, und „Neu einlesen“
  liest die Geräte neu ein (z. B. nach dem Anstecken eines Headsets). Auswahllisten
  klappen unter dem Feld auf. Die gebaute EXE bündelt jetzt ausdrücklich
  `sounddevice` samt PortAudio-Bibliothek, und die selbst eingerichtete
  Laufzeitumgebung des lokalen Modus installiert es mit. Dort fehlte es, deshalb
  blieb die Geräteliste im lokalen Modus leer, auch bei angeschlossenem Gerät.
  Beim nächsten Start richtet sich die Umgebung einmalig neu ein (Internet nötig).
- Wer die Vorlage wechselte und die Nachbearbeitung erneut startete, bekam
  stillschweigend das fertige Protokoll der alten Vorlage zurück. Das
  Gesamtprotokoll wird jetzt neu erzeugt, sobald sich der Systemprompt
  ändert; Teilanalysen (Stufe 1 und 2) bleiben erhalten. Ein vorhandenes
  Protokoll aus einer älteren Version wird dabei einmal neu erzeugt.
- Die JSON-Struktur des Protokolls stand nur im mitgelieferten
  Standard-Systemprompt. Jede Vorlage und jeder freie Text ersetzt ihn
  vollständig - die letzte Stufe kannte die Struktur dann nicht. Sie wird
  jetzt in der Anfrage der letzten Stufe selbst mitgegeben.

### Changed

- Erscheinungsbild VERMERK: Das große Logo (Fassung für dunklen Grund) steht
  oben in der Seitenleiste, die Bildmarke ist Programmsymbol für Fenster,
  Dialoge, die EXE und den Installer. Die Dateien liegen in
  `protokoll_assistent/resources/` und entstehen mit
  `python -m protokoll_assistent.tools.logo_erzeugen` aus der EPS-Vorlage.
- Neues Hauptfenster mit Seitenleiste: Links stehen „Neue Transkription“, die
  Seiten **Transkription**, **Nachbearbeitung** und **Ergebnis und Sprecher**
  sowie unten „Ausgabeordner öffnen“ und „Einstellungen“. Die sieben
  Bereiche der alten linken Spalte sind auf diese Seiten verteilt; der
  Fortschritt steht kompakt unter jeder Seite. Schaltflächen sind überall
  gleich hoch und gleich gerundet (blau = Hauptaktion, weiß = Nebenaktion,
  rot = Abbrechen). Nach einer fertigen Transkription öffnet sich die Seite
  „Ergebnis und Sprecher“ von selbst.
- Oberfläche näher an moderne Arbeitsflächen gerückt: Titelzeile mit
  Untertitel, größere Rundungen, blauer Akzent, „Starten“-Schaltflächen
  hervorgehoben und „Abbrechen“/„Aufnahme beenden“ rot.
- Sprecherzuordnung wortgenau: Wechselt der Sprecher mitten in einem
  Segment, wird das Segment an dieser Stelle geteilt. Vorher ging das ganze
  Segment an den Sprecher mit der größten Überlappung, der Rest war falsch
  zugeordnet. Segmente ohne Wortzeitstempel (z. B. von API-Endpunkten, die
  nur Segmente liefern) werden wie bisher zugeordnet.

## [0.3.1] - 2026-09-25

### Fixed

- Der lokale Modus war in der gebauten EXE vollständig kaputt: Die
  selbsteinrichtende Laufzeitumgebung (Torch/faster-whisper/pyannote) wurde
  dort fälschlich übersprungen, in der Annahme, sie sei bereits gebündelt.
  Die erste Transkription scheiterte dadurch mit „ModuleNotFoundError: No
  module named 'torch'". Betrifft **nur** die EXE aus 0.3.0 — der reine
  API-Modus war davon nicht betroffen.
- Neu: Bei einer frischen Installation bietet die Anwendung die
  Ersteinrichtung des lokalen Modus (Systemtest, Modellempfehlung,
  Downloads) einmalig automatisch als Dialog über dem Hauptfenster an —
  lokale, private Verarbeitung bleibt damit auch ohne Blick in die
  Einstellungen leicht erreichbar.

## [0.3.0] - 2026-09-25

### Changed

- Die Anwendung zeigt beim Start immer sofort das Hauptfenster — nicht mehr
  erst den Einrichtungsassistenten davor

### Added

- Neuer Knopf „Einrichtung starten" im Einstellungen-Dialog (Reiter
  Transkription → Lokal): startet Download, Systemtest und Modellwahl gezielt,
  statt automatisch bei jedem ersten Programmstart

### Fixed

- Die Systemdiagnose zeigt jetzt live, welche Prüfung gerade läuft, statt
  während der gesamten Prüfung einen unveränderten „läuft ..."-Text
  anzuzeigen — bei einer frisch eingerichteten Laufzeitumgebung (Virenschutz
  prüft die eben geschriebenen PyTorch-/pyannote-Dateien) sah das wie ein
  Hängenbleiben aus

## [0.2.0] - 2026-09-22

Aus drei Anwendungen wird eine. Ob Transkription und Nachbearbeitung lokal
oder über eine Schnittstelle laufen, ist ab sofort eine **Einstellung** im
Programm — kein eigenes Programm, kein Auswahlfenster, keine zweite
Installation.

### Hinweise zur Umstellung

- Wer bisher die tkinter-Variante („Schnittstelle nutzen") verwendet hat,
  arbeitet künftig mit derselben Anwendung wie alle anderen und trägt
  Endpunkt und Schlüssel dort einmalig neu ein. **Bestehende Einstellungen
  werden nicht übernommen.**
- Gestartet wird über den Startmenü-Eintrag, `Start-Protokoll-Assistent.ps1`
  oder `python -m protokoll_assistent.app`. Ein Start über den reinen
  Dateipfad funktioniert nicht mehr.
- Die Anwendung liegt jetzt in `protokoll_assistent/` statt in
  `lokale_windows_app/`. Wer aus dem Quellcode installiert, passt seine
  Verknüpfungen entsprechend an.

### Added

- Systemprompt-Vorlagen lassen sich benannt speichern und im Hauptfenster
  auswählen
- API-Schlüssel können auf Wunsch dauerhaft in der
  Windows-Anmeldeinformationsverwaltung hinterlegt werden; ohne diese
  Zustimmung gelten sie nur für die laufende Sitzung
- Offline-Schalter im Hauptfenster: einmal abwählen, damit ein noch nicht
  eingerichtetes Whisper-Modell heruntergeladen werden darf

### Changed

- Transkription und Nachbearbeitung sind je einzeln auf „lokal" oder
  „Schnittstelle" umschaltbar — auch gemischt
- Alle Einstellungen stehen in **einer** `konfiguration.json`; vorher hatte
  jede Anwendung ihre eigene
- Der Systemprompt eines Laufs wird direkt an die Auswertung übergeben und
  überschreibt nicht mehr den gespeicherten Systemprompt
- Die Protokolldatei heißt `logs/protokoll_assistent.log`

### Removed

- Die tkinter-Variante samt Auswahlfenster, Konsolenversion und
  Einrichtungsfenster. Ihr Weg über eine Schnittstelle lebt als Einstellung
  weiter
- Die Fachbegriffsliste (`einstellungen/fachbegriffe.txt`); sie gab es nur in
  der tkinter-Variante

### Fixed

- Fehler des API-Modells (HTTP 401, nicht erreichbarer Endpunkt, Zeitlimit)
  werden als Protokollfehler gemeldet, statt als „Unerwarteter Fehler" zu
  erscheinen; Transkript und Bericht bleiben erhalten
- Eine Vorlage mit Zeichen, die Windows in Dateinamen verbietet („Wer macht
  was?"), wird mit einer verständlichen Meldung abgelehnt statt mit einem
  Absturz
- Das Speichern des Verarbeitungsstands wird wiederholt, wenn Windows die
  Datei kurzzeitig sperrt (Virenscanner) — vorher riss das ganze
  Verarbeitungsläufe ab
- Die Systemdiagnose prüft Platz und Schreibbarkeit des Ausgabeordners statt
  des Anwendungsordners
- Das im Einrichtungsassistenten gewählte Whisper-Modell gilt auch
  tatsächlich für die Transkription
- Die Anwendung startet auch dann, wenn `keyring` oder `sounddevice` in der
  Laufzeitumgebung fehlen; betroffen ist dann nur die jeweilige Zusatzfunktion

## [0.1.0] - 2026-09-21

### Added

- Erste Veröffentlichung: Transkription mit Sprechertrennung und
  anschließende Protokollauswertung, als vollständig lokale
  Windows-Anwendung und als Variante über eine Schnittstelle
- Installer für Windows (ohne Administratorrechte, mit mitgelieferter
  Python-Laufzeitumgebung)

[Unreleased]: https://github.com/Blickfeld-KevinLemaire/lokaler-protokoll-assistent/compare/v0.3.1...HEAD
[0.3.1]: https://github.com/Blickfeld-KevinLemaire/lokaler-protokoll-assistent/compare/v0.3.0...v0.3.1
[0.3.0]: https://github.com/Blickfeld-KevinLemaire/lokaler-protokoll-assistent/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/Blickfeld-KevinLemaire/lokaler-protokoll-assistent/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/Blickfeld-KevinLemaire/lokaler-protokoll-assistent/releases/tag/v0.1.0
