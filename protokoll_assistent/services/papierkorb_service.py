"""Dateien in den Papierkorb von Windows legen -- ohne zusaetzliches Paket (CLAUDE.md, Regel 8).

Benutzt ``SHFileOperationW`` aus ``shell32`` ueber ``ctypes``: mit ``FOF_ALLOWUNDO`` landet die Datei im
Papierkorb statt endgueltig geloescht zu werden; die anderen Schalter unterdruecken jede Rueckfrage und jedes
Fenster (der Dienst hat keine Oberflaeche, die Bestaetigung holt die Oberflaeche vorher selbst ein).

Die Aufrufer bekommen ``in_papierkorb`` als Funktion uebergeben, damit Tests sie ersetzen koennen -- kein Test
legt etwas in den echten Papierkorb.
"""

from __future__ import annotations

import os
from pathlib import Path

FO_DELETE = 0x0003
FOF_SILENT = 0x0004
FOF_NOCONFIRMATION = 0x0010
FOF_ALLOWUNDO = 0x0040
FOF_NOERRORUI = 0x0400
SCHALTER = FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_SILENT | FOF_NOERRORUI


class PapierkorbFehler(OSError):
    """Der Papierkorb von Windows hat nicht alles angenommen (oder es gibt ihn hier nicht)."""


def quellliste(pfade: list[Path]) -> str:
    """``pFrom`` fuer ``SHFileOperationW``: volle Pfade, je durch eine Null getrennt, am Ende eine zweite Null."""
    # abspath statt resolve: resolve machte aus einem verbundenen Netzlaufwerk einen UNC-Pfad.
    return "".join(f"{os.path.abspath(p)}\0" for p in pfade) + "\0"  # noqa: PTH100


def in_papierkorb(pfade: list[Path], *, windows: bool = os.name == "nt") -> None:
    """Legt die Dateien in den Papierkorb. Wirft ``PapierkorbFehler``, wenn das nicht (vollstaendig) ging -- der
    Aufrufer weicht dann auf einen eigenen Ordner aus."""
    if not pfade:
        return
    if not windows:
        raise PapierkorbFehler("Den Papierkorb von Windows gibt es nur unter Windows.")
    if not all(_laufwerk_mit_papierkorb(p) for p in pfade):  # pragma: no cover - nur Windows
        # Netzlaufwerke und Wechseldatentraeger haben keinen Papierkorb: Windows loeschte dort endgueltig.
        raise PapierkorbFehler("Auf diesem Laufwerk gibt es keinen Papierkorb.")
    _shell_loeschen(quellliste(pfade))  # pragma: no cover - nur Windows
    fehlen = [p for p in pfade if p.exists()]  # pragma: no cover - nur Windows
    if fehlen:  # pragma: no cover - nur Windows
        raise PapierkorbFehler(f"Nicht im Papierkorb: {', '.join(p.name for p in fehlen)}")


DRIVE_FIXED = 3


def _laufwerk_mit_papierkorb(pfad: Path) -> bool:  # pragma: no cover - nur Windows
    """Nur feste Laufwerke mit Buchstaben: Auf Netzlaufwerken und USB-Sticks loescht Windows ohne Papierkorb."""
    import ctypes

    laufwerk = os.path.splitdrive(os.path.abspath(pfad))[0]  # noqa: PTH100
    if not laufwerk or laufwerk.startswith(("\\\\", "//")):
        return False
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined,unused-ignore]
    return int(kernel32.GetDriveTypeW(laufwerk + "\\")) == DRIVE_FIXED


def _shell_loeschen(quelle: str) -> None:  # pragma: no cover - nur Windows
    import ctypes
    from ctypes import wintypes

    class SHFILEOPSTRUCTW(ctypes.Structure):
        _fields_ = [
            ("hwnd", wintypes.HWND),
            ("wFunc", wintypes.UINT),
            ("pFrom", ctypes.c_void_p),
            ("pTo", ctypes.c_wchar_p),
            ("fFlags", ctypes.c_uint16),
            ("fAnyOperationsAborted", wintypes.BOOL),
            ("hNameMappings", ctypes.c_void_p),
            ("lpszProgressTitle", ctypes.c_wchar_p),
        ]

    # Ein Puffer statt einer Zeichenkette: Die Nullen darin muessen erhalten bleiben.
    puffer = ctypes.create_unicode_buffer(quelle, len(quelle) + 1)
    vorgang = SHFILEOPSTRUCTW()
    vorgang.hwnd = None
    vorgang.wFunc = FO_DELETE
    vorgang.pFrom = ctypes.addressof(puffer)
    vorgang.pTo = None
    vorgang.fFlags = SCHALTER
    shell32 = ctypes.WinDLL("shell32", use_last_error=True)  # type: ignore[attr-defined,unused-ignore]
    shell32.SHFileOperationW.argtypes = [ctypes.POINTER(SHFILEOPSTRUCTW)]
    shell32.SHFileOperationW.restype = ctypes.c_int
    ergebnis = shell32.SHFileOperationW(ctypes.byref(vorgang))
    if ergebnis != 0 or vorgang.fAnyOperationsAborted:
        raise PapierkorbFehler(f"Der Papierkorb von Windows hat abgelehnt (Code {ergebnis:#x}).")
