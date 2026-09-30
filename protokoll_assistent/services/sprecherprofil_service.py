"""Dauerhafte Sprecherprofile: Stimmen merken und wiedererkennen.

Ein Profil ist ein Name plus der Mittelwert der Stimm-Embeddings, die pyannote
bei der Sprechertrennung ohnehin berechnet. Nach einer neuen Aufnahme werden
die Embeddings der erkannten Sprecher mit den gespeicherten Profilen
verglichen (``speaker_merge_service.cosine_similarity``) und Namen
*vorgeschlagen*. Uebernommen wird nichts ohne Bestaetigung.

Nur im lokalen Modus verfuegbar: Nur dort liefert pyannote die Embeddings.

Datenschutz: Ein Stimmabdruck ist ein biometrisches Datum. Die Profile
liegen ausschliesslich lokal (``utils.paths.get_sprecherprofile_dir``), werden
nicht versioniert, nicht ausgeliefert und nie uebertragen. Der Anwender kann
jedes Profil loeschen.
"""

from __future__ import annotations

import json
import tempfile
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from protokoll_assistent.services.manifest_service import _ersetzen_mit_wiederholung
from protokoll_assistent.services.speaker_merge_service import cosine_similarity
from protokoll_assistent.utils.paths import get_sprecherprofile_dir

PROFILDATEI = "profile.json"
EMBEDDINGS_DATEI = "sprecher_embeddings.json"
FORMAT_VERSION = 1

# Ab dieser Aehnlichkeit wird ein Name vorgeschlagen. Der Wert ist auf die
# pyannote-Embeddings noch nicht an echten Aufnahmen abgestimmt und deshalb
# hier zentral und leicht zu aendern.
STANDARD_SCHWELLE = 0.72
# Knapp ueber der Schwelle ist der Vorschlag unsicher (Fragezeichen, wird nur
# auf Klick uebernommen).
UNSICHERHEITSMARGE = 0.08


class ProfilFehler(ValueError):
    """Ungueltige Eingabe, mit lesbarer Meldung."""


def _ordner(ordner: Path | None) -> Path:
    return ordner if ordner is not None else get_sprecherprofile_dir()


def _jetzt() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def lade_profile(ordner: Path | None = None) -> list[dict[str, Any]]:
    """Liest die Profile. Eine fehlende oder beschaedigte Datei ergibt eine
    leere Liste -- die Anwendung soll wegen der Profile nie am Start
    scheitern."""
    datei = _ordner(ordner) / PROFILDATEI
    try:
        daten = json.loads(datei.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    profile = daten.get("profile") if isinstance(daten, dict) else None
    if not isinstance(profile, list):
        return []
    return [
        p
        for p in profile
        if isinstance(p, dict) and p.get("id") and p.get("name") and isinstance(p.get("embedding"), list)
    ]


def _speichere(profile: list[dict[str, Any]], ordner: Path | None) -> None:
    ziel_ordner = _ordner(ordner)
    ziel_ordner.mkdir(parents=True, exist_ok=True)
    ziel = ziel_ordner / PROFILDATEI
    # Atomar schreiben (Projektregel 1): erst unter Arbeitsnamen, dann ersetzen.
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=ziel_ordner, suffix=".tmp", delete=False
    ) as handle:
        json.dump({"version": FORMAT_VERSION, "profile": profile}, handle, ensure_ascii=False, indent=2)
        temp = Path(handle.name)
    _ersetzen_mit_wiederholung(temp, ziel)


def _name_pruefen(name: str) -> str:
    sauber = " ".join(name.split())
    if not sauber:
        raise ProfilFehler("Bitte einen Namen eingeben.")
    return sauber


def profil_speichern(name: str, embedding: list[float], ordner: Path | None = None) -> dict[str, Any]:
    """Legt ein Profil an. Gibt es den Namen schon (Gross-/Kleinschreibung
    egal), fliesst das neue Embedding in den Mittelwert des vorhandenen
    Profils ein -- die Wiedererkennung wird mit jeder Aufnahme besser."""
    sauber = _name_pruefen(name)
    if not embedding:
        raise ProfilFehler("Für diesen Sprecher liegt kein Stimmabdruck vor.")
    profile = lade_profile(ordner)
    vorhanden = next((p for p in profile if p["name"].casefold() == sauber.casefold()), None)
    if vorhanden is None:
        eintrag: dict[str, Any] = {
            "id": uuid.uuid4().hex,
            "name": sauber,
            "embedding": [float(x) for x in embedding],
            "anzahl_proben": 1,
            "erstellt": _jetzt(),
            "aktualisiert": _jetzt(),
        }
        profile.append(eintrag)
    else:
        if len(vorhanden["embedding"]) != len(embedding):
            raise ProfilFehler(
                "Der Stimmabdruck passt nicht zum gespeicherten Profil (anderes Modell). "
                "Bitte das Profil löschen und neu anlegen."
            )
        anzahl = int(vorhanden.get("anzahl_proben", 1))
        vorhanden["embedding"] = [
            (alt * anzahl + float(neu)) / (anzahl + 1) for alt, neu in zip(vorhanden["embedding"], embedding, strict=True)
        ]
        vorhanden["anzahl_proben"] = anzahl + 1
        vorhanden["aktualisiert"] = _jetzt()
        eintrag = vorhanden
    _speichere(profile, ordner)
    return eintrag


def profil_umbenennen(profil_id: str, neuer_name: str, ordner: Path | None = None) -> None:
    sauber = _name_pruefen(neuer_name)
    profile = lade_profile(ordner)
    for profil in profile:
        if profil["id"] != profil_id and profil["name"].casefold() == sauber.casefold():
            raise ProfilFehler(f"Es gibt bereits ein Profil „{sauber}“.")
    ziel = next((p for p in profile if p["id"] == profil_id), None)
    if ziel is None:
        raise ProfilFehler("Das Profil existiert nicht mehr.")
    ziel["name"] = sauber
    ziel["aktualisiert"] = _jetzt()
    _speichere(profile, ordner)


def profil_loeschen(profil_id: str, ordner: Path | None = None) -> bool:
    profile = lade_profile(ordner)
    uebrig = [p for p in profile if p["id"] != profil_id]
    if len(uebrig) == len(profile):
        return False
    _speichere(uebrig, ordner)
    return True


def finde_vorschlaege(
    embeddings: dict[str, list[float]],
    profile: list[dict[str, Any]],
    schwelle: float = STANDARD_SCHWELLE,
    unsicherheitsmarge: float = UNSICHERHEITSMARGE,
) -> dict[str, dict[str, Any]]:
    """Ordnet erkannten Sprechern Profile zu.

    Rueckgabe: ``{sprecher_id: {"profil_id", "name", "aehnlichkeit",
    "sicher"}}`` -- nur fuer Sprecher, deren beste Aehnlichkeit die Schwelle
    erreicht. Ein Profil wird pro Aufnahme hoechstens einem Sprecher
    vorgeschlagen (dem mit der groessten Aehnlichkeit); zwei Stimmen in
    einem Gespraech sind nie dieselbe Person.
    """
    kandidaten: list[tuple[float, str, dict[str, Any]]] = []
    for sprecher_id, embedding in embeddings.items():
        for profil in profile:
            if len(profil["embedding"]) != len(embedding):
                continue  # anderes Modell -- nicht vergleichbar
            wert = cosine_similarity(embedding, profil["embedding"])
            if wert >= schwelle:
                kandidaten.append((wert, sprecher_id, profil))
    kandidaten.sort(key=lambda k: k[0], reverse=True)

    ergebnis: dict[str, dict[str, Any]] = {}
    vergebene_profile: set[str] = set()
    for wert, sprecher_id, profil in kandidaten:
        if sprecher_id in ergebnis or profil["id"] in vergebene_profile:
            continue
        ergebnis[sprecher_id] = {
            "profil_id": profil["id"],
            "name": profil["name"],
            "aehnlichkeit": wert,
            "sicher": wert >= schwelle + unsicherheitsmarge,
        }
        vergebene_profile.add(profil["id"])
    return ergebnis


def speichere_lauf_embeddings(work_dir: Path, embeddings: dict[str, list[float]]) -> Path:
    """Legt die Embeddings dieses Laufs im Arbeitsordner ab (nicht in der
    Ausgabe), damit sich Sprecher spaeter als Profil speichern lassen."""
    work_dir.mkdir(parents=True, exist_ok=True)
    ziel = work_dir / EMBEDDINGS_DATEI
    ziel.write_text(json.dumps(embeddings), encoding="utf-8")
    return ziel


def lade_lauf_embeddings(work_dir: Path) -> dict[str, list[float]]:
    try:
        daten = json.loads((work_dir / EMBEDDINGS_DATEI).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(daten, dict):
        return {}
    return {str(k): [float(x) for x in v] for k, v in daten.items() if isinstance(v, list) and v}
