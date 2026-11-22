/**
 * Stufen des Dienstes (Schlüssel aus `services/pipeline_service.py`, STAGE_LABELS, und
 * `api/routen_ollama.py`) als kurze, nicht technische Sätze. Den `stufe_text` des Dienstes zeigt die
 * Oberfläche nie direkt – er enthält Fachbegriffe und Abschnittszähler.
 */

export const STUFEN: Record<string, string> = {
  datei_pruefung: 'Wird vorbereitet',
  audio_normalisierung: 'Wird vorbereitet',
  chunk_planung: 'Wird vorbereitet',
  modell_laden: 'Spracherkennung startet',
  transkription: 'Wird in Text umgewandelt',
  ausrichtung: 'Wird in Text umgewandelt',
  diarisierung: 'Sprecher werden erkannt',
  zusammenfuehrung: 'Text wird zusammengesetzt',
  export_transkript: 'Wird gespeichert',
  transkript_laden: 'Wird vorbereitet',
  protokoll_auswertung: 'Zusammenfassung wird geschrieben',
  export_protokoll: 'Wird gespeichert',
  protokoll_fehlgeschlagen: 'Zusammenfassung hat nicht geklappt',
  abgeschlossen: 'Gleich fertig',
  laden: 'Wird heruntergeladen',
  // Ersteinrichtung (api/routen_einrichtung.py)
  ffmpeg: 'Wird eingerichtet',
  ollama: 'Wird eingerichtet',
  whisper: 'Wird heruntergeladen',
  pyannote: 'Wird heruntergeladen'
};

export const UNBEKANNT = 'Wird verarbeitet';

export function stufenText(stufe: string | null | undefined, status?: string): string {
  if (status === 'wartet') return 'Wartet';
  if (!stufe) return status === 'laeuft' ? 'Wird vorbereitet' : UNBEKANNT;
  if (stufe.startsWith('modell:')) return 'Wird heruntergeladen';
  return STUFEN[stufe] ?? UNBEKANNT;
}

/** Zustände eines Aufnahmegeräts (`services/live_service.py`). */
export const GERAETE_ZUSTAENDE: Record<string, string> = {
  empfang: 'Nimmt auf',
  wartet: 'Aufnahme angekommen',
  transkription: 'Wird in Text umgewandelt',
  transkript: 'Text fertig',
  auswertung: 'Zusammenfassung wird geschrieben',
  fertig: 'Fertig',
  fehler: 'Hat nicht geklappt'
};
