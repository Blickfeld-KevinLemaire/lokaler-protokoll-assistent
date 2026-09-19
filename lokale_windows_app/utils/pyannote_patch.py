"""Separates Pruef- und Reparaturskript fuer die pyannote-Kompatibilitaetskorrektur.

Hintergrund: Bei sehr kurzen Audioteilen kann die letzte Dimension des
Tensors in ``pyannote/audio/models/blocks/pooling.py`` nur einen einzigen
Wert enthalten. ``sequences.std(dim=-1, correction=1)`` erzeugt dann NaN.
Dieses Skript ersetzt die betroffene Zeile durch eine abgesicherte Variante.

Sicherheitsregeln (verbindlich):
* Die Anwendung selbst ruft dieses Skript NICHT automatisch bei jedem Start
  auf. Es wird ausschliesslich gezielt ueber ``check_pyannote_fix.ps1`` bzw.
  waehrend der Einrichtung aufgerufen.
* Ist die Absicherung bereits vorhanden, wird nichts veraendert.
* Es wird nur korrigiert, wenn die Originalzeile eindeutig (genau einmal)
  gefunden wird.
* Vor jeder Aenderung wird eine Sicherungskopie der Originaldatei angelegt.
* Nach der Aenderung wird die Datei mit ``py_compile`` auf Syntaxfehler
  geprueft; schlaegt das fehl, wird die Sicherung automatisch wiederhergestellt.
"""

from __future__ import annotations

import argparse
import py_compile
import re
import shutil
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

MARKER = "# --- Protokoll-Assistent Lokal: NaN-Absicherung fuer kurze Sequenzen ---"

ORIGINAL_LINE_PATTERN = re.compile(
    r"^([ \t]*)std = sequences\.std\(dim=-1, correction=1\)[ \t]*\r?\n$"
)

RELATIVE_TARGET_WINDOWS = Path("Lib") / "site-packages" / "pyannote" / "audio" / "models" / "blocks" / "pooling.py"
RELATIVE_TARGET_POSIX = Path("lib") / "python3.10" / "site-packages" / "pyannote" / "audio" / "models" / "blocks" / "pooling.py"


@dataclass
class PatchResult:
    changed: bool
    message: str
    target_file: Path | None = None


def find_pooling_file(venv_dir: Path) -> Path | None:
    """Sucht ``pooling.py`` in der angegebenen virtuellen Umgebung.

    Es wird sowohl das Windows- als auch (fuer Tests/Linux) das
    POSIX-Layout einer venv beruecksichtigt. Zusaetzlich wird notfalls im
    gesamten venv-Baum gesucht, damit sich das Skript nicht auf eine feste
    Python-Nebenversion verlaesst.
    """
    for relative in (RELATIVE_TARGET_WINDOWS, RELATIVE_TARGET_POSIX):
        candidate = venv_dir / relative
        if candidate.is_file():
            return candidate

    matches = sorted(venv_dir.glob("**/pyannote/audio/models/blocks/pooling.py"))
    if matches:
        return matches[0]
    return None


def is_already_patched(text: str) -> bool:
    return MARKER in text


def find_unique_original_line(lines: list[str]) -> int | None:
    matching_indices = [
        index for index, line in enumerate(lines) if ORIGINAL_LINE_PATTERN.match(line)
    ]
    if len(matching_indices) == 1:
        return matching_indices[0]
    return None


def build_replacement(indent: str) -> list[str]:
    return [
        f"{MARKER}\n",
        f"{indent}if sequences.size(dim=-1) > 1:\n",
        f"{indent}    std = sequences.std(dim=-1, correction=1)\n",
        f"{indent}else:\n",
        f"{indent}    std = torch.zeros_like(mean)\n",
    ]


def apply_patch(target_file: Path, dry_run: bool = False) -> PatchResult:
    if not target_file.is_file():
        return PatchResult(False, f"Datei nicht gefunden: {target_file}", target_file)

    original_text = target_file.read_text(encoding="utf-8")

    if is_already_patched(original_text):
        return PatchResult(
            False,
            "Absicherung ist bereits vorhanden. Es wurde nichts veraendert.",
            target_file,
        )

    lines = original_text.splitlines(keepends=True)
    match_index = find_unique_original_line(lines)
    if match_index is None:
        count = sum(1 for line in lines if ORIGINAL_LINE_PATTERN.match(line))
        if count == 0:
            return PatchResult(
                False,
                "Die zu korrigierende Originalzeile wurde nicht gefunden. "
                "Vermutlich weicht die installierte pyannote-Version ab. "
                "Es wurde nichts veraendert; bitte manuell pruefen.",
                target_file,
            )
        return PatchResult(
            False,
            f"Die Originalzeile wurde {count}-mal gefunden (nicht eindeutig). "
            "Aus Sicherheitsgruenden wurde nichts veraendert.",
            target_file,
        )

    # 'lines[match_index]' wurde oben ueber genau dieses Muster gefunden,
    # ein Treffer ist hier also garantiert.
    treffer = ORIGINAL_LINE_PATTERN.match(lines[match_index])
    assert treffer is not None  # noqa: S101 - nur Typ-Einengung
    indent = treffer.group(1)

    if dry_run:
        return PatchResult(
            True,
            "Originalzeile eindeutig gefunden. Korrektur wuerde jetzt angewendet "
            "(--dry-run: es wurde nichts veraendert).",
            target_file,
        )

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_file = target_file.with_name(f"{target_file.name}.backup_{timestamp}")
    shutil.copy2(target_file, backup_file)

    new_lines = lines[:match_index] + build_replacement(indent) + lines[match_index + 1 :]
    target_file.write_text("".join(new_lines), encoding="utf-8")

    try:
        py_compile.compile(str(target_file), doraise=True)
    except py_compile.PyCompileError as error:
        shutil.copy2(backup_file, target_file)
        return PatchResult(
            False,
            "Nach der Korrektur ist ein Syntaxfehler aufgetreten. Die Original-"
            f"datei wurde automatisch wiederhergestellt. Details: {error}",
            target_file,
        )

    return PatchResult(
        True,
        f"Korrektur erfolgreich angewendet. Sicherungskopie: {backup_file.name}",
        target_file,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Prueft und repariert die pyannote-NaN-Absicherung in pooling.py."
    )
    parser.add_argument(
        "--venv",
        type=Path,
        default=None,
        help="Pfad zur virtuellen Umgebung (Standard: .venv-whisperx neben der Anwendung).",
    )
    parser.add_argument(
        "--file",
        type=Path,
        default=None,
        help="Direkter Pfad zur pooling.py (ueberschreibt --venv).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Nur pruefen, nichts veraendern.",
    )
    args = parser.parse_args(argv)

    if args.file is not None:
        target_file = args.file
    else:
        from utils.paths import get_venv_dir

        venv_dir = args.venv or get_venv_dir()
        target_file = find_pooling_file(venv_dir)
        if target_file is None:
            print(f"FEHLER: pooling.py wurde in '{venv_dir}' nicht gefunden.")
            print("Ist die virtuelle Umgebung '.venv-whisperx' vollstaendig eingerichtet?")
            return 2

    result = apply_patch(target_file, dry_run=args.dry_run)
    print(result.message)
    return 0 if (result.changed or "bereits vorhanden" in result.message) else 1


if __name__ == "__main__":
    sys.exit(main())
