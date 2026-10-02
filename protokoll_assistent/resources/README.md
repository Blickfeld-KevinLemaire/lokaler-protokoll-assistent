# Logo und Programmsymbol

Die Dateien hier gehören zum Erscheinungsbild der Anwendung (VERMERK).

| Datei | Verwendung |
|---|---|
| `branding/vermerk_logo_hauptlogo.eps` | Quelle (Vektorvorlage), nicht ändern |
| `vermerk_logo.svg` / `.png` | großes Logo mit Schriftzug, für helle Hintergründe |
| `vermerk_logo_hell.png` | dasselbe für dunkle Hintergründe (Seitenleiste) |
| `vermerk_icon.svg` / `.png` | nur die Bildmarke, quadratisch |
| `vermerk_icon.ico` | Windows-Symbol (16 bis 256 Pixel): Fenster, EXE, Installer |

Alles außer der EPS wird erzeugt:

```powershell
uv run python -m protokoll_assistent.tools.logo_erzeugen
```

Die Fassung für dunklen Grund färbt die dunklen Flächen weiß und behält das
Hellblau. Verwendet werden die Dateien in `gui/branding.py`, in der
Seitenleiste des Hauptfensters, in `protokoll_assistent.spec` (EXE-Symbol) und in
`installer/protokoll-assistent.iss` (Installer-Symbol).
