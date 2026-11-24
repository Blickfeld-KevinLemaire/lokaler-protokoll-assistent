# Oberfläche (SvelteKit)

Die Oberfläche von VERMERK – dieselbe im Tauri-Fenster und im Browser („Im Netz anbieten“,
Servermodus). Statisch gebaut nach `build/`; der Dienst liefert sie aus, das Fenster bündelt sie.

```powershell
npm ci
npm run dev          # Entwicklungsserver auf http://localhost:5173
npm run check        # Typen (svelte-check)
npm run lint         # prettier + eslint
npm test             # vitest
npm run build        # nach build/
npm run api:typen    # src/lib/api/schema.d.ts aus openapi.json neu erzeugen
```

## Gegen einen laufenden Dienst entwickeln

Sind `VERMERK_DIENST_URL` und `VERMERK_API_SCHLUESSEL` gesetzt (Umgebung oder `.env`, Vorlage
`.env.beispiel`), leitet der Entwicklungsserver `/api` an den Dienst weiter und setzt den Schlüssel
dort selbst ein. Der Schlüssel landet nie im Bündel; die Seite verhält sich wie im Browser.

```powershell
$env:VERMERK_DIENST_URL = "http://127.0.0.1:8780"
$env:VERMERK_API_SCHLUESSEL = "<Schlüssel aus api_zugang.json>"
npm run dev
```

## Bildschirmfotos

`npm run build`, einmalig `npx playwright install chromium`, dann `npm run bildschirmfotos`. Ein
nachgebauter Dienst (`bildschirmfotos/attrappe.mjs`) liefert erfundene Daten; die Bilder (hell und
dunkel, 1360×860, einige zusätzlich 1100 px breit als `schmal-*`) landen in `screenshots/` (nicht
eingecheckt). `npm run bildschirmfotos einricht` nimmt nur die Bilder auf, deren Name „einricht“ enthält.

Szenarien der Attrappe (`/__szenario?name=…`): `reihe`, `leer`, `laufend`, `fehler`, `anmelden`,
`anmelden-mehr`, `nutzer`, `admin`, `aufnahme` und für die Ersteinrichtung `einrichtung`,
`einrichtung-nichts`, `neustart`, `mitschrift`, `fehler-einrichtung`.

## Symbole und Kürzel

Ein Symbolsatz: `@lucide/svelte` (ISC), je Symbol einzeln importiert; Größe und Linienstärke setzt
`+layout.svelte` für alle (`setLucideProps`). Tastenkürzel stehen in `src/lib/logik/tasten.ts`
(Strg+N, Strg+„,“, „/“; Esc schließt Dialoge und Blasen).

## Regeln

Siehe `ARCHITEKTUR.md`: ein Startgatter (`src/lib/start/gatter.ts`), alle Anfragen über
`src/lib/api/client.ts`, Ereignisse per `fetch` + Strom (`src/lib/api/ereignisstrom.ts`), keine
Fachbegriffe in der Oberfläche.
