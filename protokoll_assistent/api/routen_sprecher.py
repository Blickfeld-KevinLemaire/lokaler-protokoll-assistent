"""Sprecher einer Besprechung: Hoerprobe, bekannte Stimmen (Profile), Export -- und die Profile selbst.

Stimmprofile sind biometrische Daten: Im Servermodus hat jeder Nutzer seine
eigenen (``sprecherprofile/nutzer/<name>``), niemand sieht die eines anderen.

Die Stimmabdruecke eines Laufs liegen im Arbeitsordner der Aufnahme, der sich
aus dem Hash der Audiodatei ergibt (wie in der Pipeline). Der Hash wird je
Datei (Pfad, Groesse, Aenderungszeit) nur einmal berechnet.
"""

from __future__ import annotations

import hashlib
import json
import threading
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from protokoll_assistent.api.kontext import Angemeldet, Dienste, angemeldet, dienste
from protokoll_assistent.api.routen_besprechungen import besprechung_finden
from protokoll_assistent.services import manifest_service, sprecher_export_service, sprecherprofil_service
from protokoll_assistent.utils import paths

router = APIRouter(prefix="/api", tags=["sprecher"])

_hash_sperre = threading.Lock()
_hash_zwischenspeicher: dict[tuple[str, int, int], str] = {}


class ProfilName(BaseModel):
    name: str = Field(min_length=1, max_length=80)


def profil_ordner(wer: Angemeldet) -> Path:
    basis = paths.get_sprecherprofile_dir()
    return basis / "nutzer" / wer.besitzer if wer.besitzer else basis


def _transkript_daten(transkript: Path) -> dict[str, Any]:
    try:
        daten = json.loads(transkript.read_text(encoding="utf-8"))
    except (OSError, ValueError) as fehler:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Das Transkript ist nicht lesbar.") from fehler
    return daten if isinstance(daten, dict) else {}


def _sprecher_pruefen(daten: dict[str, Any], sprecher_id: str) -> None:
    bekannt = {e.get("sprecher_id") for e in daten.get("sprecher_zuordnung") or [] if isinstance(e, dict)}
    if sprecher_id not in bekannt:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Diesen Sprecher gibt es in diesem Transkript nicht.")


def arbeitsordner_der_aufnahme(daten: dict[str, Any]) -> Path | None:
    """Arbeitsordner der Aufnahme (dort liegen die Stimmabdruecke) -- oder None, wenn die Audiodatei fehlt."""
    audio = Path(str(daten.get("audio_pfad") or ""))
    if not str(audio) or not audio.is_file():
        return None
    if (audio.parent / manifest_service.MANIFEST_FILENAME).is_file():
        # Die Pipeline traegt die normalisierte Fassung ein, die IM Arbeitsordner liegt. Deren Hash fuehrte in einen
        # anderen (leeren) Ordner: "Stimme merken" fand nie eine Stimme, Vorschlaege gab es nie.
        return audio.parent
    stat = audio.stat()
    schluessel = (str(audio.resolve()), stat.st_size, stat.st_mtime_ns)
    with _hash_sperre:
        bekannt = _hash_zwischenspeicher.get(schluessel)
    if bekannt is None:
        bekannt = manifest_service.compute_file_hash(audio)
        with _hash_sperre:
            _hash_zwischenspeicher[schluessel] = bekannt
    return manifest_service.get_work_dir_for_file(paths.get_work_dir(), bekannt)


def _stimmabdruecke(daten: dict[str, Any]) -> dict[str, list[float]]:
    ordner = arbeitsordner_der_aufnahme(daten)
    return sprecherprofil_service.lade_lauf_embeddings(ordner) if ordner is not None else {}


# ---------------------------------------------------------------- je Besprechung
@router.get("/besprechungen/{kennung}/sprecher/vorschlaege")
def vorschlaege(kennung: str, d: Dienste = Depends(dienste), wer: Angemeldet = Depends(angemeldet)) -> dict[str, Any]:
    """Bekannte Stimmen: je Sprecher ein Namensvorschlag aus den eigenen Profilen (``sicher``: deutlich erkannt)."""
    daten = _transkript_daten(besprechung_finden(d, wer, kennung).besprechung.transkript)
    gefunden = sprecherprofil_service.finde_vorschlaege(
        _stimmabdruecke(daten), sprecherprofil_service.lade_profile(profil_ordner(wer))
    )
    return {
        "vorschlaege": {sid: {"name": v["name"], "sicher": bool(v["sicher"])} for sid, v in gefunden.items()},
        "stimmen_vorhanden": bool(_stimmabdruecke(daten)),
    }


@router.get("/besprechungen/{kennung}/sprecher/{sprecher_id}/hoerprobe")
def hoerprobe(kennung: str, sprecher_id: str, d: Dienste = Depends(dienste), wer: Angemeldet = Depends(angemeldet)) -> FileResponse:
    transkript = besprechung_finden(d, wer, kennung).besprechung.transkript
    daten = _transkript_daten(transkript)
    _sprecher_pruefen(daten, sprecher_id)
    name = hashlib.sha256(f"{transkript.resolve()}|{sprecher_id}".encode()).hexdigest()[:20]
    ziel = paths.get_work_dir() / "hoerproben" / f"{name}.wav"
    if not ziel.is_file() or ziel.stat().st_mtime < transkript.stat().st_mtime:
        ziel.parent.mkdir(parents=True, exist_ok=True)
        try:
            sprecher_export_service.hoerprobe_erstellen(transkript, sprecher_id, ziel)
        except (sprecher_export_service.SprecherExportFehler, RuntimeError, OSError) as fehler:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(fehler)) from fehler
    return FileResponse(ziel, media_type="audio/wav")


@router.post("/besprechungen/{kennung}/sprecher/{sprecher_id}/profil", status_code=201)
def als_profil_merken(
    kennung: str, sprecher_id: str, daten: ProfilName, d: Dienste = Depends(dienste), wer: Angemeldet = Depends(angemeldet)
) -> dict[str, Any]:
    """Die Stimme dieses Sprechers merken, damit er in spaeteren Aufnahmen erkannt wird."""
    transkript_daten = _transkript_daten(besprechung_finden(d, wer, kennung).besprechung.transkript)
    _sprecher_pruefen(transkript_daten, sprecher_id)
    abdruck = _stimmabdruecke(transkript_daten).get(sprecher_id)
    if not abdruck:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Für diesen Sprecher liegt keine Stimme vor. Das geht nur bei Aufnahmen, die auf diesem Computer "
            "umgewandelt wurden und deren Audiodatei noch vorhanden ist.",
        )
    try:
        profil = sprecherprofil_service.profil_speichern(daten.name, abdruck, profil_ordner(wer))
    except sprecherprofil_service.ProfilFehler as fehler:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(fehler)) from fehler
    return {"id": profil["id"], "name": profil["name"]}


@router.post("/besprechungen/{kennung}/sprecher/{sprecher_id}/export")
def sprecher_exportieren(
    kennung: str, sprecher_id: str, d: Dienste = Depends(dienste), wer: Angemeldet = Depends(angemeldet)
) -> dict[str, Any]:
    """Audio (WAV) und Text (TXT) eines Sprechers in den Ordner der Besprechung schreiben."""
    besprechung = besprechung_finden(d, wer, kennung, aendern=True).besprechung
    _sprecher_pruefen(_transkript_daten(besprechung.transkript), sprecher_id)
    try:
        wav, txt = sprecher_export_service.sprecher_exportieren(besprechung.transkript, sprecher_id, besprechung.transkript.parent)
    except (sprecher_export_service.SprecherExportFehler, RuntimeError, OSError) as fehler:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(fehler)) from fehler
    return {"dateien": [{"name": p.name, "pfad": str(p)} for p in (wav, txt)]}


# ---------------------------------------------------------------- Profile
@router.get("/sprecherprofile")
def profile(wer: Angemeldet = Depends(angemeldet)) -> list[dict[str, Any]]:
    """Gemerkte Stimmen -- ohne die Stimmabdruecke selbst."""
    return [
        {"id": p["id"], "name": p["name"], "erstellt": p.get("erstellt", ""), "aktualisiert": p.get("aktualisiert", "")}
        for p in sprecherprofil_service.lade_profile(profil_ordner(wer))
    ]


@router.patch("/sprecherprofile/{profil_id}")
def profil_umbenennen(profil_id: str, daten: ProfilName, wer: Angemeldet = Depends(angemeldet)) -> dict[str, bool]:
    try:
        sprecherprofil_service.profil_umbenennen(profil_id, daten.name, profil_ordner(wer))
    except sprecherprofil_service.ProfilFehler as fehler:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(fehler)) from fehler
    return {"gespeichert": True}


@router.delete("/sprecherprofile/{profil_id}")
def profil_loeschen(profil_id: str, wer: Angemeldet = Depends(angemeldet)) -> dict[str, bool]:
    if not sprecherprofil_service.profil_loeschen(profil_id, profil_ordner(wer)):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Dieses Profil gibt es nicht.")
    return {"geloescht": True}
