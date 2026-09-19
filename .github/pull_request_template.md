## Worum geht es?

<!-- Kurz: Was aendert sich, und warum? -->

## Wie wurde es geprueft?

<!-- Welche Tests sind neu oder angepasst? Wurde es einmal von Hand ausprobiert? -->

## Checkliste

- [ ] `uv run ruff check .` laeuft durch
- [ ] `uv run mypy` laeuft durch
- [ ] `uv run pytest` laeuft durch (Abdeckung mindestens 85 %)
- [ ] Neue Laufzeit-Abhaengigkeiten stehen **sowohl** in `pyproject.toml` **als auch**
      in der passenden `requirements*.txt`
- [ ] Keine Schluessel, Token, Aufnahmen oder Transkripte im Diff
- [ ] Bei Aenderungen an der Datenuebertragung: Die Rueckfrage vor dem Upload
      ist weiterhin vorhanden

> Die CI meldet Fehler, kann das Zusammenfuehren aber nicht verhindern, solange
> es keine Branch-Schutzregeln gibt. Bitte vor dem Merge selbst nachsehen.
