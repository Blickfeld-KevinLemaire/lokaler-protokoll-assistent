/** Das Transkript als Folge von Wortbeiträgen – für die Anzeige und zum Kopieren. */
import type { Segment } from '../api/typen';
import { sprecherName, zeitmarke } from './format';

export interface Beitrag {
  sprecher: string;
  id: string;
  start: number | null;
  text: string;
}

/** Aufeinanderfolgende Stücke derselben Person zusammenfassen – liest sich wie ein Gespräch. */
export function transkriptBloecke(segmente: Segment[]): Beitrag[] {
  const ergebnis: Beitrag[] = [];
  for (const s of segmente) {
    const name = sprecherName(s.sprecher, s.sprecher_id);
    const letzter = ergebnis.at(-1);
    if (letzter && letzter.id === (s.sprecher_id ?? name)) letzter.text += ` ${s.text ?? ''}`;
    else ergebnis.push({ sprecher: name, id: s.sprecher_id ?? name, start: s.start, text: s.text ?? '' });
  }
  return ergebnis;
}

/**
 * Zum Einfügen in eine Mail oder ein Dokument: je Wortbeitrag eine Zeile „[12:05] Anna: …“ (Zeitmarke wie in der
 * Ansicht, Namen wie unter „Sprecher“ vergeben). Ohne Sprechertrennung nur Zeit und Text.
 */
export function transkriptAlsText(segmente: Segment[]): string {
  const zeilen = transkriptBloecke(segmente)
    .filter((b) => b.text.trim())
    .map((b) => `[${zeitmarke(b.start) || '0:00'}] ${b.sprecher ? `${b.sprecher}: ` : ''}${b.text.trim()}`);
  return zeilen.length ? `${zeilen.join('\n')}\n` : '';
}
