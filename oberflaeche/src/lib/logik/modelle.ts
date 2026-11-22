/**
 * Modelle in einfachen Worten: Statt „Qwen3.5 4B (empfohlener Standard)“ steht vorn „Empfohlen“, der Name
 * nur noch klein daneben. Abgeleitet aus dem Zusatz in Klammern, den der Dienst mitliefert.
 */

export interface ModellEinordnung {
  /** „Empfohlen“, „Schneller“, „Genauer“ – oder der Name, wenn der Zusatz nichts hergibt. */
  titel: string;
  /** Der Name des Modells (klein, zweitrangig). */
  name: string;
  /** Rest des Zusatzes, z. B. „auch für Rechner ohne Grafikkarte“. */
  zusatz: string;
}

const STICHWORTE: [RegExp, string][] = [
  [/^empfohlen\w*/i, 'Empfohlen'],
  [/^schneller/i, 'Schneller'],
  [/^genauer/i, 'Genauer'],
  [/^kleiner/i, 'Kleiner'],
  [/^gr(ö|oe)(ß|ss)er/i, 'Größer']
];

export function modellEinordnen(label: string): ModellEinordnung {
  const m = /^(.*?)\s*\((.*)\)\s*$/.exec(label);
  const name = (m ? m[1]! : label).trim();
  const klammer = (m ? m[2]! : '').trim();
  for (const [muster, titel] of STICHWORTE) {
    if (muster.test(klammer)) {
      const zusatz = klammer
        .replace(muster, '')
        .replace(/^\s*(standard)?\s*[,;–-]?\s*/i, '')
        .trim();
      return { titel, name, zusatz };
    }
  }
  return { titel: name, name: '', zusatz: klammer };
}
