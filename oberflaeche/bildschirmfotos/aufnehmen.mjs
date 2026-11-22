/**
 * Bildschirmfotos für die Durchsicht (hell und dunkel) gegen den nachgebauten Dienst.
 * Vorher: `npm run build` und einmalig `npx playwright install chromium`.
 *
 *   npm run bildschirmfotos           → screenshots/*.png (hell und dunkel, 1360×860, einige auch 1100 px)
 *   npm run bildschirmfotos einricht  → nur Aufnahmen, deren Name „einricht“ enthält
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

/** Klickt sich durch die Ersteinrichtung (nach dem Öffnen der Seite). */
async function weiter(s, anzahl = 1) {
  for (let i = 0; i < anzahl; i++) {
    await s.getByRole('button', { name: /^(Los geht’s|Weiter|Einrichten)$/ }).click();
    await s.waitForTimeout(350);
  }
}

async function szenario(name) {
  await fetch(`${BASIS}/__szenario?name=${name}`);
}

const AUFNAHMEN = [
  { name: '01-transkription', szenario: 'reihe', pfad: '/', schmal: true },
  { name: '02-status-bereit', szenario: 'leer', pfad: '/' },
  { name: '03-status-laeuft', szenario: 'laufend', pfad: '/' },
  {
    name: '04-status-warteschlange',
    szenario: 'reihe',
    pfad: '/',
    tun: async (s) => s.getByRole('button', { name: /2 warten/ }).click()
  },
  { name: '05-besprechungen', szenario: 'reihe', pfad: '/besprechungen' },
  { name: '06-besprechung-transkript', szenario: 'reihe', pfad: '/besprechungen?id=b1', schmal: true },
  { name: '07-besprechung-sprecher', szenario: 'reihe', pfad: '/besprechungen?id=b1&reiter=sprecher' },
  {
    name: '08-besprechung-zusammenfassung',
    szenario: 'reihe',
    pfad: '/besprechungen?id=b1&reiter=zusammenfassung'
  },
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
    tun: async (s) => s.getByRole('button', { name: /^Wer kümmert sich/ }).click()
  },
  { name: '13-raum', szenario: 'reihe', pfad: '/raum', schmal: true },
  { name: '14-einstellungen', szenario: 'reihe', pfad: '/einstellungen', schmal: true },
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
      await s
        .locator('.zuletzt')
        .getByRole('button', { name: /Teamrunde/ })
        .click();
      await s.getByRole('button', { name: 'Transkription starten' }).click();
    }
  },
  { name: '18-anmeldung', szenario: 'anmelden', pfad: '/', browser: true },
  { name: '19-nutzer-besprechungen', szenario: 'nutzer', pfad: '/besprechungen', browser: true },
  {
    name: '20-nutzer-geteilt',
    szenario: 'nutzer',
    pfad: '/besprechungen?id=jonas~b1&reiter=zusammenfassung',
    browser: true
  },
  { name: '21-nutzer-einstellungen', szenario: 'nutzer', pfad: '/einstellungen', browser: true },
  { name: '22-admin-nutzer', szenario: 'admin', pfad: '/einstellungen#nutzer', browser: true },
  {
    name: '23-admin-teilen',
    szenario: 'admin',
    pfad: '/besprechungen?id=b4',
    browser: true,
    tun: async (s) => s.getByRole('button', { name: /Geteilt|Teilen/ }).click()
  },
  {
    name: '24-usb-anschliessen',
    szenario: 'reihe',
    pfad: '/raum',
    tun: async (s) => s.getByRole('button', { name: /per USB verbinden/i }).click()
  },
  {
    name: '25-usb-name-wlan',
    szenario: 'reihe',
    pfad: '/raum',
    tun: async (s) => {
      await s.getByRole('button', { name: /per USB verbinden/i }).click();
      await s.waitForTimeout(400);
      await s.getByRole('button', { name: 'Weiter' }).click();
      await s.waitForTimeout(300);
      await s.getByLabel('Name des Geräts').fill('Raum-4');
    }
  },
  {
    name: '30-einrichtung-willkommen',
    szenario: 'einrichtung',
    pfad: '/',
    schmal: true
  },
  {
    name: '31-einrichtung-computer',
    szenario: 'einrichtung',
    pfad: '/',
    schmal: true,
    tun: async (s) => weiter(s, 1)
  },
  {
    name: '32-einrichtung-arbeitsweise',
    szenario: 'einrichtung',
    pfad: '/',
    tun: async (s) => weiter(s, 2)
  },
  {
    name: '33-einrichtung-was-noetig-ist',
    szenario: 'einrichtung',
    pfad: '/',
    schmal: true,
    tun: async (s) => {
      await weiter(s, 3);
      await s.getByText('Allem zustimmen').click();
    }
  },
  {
    name: '34-einrichtung-einrichten',
    szenario: 'einrichtung',
    pfad: '/',
    tun: async (s) => {
      await weiter(s, 3);
      await s.getByText('Allem zustimmen').click();
      await s.getByLabel('Zugangsschlüssel für die Sprechererkennung').fill('hf_beispiel');
      await weiter(s, 1);
    }
  },
  {
    name: '35-einrichtung-online-dienst',
    szenario: 'einrichtung',
    pfad: '/',
    tun: async (s) => {
      await weiter(s, 2);
      await s.getByRole('radiogroup', { name: 'Zusammenfassung' }).getByText('Online-Dienst').click();
      await s.getByRole('radiogroup', { name: 'Frag mein Meeting' }).getByText('Online-Dienst').click();
      await weiter(s, 2);
      await s.getByRole('combobox').first().selectOption('ionos');
    }
  },
  {
    name: '36-einrichtung-raum',
    szenario: 'einrichtung',
    pfad: '/',
    tun: async (s) => weiter(s, 4)
  },
  { name: '37-einrichtung-neu-starten', szenario: 'neustart', pfad: '/' },
  {
    name: '38-einrichtung-startet-neu',
    szenario: 'neustart',
    pfad: '/',
    tun: async (s) => s.getByRole('button', { name: 'Jetzt neu starten' }).click()
  },
  {
    name: '39-einrichtung-spracherkennung',
    szenario: 'mitschrift',
    pfad: '/',
    tun: async (s) => {
      await s.getByText('Spracherkennung', { exact: true }).last().click();
      await s.getByText('Sprechererkennung', { exact: true }).click();
    }
  },
  {
    name: '40-einrichtung-fertig',
    szenario: 'einrichtung-nichts',
    pfad: '/',
    tun: async (s) => weiter(s, 4)
  },
  {
    name: '41-fehler-einrichten',
    szenario: 'fehler-einrichtung',
    pfad: '/',
    tun: async (s) => {
      await s
        .locator('.zuletzt')
        .getByRole('button', { name: /Teamrunde/ })
        .click();
      await s.getByRole('button', { name: 'Transkription starten' }).click();
    }
  },
  { name: '42-aufnahme-laeuft', szenario: 'aufnahme', pfad: '/' },
  { name: '43-bekannte-stimmen', szenario: 'reihe', pfad: '/einstellungen#stimmen' },
  {
    name: '44-export-herunterladen',
    szenario: 'leer',
    pfad: '/besprechungen?id=b2',
    browser: true,
    tun: async (s) => {
      await s.getByRole('button', { name: 'Exportieren' }).click();
      await s.waitForTimeout(300);
      await s.getByRole('dialog').getByRole('button', { name: 'Exportieren' }).click();
    }
  },
  {
    name: '45-ablegen',
    szenario: 'leer',
    pfad: '/',
    browser: true,
    tun: async (s) =>
      s.evaluate(() => {
        const dt = new DataTransfer();
        dt.items.add(new File(['x'], 'Besprechung.m4a', { type: 'audio/mp4' }));
        window.dispatchEvent(new DragEvent('dragenter', { dataTransfer: dt, bubbles: true }));
      })
  },
  {
    name: '46-rueckgaengig',
    szenario: 'reihe',
    pfad: '/chat',
    tun: async (s) => s.getByRole('button', { name: /Offene Punkte Vertrieb.*löschen/ }).click()
  },
  { name: '47-anmeldung-mehrere-nutzer', szenario: 'anmelden-mehr', pfad: '/', browser: true },
  {
    name: '48-leer-besprechungen',
    szenario: 'leer',
    pfad: '/besprechungen',
    tun: async (s) => s.getByLabel('Transkripte suchen').fill('Gibt es nicht')
  },
  {
    name: '49-entfernen-rueckfrage',
    szenario: 'reihe',
    pfad: '/raum',
    tun: async (s) => s.getByRole('button', { name: 'Flur-EG entfernen' }).click()
  },
  {
    name: '26-usb-wird-eingerichtet',
    szenario: 'reihe',
    pfad: '/raum',
    tun: async (s) => {
      await s.getByRole('button', { name: /per USB verbinden/i }).click();
      await s.waitForTimeout(400);
      await s.getByRole('button', { name: 'Weiter' }).click();
      await s.waitForTimeout(300);
      await s.getByLabel('Name des Geräts').fill('Raum-4');
      await s.getByLabel('WLAN-Passwort').fill('geheim123');
      await s.getByRole('button', { name: 'Einrichten' }).click();
    }
  }
];

const server = await starten(PORT);
const browser = await chromium.launch();
const nur = process.argv[2];

async function aufnehmen(a, modus, breite, hoehe, datei) {
  await szenario(a.szenario);
  const kontext = await browser.newContext({
    viewport: { width: breite, height: hoehe },
    colorScheme: modus === 'dunkel' ? 'dark' : 'light',
    locale: 'de-DE',
    timezoneId: 'Europe/Berlin'
  });
  if (!a.browser) await kontext.addInitScript(TAURI_NACHBAU);
  const seite = await kontext.newPage();
  seite.on('pageerror', (e) => console.error(`[${a.name}] Seitenfehler:`, e.stack ?? e.message));
  await seite.goto(BASIS + a.pfad);
  // Der Ereignisstrom bleibt offen – auf „networkidle“ zu warten hieße ewig warten.
  await seite.waitForTimeout(1200);
  if (a.tun) {
    await a.tun(seite);
    await seite.waitForTimeout(600);
  }
  await seite.screenshot({ path: `${ZIEL}${datei}` });
  await kontext.close();
  console.log(datei);
}

try {
  for (const modus of ['hell', 'dunkel']) {
    for (const a of AUFNAHMEN) {
      if (nur && !a.name.includes(nur)) continue;
      await aufnehmen(a, modus, 1360, 860, `${a.name}-${modus}.png`);
    }
  }
  // Schmaleres Fenster: bricht nichts um, schiebt nichts aus dem Bild?
  for (const a of AUFNAHMEN) {
    if (!a.schmal || (nur && !a.name.includes(nur))) continue;
    await aufnehmen(a, 'hell', 1100, 760, `schmal-${a.name}.png`);
  }
} finally {
  await browser.close();
  server.close();
}
