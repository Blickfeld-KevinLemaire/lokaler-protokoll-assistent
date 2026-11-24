"""Aufnahmen: Eingangsordner auflisten, Dateien hochladen (Browser im Netz, Aufnahme im Browser)."""

from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, UploadFile, status

from protokoll_assistent.api import modelle
from protokoll_assistent.api.kontext import Angemeldet, Dienste, angemeldet, dienste

router = APIRouter(prefix="/api/dateien", tags=["dateien"])

AUDIO_ENDUNGEN = frozenset(
    {".mp3", ".mp4", ".m4a", ".wav", ".aac", ".flac", ".ogg", ".opus", ".mov", ".mkv", ".webm", ".wma", ".amr"}
)
MAX_HOCHLADEN_BYTES = 8 * 1024**3
_UNERLAUBT = re.compile(r"[^A-Za-z0-9ÄÖÜäöüß _.-]+")
STUECK_BYTES = 1024 * 1024


def sicherer_name(name: str) -> str:
    """Nur der Dateiname (kein Pfad), ohne Zeichen, die Windows oder die Shell stoeren."""
    basis = Path(name.replace("\\", "/")).name
    stamm = _UNERLAUBT.sub("_", Path(basis).stem).strip(" ._") or "aufnahme"
    return f"{stamm[:80]}{Path(basis).suffix.lower()}"


def _eindeutig(ordner: Path, name: str) -> Path:
    ziel = ordner / name
    zaehler = 1
    while ziel.exists():
        ziel = ordner / f"{Path(name).stem}_{zaehler}{Path(name).suffix}"
        zaehler += 1
    return ziel


def _audio_in(ordner: Path) -> list[dict[str, Any]]:
    if not ordner.is_dir():
        return []
    dateien = []
    for pfad in ordner.iterdir():
        if pfad.is_file() and pfad.suffix.lower() in AUDIO_ENDUNGEN:
            stat = pfad.stat()
            dateien.append({"name": pfad.name, "pfad": str(pfad), "groesse": stat.st_size, "geaendert": stat.st_mtime})
    return sorted(dateien, key=lambda d: d["geaendert"], reverse=True)


@router.get("/eingang", response_model=list[modelle.EingangsDatei])
def eingang(d: Dienste = Depends(dienste), wer: Angemeldet = Depends(angemeldet)) -> list[dict[str, Any]]:
    """Aufnahmen im Aufnahmeordner und (Windows-Anwendung) im Eingangsordner, neueste zuerst."""
    ordner = [d.aufnahmeordner(wer)]
    eingabe = d.steuerung.konfiguration().get("eingabeordner")
    if eingabe and not d.mehrbenutzer and Path(eingabe) not in ordner:
        ordner.append(Path(eingabe))
    gesehen: set[str] = set()
    ergebnis = []
    for o in ordner:
        for datei in _audio_in(o):
            if datei["pfad"] not in gesehen:
                gesehen.add(datei["pfad"])
                ergebnis.append(datei)
    return sorted(ergebnis, key=lambda x: x["geaendert"], reverse=True)


@router.post("/hochladen", response_model=modelle.EingangsDatei, status_code=201)
def hochladen(datei: UploadFile, d: Dienste = Depends(dienste), wer: Angemeldet = Depends(angemeldet)) -> dict[str, Any]:
    name = sicherer_name(datei.filename or "aufnahme")
    if Path(name).suffix.lower() not in AUDIO_ENDUNGEN:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "Dieses Dateiformat wird nicht unterstützt.")
    ordner = d.aufnahmeordner(wer)
    ordner.mkdir(parents=True, exist_ok=True)
    ziel = _eindeutig(ordner, name)
    teil = ziel.with_name(ziel.name + ".part")
    geschrieben = 0
    try:
        with teil.open("wb") as ausgabe:
            while stueck := datei.file.read(STUECK_BYTES):
                geschrieben += len(stueck)
                if geschrieben > MAX_HOCHLADEN_BYTES:
                    raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Die Datei ist zu groß.")
                ausgabe.write(stueck)
        if geschrieben == 0:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Die Datei ist leer.")
        shutil.move(str(teil), str(ziel))
    finally:
        teil.unlink(missing_ok=True)
    stat = ziel.stat()
    d.steuerung.bus.senden("dateien", {"grund": "hochgeladen", "pfad": str(ziel)})
    return {"name": ziel.name, "pfad": str(ziel), "groesse": stat.st_size, "geaendert": stat.st_mtime}
