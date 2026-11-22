/**
 * Server-Sent Events lesen – ohne EventSource (das kann keine Authorization-Kopfzeile setzen).
 * Der Parser bekommt beliebig zerschnittene Textstücke und liefert vollständige Nachrichten.
 */

export interface SseNachricht {
  /** Wert der letzten `id:`-Zeile (gilt laut Standard auch für folgende Nachrichten ohne eigene id). */
  id: string | null;
  event: string;
  data: string;
}

export class SseParser {
  private puffer = '';
  private ereignis = '';
  private daten: string[] = [];
  private hatDaten = false;
  private letzteId: string | null = null;

  constructor(private readonly ausgabe: (nachricht: SseNachricht) => void) {}

  get id(): string | null {
    return this.letzteId;
  }

  /** Ein Stück Text, wie es aus dem Strom kommt (auch mitten in einer Zeile oder einem Zeichen geteilt). */
  hinzufuegen(stueck: string): void {
    this.puffer += stueck;
    let ende: number;
    while ((ende = this.zeilenende()) >= 0) {
      const zeile = this.puffer.slice(0, ende);
      const laenge = this.puffer[ende] === '\r' && this.puffer[ende + 1] === '\n' ? 2 : 1;
      this.puffer = this.puffer.slice(ende + laenge);
      this.zeile(zeile);
    }
  }

  /** Strom zu Ende: Eine nicht abgeschlossene Nachricht wird laut Standard verworfen. */
  beenden(): void {
    this.puffer = '';
    this.zuruecksetzen();
  }

  private zeilenende(): number {
    for (let i = 0; i < this.puffer.length; i++) {
      const zeichen = this.puffer[i];
      if (zeichen === '\n') return i;
      if (zeichen === '\r') {
        // Ein \r am Ende des Puffers kann der erste Teil von \r\n sein: auf das nächste Stück warten.
        if (i === this.puffer.length - 1) return -1;
        return i;
      }
    }
    return -1;
  }

  private zeile(zeile: string): void {
    if (zeile === '') {
      this.absenden();
      return;
    }
    if (zeile.startsWith(':')) return; // Kommentar (Herzschlag)
    const doppelpunkt = zeile.indexOf(':');
    const feld = doppelpunkt < 0 ? zeile : zeile.slice(0, doppelpunkt);
    let wert = doppelpunkt < 0 ? '' : zeile.slice(doppelpunkt + 1);
    if (wert.startsWith(' ')) wert = wert.slice(1);
    switch (feld) {
      case 'event':
        this.ereignis = wert;
        break;
      case 'data':
        this.daten.push(wert);
        this.hatDaten = true;
        break;
      case 'id':
        if (!wert.includes('\0')) this.letzteId = wert;
        break;
      default:
        break; // retry und Unbekanntes: ignorieren
    }
  }

  private absenden(): void {
    if (this.hatDaten) {
      this.ausgabe({ id: this.letzteId, event: this.ereignis || 'message', data: this.daten.join('\n') });
    }
    this.zuruecksetzen();
  }

  private zuruecksetzen(): void {
    this.ereignis = '';
    this.daten = [];
    this.hatDaten = false;
  }
}

/** Liest einen Antwortkörper bis zum Ende und reicht jede Nachricht weiter. */
export async function stromLesen(
  koerper: ReadableStream<Uint8Array>,
  nachricht: (n: SseNachricht) => void,
  signal?: AbortSignal
): Promise<string | null> {
  const parser = new SseParser(nachricht);
  const leser = koerper.getReader();
  const dekodierer = new TextDecoder('utf-8');
  const abbrechen = () => void leser.cancel().catch(() => undefined);
  signal?.addEventListener('abort', abbrechen, { once: true });
  try {
    for (;;) {
      const { done, value } = await leser.read();
      if (done) break;
      if (signal?.aborted) break;
      parser.hinzufuegen(dekodierer.decode(value, { stream: true }));
    }
    parser.hinzufuegen(dekodierer.decode());
  } finally {
    signal?.removeEventListener('abort', abbrechen);
    parser.beenden();
    try {
      leser.releaseLock();
    } catch {
      // schon freigegeben oder abgebrochen
    }
  }
  return parser.id;
}
