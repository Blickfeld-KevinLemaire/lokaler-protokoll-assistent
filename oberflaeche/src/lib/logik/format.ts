/** Anzeigeformate: Dauer, Datum, Größe. */

export function dauerText(sekunden: number | null | undefined): string {
  if (sekunden == null || !Number.isFinite(sekunden)) return '–';
  const minuten = Math.round(sekunden / 60);
  if (minuten < 1) return '< 1 Min.';
  if (minuten < 60) return `${minuten} Min.`;
  const h = Math.floor(minuten / 60);
  const m = minuten % 60;
  return m ? `${h} Std. ${m} Min.` : `${h} Std.`;
}

/** Zeitmarke aus dem Transkript (`hh:mm:ss` bzw. `mm:ss`). */
export function zeitmarke(sekunden: number | null | undefined): string {
  if (sekunden == null) return '';
  const s = Math.max(0, Math.floor(sekunden));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const r = s % 60;
  const zwei = (n: number) => String(n).padStart(2, '0');
  return h ? `${h}:${zwei(m)}:${zwei(r)}` : `${m}:${zwei(r)}`;
}

/** `20261121_143000` (Dateinamen der Besprechungen) oder ISO-Text → Date. */
export function zeitLesen(text: string | null | undefined): Date | null {
  if (!text) return null;
  const m = /^(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})$/.exec(text);
  if (m) return new Date(+m[1]!, +m[2]! - 1, +m[3]!, +m[4]!, +m[5]!, +m[6]!);
  const d = new Date(text);
  return Number.isNaN(d.getTime()) ? null : d;
}

export function datumText(text: string | null | undefined): string {
  const d = zeitLesen(text);
  if (!d) return '';
  return d.toLocaleString('de-DE', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit'
  });
}

export function groesseText(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 ** 2) return `${Math.round(bytes / 1024)} KB`;
  if (bytes < 1024 ** 3) return `${(bytes / 1024 ** 2).toFixed(1).replace('.', ',')} MB`;
  return `${(bytes / 1024 ** 3).toFixed(1).replace('.', ',')} GB`;
}

/** Unix-Sekunden → „14:32“ oder „gestern“ / Datum. */
export function uhrzeit(sekunden: number): string {
  return new Date(sekunden * 1000).toLocaleTimeString('de-DE', { hour: '2-digit', minute: '2-digit' });
}

export function dateiname(pfad: string): string {
  return pfad.split(/[\\/]/).pop() ?? pfad;
}

export function ordnerVon(pfad: string): string {
  const i = Math.max(pfad.lastIndexOf('\\'), pfad.lastIndexOf('/'));
  return i > 0 ? pfad.slice(0, i) : pfad;
}
