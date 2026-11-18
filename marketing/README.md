# VERMERK – Material für Präsentation und Social Media

Alles hier wird aus HTML-Vorlagen in `quelle/` erzeugt (Farben und Logo wie in der App).
Die Inhalte (Besprechung „Relaunch Website“, Anna/Murat/Sabine) sind **erfunden**. Die
App-Ansichten sind **nachgebaute Mockups** im Stil von VERMERK Desktop, keine echten Screenshots.

## Was es gibt

| Datei | Format | Wofür |
|---|---|---|
| `videos/vermerk_protokoll_reel_9x16.mp4` | 1080×1920, 16,5 s | Instagram/Facebook Reels, LinkedIn-Video hochkant, Stories |
| `videos/vermerk_protokoll_feed_1x1.mp4` | 1080×1080 | Feed-Video LinkedIn/Facebook/Instagram |
| `videos/vermerk_protokoll_16x9.mp4` | 1920×1080 | Präsentation, Website, YouTube |
| `videos/vermerk_datenschutz_*.mp4` | 9:16 und 1:1, 11,5 s | Thema „bleibt auf Ihrem PC“ |
| `videos/vermerk_raum_*.mp4` | 9:16 und 1:1, 13 s | Aufnahmegerät VERMERK Raum |
| `bilder/posts/` | 1:1, 4:5, 9:16, LinkedIn quer (1200×627) | Einzelbeiträge |
| `bilder/karussell/vermerk_linkedin_karussell.pdf` | 8 Seiten 4:5 | LinkedIn-Dokumentbeitrag (PDF hochladen = Wisch-Karussell) |
| `bilder/karussell/karussell_*.png` | 8 Bilder 4:5 | Instagram/Facebook-Karussell |
| `praesentation/vermerk_praesentation.pdf` + `folie_*.png` | 16:9, 8 Folien | Produktpräsentation |

Die Videos haben eine **stille Tonspur**: Musik bitte direkt in Instagram/LinkedIn/CapCut
aus der lizenzierten Bibliothek der Plattform darunterlegen.

## Neu erzeugen / anpassen

Texte stehen in `quelle/film.html` (Videos), `quelle/bilder.html` (Bilder/Folien) und
`quelle/bausteine.js` (Beispielbesprechung, App-Mockups).

```bash
cd marketing/quelle
node bilder.js                                                  # alle Bilder und Folien
node rendern.js film protokoll story ../videos/test.mp4         # ein Video (story|square|wide)
node rendern.js probe protokoll story 2,5,9 /tmp/probe          # Einzelbilder zum Prüfen
```

Braucht Node mit Playwright (Chromium) und ffmpeg.

Die PNG-Dateien (Posts, Karussell- und Folienbilder) sind **nicht versioniert** – sie sind groß und
lassen sich mit `node bilder.js` jederzeit neu erzeugen. Videos und PDFs liegen im Repository.

## Beitragstexte (Vorschläge)

### LinkedIn – Reel/Video „Protokoll“
> 60 Minuten Besprechung – und danach noch 30 Minuten Protokoll schreiben?
>
> Mit VERMERK geht das so:
> 1️⃣ Besprechung aufnehmen oder Datei hineinziehen
> 2️⃣ Transkript mit automatischer Sprechertrennung
> 3️⃣ Fertiges Protokoll mit Aufgaben – als Word-Datei
>
> Und das Beste: Im lokalen Modus läuft alles auf Ihrem Windows-PC. Kein Upload, keine Cloud.
>
> #Protokoll #KI #Datenschutz #Meetings #Produktivität #Transkription #LokaleKI

### LinkedIn – Karussell (PDF)
> Schluss mit Protokoll-Schreiben. 👉 In 8 Folien: wie aus einer Besprechung ein fertiges Protokoll wird – ohne dass ein Wort Ihren Rechner verlässt.
>
> #KI #Datenschutz #NewWork #Meetings #Protokoll

### Instagram / Facebook – Reel „Datenschutz“
> Vertrauliche Besprechung? Dann bleibt sie auf Ihrem Rechner. 🔒
> VERMERK transkribiert und schreibt Protokolle lokal – auf Wunsch komplett offline.
> #datenschutz #ki #meetings #büro #produktivität #lokaleki

### Instagram / Facebook – Reel „VERMERK Raum“
> Gerät auf den Tisch. Protokoll auf den PC. 🎙️➡️📝
> VERMERK Raum nimmt im Besprechungsraum auf und überträgt per WLAN – transkribiert wird schon während der Besprechung.
> #meetingroom #ki #protokoll #hardware #büroalltag

## Bitte vor dem Veröffentlichen prüfen

- **Aussagen:** „100 % lokal“ gilt für den lokalen Modus. Wer per API arbeitet, überträgt
  Audio bzw. Transkript an den eingestellten Anbieter – die Texte sagen deshalb „im lokalen Modus“
  bzw. „auf Wunsch“.
- **Anbieternamen** (IONOS, STACKIT, Mistral) sind fremde Marken. Sie stehen nur als Beispiel für
  wählbare Anbieter; ggf. weglassen.
- **Live-Übertragung** kann derzeit nur VERMERK Raum mit Bildschirm (ESP32-S3 LCD).
- Ein **Link/Call-to-Action** (Website, Kontakt) fehlt noch und gehört in den Beitragstext oder auf die letzte Folie.
