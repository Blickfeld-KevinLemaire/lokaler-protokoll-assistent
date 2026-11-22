/**
 * Bildschirmfotos für die Durchsicht (hell und dunkel) gegen den nachgebauten Dienst.
 * Vorher: `npm run build` und einmalig `npx playwright install chromium`.
 *
 *   npm run bildschirmfotos   → screenshots/*.png
 */
import { mkdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { chromium } from 'playwright';
import { starten } from './attrappe.mjs';

const PORT = 4319;
const BASIS = `http://127.0.0.1:${PORT}`;
const ZIEL = fileURLToPath(new URL('../screenshots/', import.meta.url));
mkdirSync(ZIEL, { recursive: true });

/** Spielt das Tauri-Fenster nach: `zugang` liefert Adresse und Schlüssel, Ereignisse werden angenommen. */
const TAURI_NACHBAU = `
  (() => {
    let nr = 0;
    const rueckrufe = {};
    window.__TAURI_INTERNALS__ = {
      metadata: { currentWindow: { label: 'main' }, currentWebview: { label: 'main', windowLabel: 'main' } },
      transformCallback(cb) { const id = ++nr; rueckrufe[id] = cb; return id; },
      unregisterCallback(id) { delete rueckrufe[id]; },
      convertFileSrc(p) { return p; },
      async invoke(cmd, args) {
        if (cmd === 'zugang') return { basis_url: location.origin, schluessel: 'bildschirmfoto' };
        if (cmd === 'plugin:event|listen') return ++nr;
        return null;
      }
    };
    window.__TAURI_EVENT_PLUGIN_INTERNALS__ = { unregisterListener() {} };
  })();
`;

async function szenario(name) {
  await fetch(`${BASIS}/__szenario?name=${name}`);
}

const AUFNAHMEN = [
  { name: '01-transkription', szenario: 'reihe', pfad: '/' },
  { name: '02-status-bereit', szenario: 'leer', pfad: '/' },
  { name: '03-status-laeuft', szenario: 'laufend', pfad: '/' },
  {
    name: '04-status-warteschlange',
    szenario: 'reihe',
    pfad: '/',
    tun: async (s) => s.getByRole('button', { name: /2 warten/ }).click()
  },
  { name: '05-besprechungen', szenario: 'reihe', pfad: '/besprechungen' },
  { name: '06-besprechung-transkript', szenario: 'reihe', pfad: '/besprechungen?id=b1' },
  { name: '07-besprechung-sprecher', szenario: 'reihe', pfad: '/besprechungen?id=b1&reiter=sprecher' },
  { name: '08-besprechung-zusammenfassung', szenario: 'reihe', pfad: '/besprechungen?id=b1&reiter=zusammenfassung' },
  {
    name: '09-zusammenfassung-bearbeiten',
    szenario: 'reihe',
    pfad: '/besprechungen?id=b1&reiter=zusammenfassung',
    tun: async (s) => s.getByRole('button', { name: /Bearbeiten/ }).click()
  },
  { name: '10-besprechung-dateien', szenario: 'reihe', pfad: '/besprechungen?id=b1&reiter=dateien' },
  {
    name: '11-export',
    szenario: 'reihe',
    pfad: '/besprechungen?id=b1',
    tun: async (s) => s.getByRole('button', { name: 'Exportieren' }).click()
  },
  {
    name: '12-frag-mein-meeting',
    szenario: 'reihe',
    pfad: '/chat',
    tun: async (s) => s.getByRole('button', { name: /Wer kümmert sich/ }).click()
  },
  { name: '13-raum', szenario: 'reihe', pfad: '/raum' },
  { name: '14-einstellungen', szenario: 'reihe', pfad: '/einstellungen' },
  { name: '15-einstellungen-zusammenfassung', szenario: 'reihe', pfad: '/einstellungen#zusammenfassung' },
  {
    name: '16-info-erklaerung',
    szenario: 'leer',
    pfad: '/',
    tun: async (s) => s.getByRole('button', { name: 'Was bedeutet Sprecher erkennen?' }).hover()
  },
  {
    name: '17-fehlerdialog',
    szenario: 'fehler',
    pfad: '/',
    tun: async (s) => {
      await s.getByRole('button', { name: /Teamrunde/ }).click();
      await s.getByRole('button', { name: 'Transkription starten' }).click();
    }
  },
  { name: '18-anmeldung', szenario: 'anmelden', pfad: '/', browser: true },
  { name: '19-nutzer-besprechungen', szenario: 'nutzer', pfad: '/besprechungen', browser: true },
  { name: '20-nutzer-geteilt', szenario: 'nutzer', pfad: '/besprechungen?id=jonas~b1&reiter=zusammenfassung', browser: true },
  { name: '21-nutzer-einstellungen', szenario: 'nutzer', pfad: '/einstellungen', browser: true },
  { name: '22-admin-nutzer', szenario: 'admin', pfad: '/einstellungen#nutzer', browser: true },
  {
    name: '23-admin-teilen',
    szenario: 'admin',
    pfad: '/besprechungen?id=b4',
    browser: true,
    tun: async (s) => s.getByRole('button', { name: /Geteilt|Teilen/ }).click()
  }
];

const server = await starten(PORT);
const browser = await chromium.launch();
const nur = process.argv[2];
try {
  for (const modus of ['hell', 'dunkel']) {
    for (const a of AUFNAHMEN) {
      if (nur && !a.name.includes(nur)) continue;
      await szenario(a.szenario);
      const kontext = await browser.newContext({
        viewport: { width: 1360, height: 860 },
        colorScheme: modus === 'dunkel' ? 'dark' : 'light',
        locale: 'de-DE',
        timezoneId: 'Europe/Berlin'
      });
      if (!a.browser) await kontext.addInitScript(TAURI_NACHBAU);
      const seite = await kontext.newPage();
      seite.on('pageerror', (e) => console.error(`[${a.name}] Seitenfehler:`, e.message));
      await seite.goto(BASIS + a.pfad);
      // Der Ereignisstrom bleibt offen – auf „networkidle“ zu warten hieße ewig warten.
      await seite.waitForTimeout(1200);
      if (a.tun) {
        await a.tun(seite);
        await seite.waitForTimeout(500);
      }
      await seite.screenshot({ path: `${ZIEL}${a.name}-${modus}.png` });
      await kontext.close();
      console.log(`${a.name}-${modus}.png`);
    }
  }
} finally {
  await browser.close();
  server.close();
}
