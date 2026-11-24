"""Unterprozesse ohne schwarzes Konsolenfenster (Windows).

Die Anwendung hat selbst kein Konsolenfenster zu zeigen: Die gebaute EXE ist
eine Fensteranwendung, und die Oberflaeche laeuft auch in der eingerichteten
Laufzeitumgebung unsichtbar im Hintergrund (siehe ``bootstrap._relaunch``).
Startet ein solcher Prozess aber ein Konsolenprogramm (``python.exe``,
``ffmpeg.exe``, ``nvidia-smi``), oeffnet Windows dafuer von sich aus ein neues
schwarzes Fenster -- bei ``python.exe`` samt Oberflaeche so lange, wie das
Programm laeuft, und schliesst der Anwender es, endet auch das Programm.

``KEIN_FENSTER`` als ``creationflags=`` an jeden ``subprocess``-Aufruf, dessen
Ergebnis der Anwender nicht in einer Konsole lesen soll. Ohne Windows ist der
Wert 0 (die Konstante gibt es dort nicht; das Flag waere ohnehin wirkungslos).

Nur Standardbibliothek: ``bootstrap`` laeuft, bevor irgendetwas installiert ist.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable, Sequence
from typing import Any, TypeVar

KEIN_FENSTER: int = getattr(subprocess, "CREATE_NO_WINDOW", 0)
NEUE_PROZESSGRUPPE: int = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
# Vom startenden Programm geloest: Der Prozess lebt weiter, wenn dieses endet.
LOSGELOEST: int = getattr(subprocess, "DETACHED_PROCESS", 0)
# Nicht im Job-Objekt des Startenden: Das Fenster (oberflaeche/src-tauri/src/prozess.rs) legt den Dienst in einen
# Job, der beim Schliessen alle seine Prozesse beendet. Was laenger leben soll (Ollama, sein Installer), verlaesst ihn.
AUS_DEM_JOB: int = getattr(subprocess, "CREATE_BREAKAWAY_FROM_JOB", 0)

_Ergebnis = TypeVar("_Ergebnis")


def ausserhalb_des_jobs_starten(
    starte: Callable[..., _Ergebnis], befehl: Sequence[str], *, creationflags: int = 0, **argumente: Any
) -> _Ergebnis:
    """Startet ``befehl`` mit ``starte`` (``subprocess.Popen``/``run``) ausserhalb des Job-Objekts, in dem dieser
    Prozess laeuft. Erlaubt ein umgebender Job das nicht (kein ``JOB_OBJECT_LIMIT_BREAKAWAY_OK``, etwa ein fremdes
    Startprogramm), scheitert der Start mit "Zugriff verweigert" -- dann noch einmal ohne: Der Prozess lebt dann
    nur so lange wie der Job, aber er laeuft."""
    if AUS_DEM_JOB:
        try:
            return starte(list(befehl), creationflags=creationflags | AUS_DEM_JOB, **argumente)
        except PermissionError:
            pass
    return starte(list(befehl), creationflags=creationflags, **argumente)
