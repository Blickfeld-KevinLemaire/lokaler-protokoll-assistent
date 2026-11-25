"""Probe der Grafikkarte in einem eigenen Prozess (fuer ``grafikkarte_service``).

    python -m protokoll_assistent.services.grafikkarte_probe transkription|sprechertrennung

Warum ein eigener Prozess: Verweigert der Rechner der Laufzeit der Karte etwas, scheitert die erste Rechnung oft
nicht mit einer Ausnahme, sondern mit einem Speicherzugriffsfehler -- der ganze Prozess ist weg. Gemessen auf
einem Ryzen AI Max+ 395 (gfx1151) unter Fedora: SELinux liess die ROCm-Laufzeit im Container nicht an alles heran;
CTranslate2 meldete die Karte und float16, die erste Rechnung beendete den Prozess mit Signal 11 (Ollamas
ROCm-Image genauso). Im Dienst selbst haette das den Start ohne jede Erklaerung abgebrochen. So bleibt es ein
Befund mit Meldung -- und die Meldung nennt die bekannten Ursachen.

Der Kindprozess schreibt als letzte Zeile ein JSON ``{"ok": bool, "meldung": str}``.
"""

from __future__ import annotations

import json
import signal
import subprocess
import sys
from collections.abc import Callable, Sequence
from typing import Any

from protokoll_assistent.utils.prozess import KEIN_FENSTER

SCHRITTE = ("transkription", "sprechertrennung")
# Das Laden von CUDA/ROCm und die erste Rechnung brauchen Sekunden; die Grenze faengt nur eine haengende Karte ab.
ZEITLIMIT_SEKUNDEN = 180

LaufFn = Callable[..., Any]


def _signalname(code: int) -> str:
    nummer = -code if code < 0 else code - 128
    try:
        return f"Signal {nummer} ({signal.Signals(nummer).name})"
    except ValueError:
        return f"Code {code}"


def im_eigenen_prozess(schritt: str, lauf_fn: LaufFn | None = None, python: str | None = None) -> tuple[bool, str]:
    """Fuehrt die Probe fuer ``schritt`` in einem eigenen Prozess aus und liefert ``(ok, meldung)``."""
    from protokoll_assistent.utils.paths import get_project_root

    befehl = [python or sys.executable, "-m", __name__, schritt]
    try:
        lauf = (lauf_fn or subprocess.run)(
            befehl,
            cwd=get_project_root(),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=ZEITLIMIT_SEKUNDEN,
            check=False,
            creationflags=KEIN_FENSTER,
        )
    except subprocess.TimeoutExpired:
        return False, f"die erste Rechnung auf der Karte kam nach {ZEITLIMIT_SEKUNDEN} s nicht zurueck"
    except OSError as fehler:
        return False, f"die Probe liess sich nicht starten: {fehler}"
    zeilen = (lauf.stdout or "").strip().splitlines()
    if lauf.returncode == 0 and zeilen:
        try:
            daten = json.loads(zeilen[-1])
            return bool(daten["ok"]), str(daten["meldung"])
        except (ValueError, KeyError, TypeError):
            pass
    if lauf.returncode < 0 or lauf.returncode > 128:
        return False, (
            f"der Prozess stuerzt bei der ersten Rechnung auf der Karte ab ({_signalname(lauf.returncode)}). "
            "Bekannte Ursachen: SELinux auf dem Rechner (Fedora/RHEL: 'security_opt: label:disable' fehlt), "
            "oder Kernel, Firmware bzw. Grafiktreiber passen nicht zur Karte"
        )
    letzte = " | ".join((lauf.stderr or lauf.stdout or "").strip().splitlines()[-3:])
    return False, f"die Probe ist gescheitert (Code {lauf.returncode}): {letzte}"


def main(argv: Sequence[str] | None = None) -> int:
    argumente = list(sys.argv[1:] if argv is None else argv)
    if len(argumente) != 1 or argumente[0] not in SCHRITTE:
        print(f"Aufruf: python -m {__name__} {'|'.join(SCHRITTE)}", file=sys.stderr)
        return 2
    from protokoll_assistent.services import model_service

    pruefen = model_service.whisper_auf_grafikkarte if argumente[0] == "transkription" else model_service.torch_auf_grafikkarte
    ok, meldung = pruefen()
    print(json.dumps({"ok": ok, "meldung": meldung}, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
