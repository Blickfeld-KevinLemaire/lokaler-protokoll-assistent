"""Stimmen alle Versionsangaben ueberein? (nur Standardbibliothek)

    python tools/versionen_pruefen.py                 (nur die Dateien untereinander)
    python tools/versionen_pruefen.py v0.6.0-alpha.1  (zusaetzlich gegen den Tag)

Verglichen werden ``pyproject.toml``, ``protokoll_assistent/version.py``, ``oberflaeche/package.json``
(fehlt sie, mit Hinweis uebersprungen), ``oberflaeche/src-tauri/tauri.conf.json`` und
``oberflaeche/src-tauri/Cargo.toml`` -- dazu Major.Minor aller ``@tauri-apps/*``-Pakete in package.json
gegen das Crate ``tauri`` (ARCHITEKTUR.md, "Build, Release, CI"). Exit-Code 1 bei einer Abweichung.
"""

from __future__ import annotations

import ast
import json
import re
import sys
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10
    tomllib = None  # type: ignore[assignment]

WURZEL = Path(__file__).resolve().parent.parent


def _toml_lesen(pfad: Path) -> dict[str, object]:
    text = pfad.read_text(encoding="utf-8")
    if tomllib is not None:
        return tomllib.loads(text)
    return _toml_notbehelf(text)


def _toml_notbehelf(text: str) -> dict[str, object]:
    """Genug TOML fuer diese Pruefung unter Python 3.10: Abschnitte, ``name = "wert"`` und Inline-Tabellen
    mit ``version = "..."``."""
    ergebnis: dict[str, object] = {}
    abschnitt: dict[str, object] = ergebnis
    for roh in text.splitlines():
        zeile = roh.strip()
        if not zeile or zeile.startswith("#"):
            continue
        kopf = re.match(r"\[([^\[\]]+)\]", zeile)
        if kopf:
            abschnitt = ergebnis
            for teil in kopf.group(1).split("."):
                abschnitt = abschnitt.setdefault(teil.strip().strip('"'), {})  # type: ignore[assignment]
            continue
        eintrag = re.match(r'([A-Za-z0-9_.-]+)\s*=\s*"([^"]*)"', zeile)
        if eintrag:
            abschnitt[eintrag.group(1)] = eintrag.group(2)
            continue
        tabelle = re.match(r"([A-Za-z0-9_.-]+)\s*=\s*\{(.*)\}", zeile)
        if tabelle:
            version = re.search(r'version\s*=\s*"([^"]*)"', tabelle.group(2))
            abschnitt[tabelle.group(1)] = {"version": version.group(1)} if version else {}
    return ergebnis


def version_py(pfad: Path) -> str:
    for knoten in ast.parse(pfad.read_text(encoding="utf-8")).body:
        if isinstance(knoten, ast.Assign) and any(isinstance(z, ast.Name) and z.id == "VERSION" for z in knoten.targets):
            if isinstance(knoten.value, ast.Constant) and isinstance(knoten.value.value, str):
                return knoten.value.value
    raise ValueError(f"VERSION fehlt in {pfad}")


def major_minor(version: str) -> str | None:
    """'^2.12.5' -> '2.12', '~2.12' -> '2.12', '2' -> None."""
    treffer = re.search(r"(\d+)\.(\d+)", version)
    return f"{treffer.group(1)}.{treffer.group(2)}" if treffer else None


def crate_version(cargo: dict[str, object], name: str) -> str | None:
    abhaengigkeiten = cargo.get("dependencies")
    if not isinstance(abhaengigkeiten, dict):
        return None
    eintrag = abhaengigkeiten.get(name)
    if isinstance(eintrag, str):
        return eintrag
    if isinstance(eintrag, dict) and isinstance(eintrag.get("version"), str):
        return str(eintrag["version"])
    return None


def pruefen(wurzel: Path, tag: str | None) -> tuple[list[str], list[str]]:
    """Gibt (Abweichungen, Hinweise) zurueck."""
    abweichungen: list[str] = []
    hinweise: list[str] = []
    versionen: dict[str, str] = {}

    def lesen(name: str, holen) -> None:  # type: ignore[no-untyped-def]
        try:
            wert = holen()
        except (OSError, ValueError, KeyError, TypeError) as fehler:
            abweichungen.append(f"{name}: nicht lesbar ({fehler})")
            return
        if not isinstance(wert, str) or not wert:
            abweichungen.append(f"{name}: keine Version gefunden")
            return
        versionen[name] = wert

    lesen("pyproject.toml", lambda: _toml_lesen(wurzel / "pyproject.toml")["project"]["version"])  # type: ignore[index]
    lesen("protokoll_assistent/version.py", lambda: version_py(wurzel / "protokoll_assistent" / "version.py"))
    paket_json = wurzel / "oberflaeche" / "package.json"
    paket: dict[str, object] | None = None
    if paket_json.is_file():
        paket = json.loads(paket_json.read_text(encoding="utf-8"))
        lesen("oberflaeche/package.json", lambda: paket["version"])  # type: ignore[index]
    else:
        hinweise.append("oberflaeche/package.json fehlt noch -- uebersprungen.")
    tauri_dir = wurzel / "oberflaeche" / "src-tauri"
    lesen(
        "oberflaeche/src-tauri/tauri.conf.json",
        lambda: json.loads((tauri_dir / "tauri.conf.json").read_text(encoding="utf-8"))["version"],
    )
    cargo: dict[str, object] = {}
    try:
        cargo = _toml_lesen(tauri_dir / "Cargo.toml")
    except OSError as fehler:
        abweichungen.append(f"oberflaeche/src-tauri/Cargo.toml: nicht lesbar ({fehler})")
    else:
        lesen("oberflaeche/src-tauri/Cargo.toml", lambda: cargo["package"]["version"])  # type: ignore[index]

    if tag is not None:
        versionen["Tag"] = tag[1:] if tag.startswith("v") else tag

    if versionen:
        bezug_name, bezug = next(iter(versionen.items()))
        for name, wert in versionen.items():
            if wert != bezug:
                abweichungen.append(f"{name}: {wert} (statt {bezug} wie in {bezug_name})")

    # @tauri-apps/* (npm) und das Crate 'tauri' auf demselben Major.Minor.
    tauri_crate = crate_version(cargo, "tauri") if cargo else None
    if paket is not None:
        npm_pakete: dict[str, str] = {}
        for feld in ("dependencies", "devDependencies"):
            bereich = paket.get(feld)
            if isinstance(bereich, dict):
                npm_pakete.update({k: str(v) for k, v in bereich.items() if k.startswith("@tauri-apps/")})
        if npm_pakete and tauri_crate is None:
            abweichungen.append("Cargo.toml: Crate 'tauri' ohne Version")
        elif tauri_crate is not None:
            soll = major_minor(tauri_crate)
            # Plugins haben eigene Versionen ('@tauri-apps/plugin-dialog' 2.8 zu 'tauri-plugin-dialog' 2.8);
            # gegen 'tauri' werden nur die Kernpakete verglichen.
            for name, wert in sorted(npm_pakete.items()):
                if name.startswith("@tauri-apps/plugin-"):
                    crate = "tauri-" + name.removeprefix("@tauri-apps/")
                    bezug_crate = crate_version(cargo, crate)
                    if bezug_crate is None:
                        hinweise.append(f"{name}: kein Crate {crate} in Cargo.toml -- nicht verglichen.")
                        continue
                    if major_minor(wert) != major_minor(bezug_crate):
                        abweichungen.append(f"{name} {wert} passt nicht zu {crate} {bezug_crate} (Major.Minor)")
                    continue
                if major_minor(wert) != soll:
                    abweichungen.append(f"{name} {wert} passt nicht zum Crate tauri {tauri_crate} (Major.Minor)")
    return abweichungen, [*hinweise, *(f"{n}: {v}" for n, v in versionen.items())]


def main(argv: list[str] | None = None) -> int:
    argumente = list(sys.argv[1:] if argv is None else argv)
    if len(argumente) > 1 or (argumente and argumente[0] in ("-h", "--help")):
        print(__doc__)
        return 0 if argumente and argumente[0] in ("-h", "--help") else 2
    tag = argumente[0] if argumente else None
    abweichungen, hinweise = pruefen(WURZEL, tag)
    for hinweis in hinweise:
        print(hinweis)
    if abweichungen:
        print("\nVersionen passen NICHT zusammen:", file=sys.stderr)
        for abweichung in abweichungen:
            print(f"  - {abweichung}", file=sys.stderr)
        return 1
    print("\nAlle Versionsangaben stimmen ueberein.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
