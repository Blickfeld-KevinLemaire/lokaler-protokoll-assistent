/**
 * Alles, was nur im Tauri-Fenster geht. Die Tauri-Pakete werden erst bei Bedarf geladen, damit die Seite
 * im Browser (im Netz anbieten, Container) davon nichts mitbringt.
 */

export interface ZugangAusHuelle {
  basis_url: string;
  schluessel: string;
}

export type DienstZustand = 'startet' | 'bereit' | 'neustart' | 'fehlgeschlagen';

export interface DienstStatus {
  zustand: DienstZustand;
  meldung: string;
  basis_url?: string;
}

/** Was das Startgatter von der Hülle braucht – im Test ersetzbar. */
export interface Huelle {
  zugangHolen(): Promise<ZugangAusHuelle>;
  dienstStatusHoeren(rueckruf: (status: DienstStatus) => void): Promise<() => void>;
}

export const AUDIO_ENDUNGEN = [
  'mp3',
  'mp4',
  'm4a',
  'wav',
  'aac',
  'flac',
  'ogg',
  'opus',
  'mov',
  'mkv',
  'webm',
  'wma',
  'amr'
];

export function istTauri(): boolean {
  return typeof window !== 'undefined' && '__TAURI_INTERNALS__' in window;
}

export async function befehl<T>(name: string, argumente?: Record<string, unknown>): Promise<T> {
  const { invoke } = await import('@tauri-apps/api/core');
  return invoke<T>(name, argumente);
}

export function tauriHuelle(): Huelle {
  return {
    zugangHolen: () => befehl<ZugangAusHuelle>('zugang'),
    async dienstStatusHoeren(rueckruf) {
      const { listen } = await import('@tauri-apps/api/event');
      return listen<DienstStatus>('dienst-status', (e) => rueckruf(e.payload));
    }
  };
}

export async function dateiWaehlen(): Promise<string | null> {
  const { open } = await import('@tauri-apps/plugin-dialog');
  const pfad = await open({
    multiple: false,
    directory: false,
    filters: [{ name: 'Aufnahmen', extensions: AUDIO_ENDUNGEN }]
  });
  return typeof pfad === 'string' ? pfad : null;
}

export async function ordnerWaehlen(vorgabe?: string | null): Promise<string | null> {
  const { open } = await import('@tauri-apps/plugin-dialog');
  const pfad = await open({ multiple: false, directory: true, defaultPath: vorgabe ?? undefined });
  return typeof pfad === 'string' ? pfad : null;
}

/** Dateien, die auf das Fenster gezogen werden (Tauri liefert Pfade statt Dateiinhalten). */
export async function ablegenHoeren(
  ablegen: (pfade: string[]) => void,
  schweben: (aktiv: boolean) => void
): Promise<() => void> {
  const { getCurrentWebview } = await import('@tauri-apps/api/webview');
  return getCurrentWebview().onDragDropEvent((e) => {
    const p = e.payload;
    if (p.type === 'enter' || p.type === 'over') schweben(true);
    else if (p.type === 'leave') schweben(false);
    else if (p.type === 'drop') {
      schweben(false);
      ablegen(p.paths);
    }
  });
}
