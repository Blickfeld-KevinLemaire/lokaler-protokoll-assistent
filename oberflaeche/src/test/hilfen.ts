/** Hilfen für Tests: Antworten mit Strom-Körper, JSON-Antworten. */

export function stromAntwort(stuecke: string[], status = 200, offenLassen = false): Response {
  const kodierer = new TextEncoder();
  const koerper = new ReadableStream<Uint8Array>({
    start(steuerung) {
      for (const s of stuecke) steuerung.enqueue(kodierer.encode(s));
      if (!offenLassen) steuerung.close();
    }
  });
  return new Response(koerper, { status, headers: { 'Content-Type': 'text/event-stream' } });
}

export function jsonAntwort(daten: unknown, status = 200): Response {
  return new Response(JSON.stringify(daten), { status, headers: { 'Content-Type': 'application/json' } });
}

export const INFO = {
  version: '0.6.0',
  rolle: 'desktop',
  angemeldet_als: 'desktop',
  anzeigename: 'desktop',
  admin: true,
  mehrbenutzer: false,
  faehigkeiten: {
    lokale_transkription: true,
    mikrofon: true,
    dateipfade: true,
    ordner_oeffnen: true,
    geraete_empfang: true
  },
  einrichtung_abgeschlossen: true,
  ausgabeordner: 'C:/Ausgabe'
};
