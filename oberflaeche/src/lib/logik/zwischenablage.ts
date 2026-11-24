/**
 * Text in die Zwischenablage. `navigator.clipboard` gibt es nur in einer sicheren Umgebung (Fenster, https,
 * localhost) – im Browser über `http://` im Firmennetz fehlt es. Dann hilft der alte Weg über ein unsichtbares
 * Textfeld.
 */
export async function inZwischenablage(text: string): Promise<void> {
  if (navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(text);
      return;
    } catch {
      // z. B. ohne Fokus im Dokument – weiter mit dem alten Weg
    }
  }
  const feld = document.createElement('textarea');
  feld.value = text;
  feld.setAttribute('readonly', '');
  feld.style.position = 'fixed';
  feld.style.opacity = '0';
  const vorher = document.activeElement as HTMLElement | null;
  document.body.append(feld);
  feld.focus();
  feld.select();
  try {
    if (!document.execCommand('copy')) throw new Error('Kopieren nicht möglich');
  } finally {
    feld.remove();
    vorher?.focus();
  }
}
