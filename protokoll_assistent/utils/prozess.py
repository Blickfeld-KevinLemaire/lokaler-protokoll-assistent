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

KEIN_FENSTER: int = getattr(subprocess, "CREATE_NO_WINDOW", 0)
NEUE_PROZESSGRUPPE: int = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
