"""Grafikkarte im Container: was Pflicht ist, und die Pruefungen zur Laufzeit.

Die Regeln selbst (welche Karte, welche Schritte, was ist ein Fehler) -- ohne einen einzigen Import aus
``services/``. So koennen ``ollama_service`` und ``pipeline_service`` sie benutzen, ohne einen Kreis ueber die
Startpruefung (``grafikkarte_service``) zu bilden, die ihrerseits Ollama und die Proben braucht. Das
Warum steht in ``grafikkarte_service``.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass

ART_VARIABLE = "PROTOKOLL_GRAFIKKARTE"
PFLICHT_VARIABLE = "PROTOKOLL_GRAFIKKARTE_PFLICHT"
KEINE = "keine"
ARTEN = (KEINE, "nvidia", "amd", "intel")


@dataclass(frozen=True)
class Erwartung:
    """Welche Schritte muessen auf der Karte laufen?"""

    transkription: bool = False
    sprechertrennung: bool = False
    sprachmodell: bool = False

    @property
    def irgendeine(self) -> bool:
        return self.transkription or self.sprechertrennung or self.sprachmodell


ERWARTUNGEN: dict[str, Erwartung] = {
    KEINE: Erwartung(),
    "nvidia": Erwartung(transkription=True, sprechertrennung=True, sprachmodell=True),
    "amd": Erwartung(transkription=True, sprechertrennung=True, sprachmodell=True),
    # CTranslate2 (Whisper) hat kein Rechenwerk fuer Intel-Karten; pyannote bleibt mit Whisper auf dem Prozessor.
    "intel": Erwartung(sprachmodell=True),
}


class GrafikkarteFehlt(RuntimeError):
    """Ein Schritt, der auf der Grafikkarte laufen muss, kann sie nicht nutzen."""


class EinstellungFalsch(ValueError):
    """``PROTOKOLL_GRAFIKKARTE`` oder ``PROTOKOLL_GRAFIKKARTE_PFLICHT`` hat einen unbekannten Wert."""


def _umgebung(umgebung: Mapping[str, str] | None) -> Mapping[str, str]:
    return os.environ if umgebung is None else umgebung


def art(umgebung: Mapping[str, str] | None = None) -> str:
    """Fuer welche Karte das Image gebaut ist. Ohne Angabe: ``keine``."""
    wert = (_umgebung(umgebung).get(ART_VARIABLE) or "").strip().lower() or KEINE
    if wert not in ARTEN:
        raise EinstellungFalsch(f"{ART_VARIABLE}: '{wert}' ist unbekannt (erlaubt: {', '.join(ARTEN)}).")
    return wert


def pflicht(umgebung: Mapping[str, str] | None = None) -> bool:
    """Muss die Karte genutzt werden? Vorgabe: ja, sobald das Image fuer eine Karte gebaut ist."""
    if art(umgebung) == KEINE:
        return False
    roh = (_umgebung(umgebung).get(PFLICHT_VARIABLE) or "").strip().lower()
    if not roh or roh in ("1", "true", "ja", "an", "yes", "on"):
        return True
    if roh in ("0", "false", "nein", "aus", "no", "off"):
        return False
    raise EinstellungFalsch(f"{PFLICHT_VARIABLE}: '{roh}' ist weder an noch aus (erlaubt: 1/0, ja/nein, an/aus).")


def erwartet(umgebung: Mapping[str, str] | None = None) -> Erwartung:
    """Was zur Laufzeit erzwungen wird: die Erwartung der Kartenart, aber nur mit Pflicht. Ein unbekannter Wert
    erzwingt hier nichts -- er faellt schon beim Start auf (``grafikkarte_service.startpruefung``), und ein
    laufender Auftrag soll daran nicht scheitern."""
    try:
        return ERWARTUNGEN[art(umgebung)] if pflicht(umgebung) else Erwartung()
    except EinstellungFalsch:
        return Erwartung()


# Hinweise je Kartenart, was auf dem Rechner fehlen kann. Sie stehen in jeder Fehlermeldung, damit niemand die
# README suchen muss.
ABHILFE: dict[str, str] = {
    "nvidia": (
        "Auf dem Rechner muessen der NVIDIA-Treiber und das NVIDIA Container Toolkit installiert sein, und der "
        "Container muss mit 'docker-compose.gpu.yml' gestartet werden (auf ARM64 zusaetzlich "
        "'docker-compose.gpu-arm.yml'). Test: 'docker run --rm --gpus all nvidia/cuda:12.6.3-base-ubuntu22.04 "
        "nvidia-smi'."
    ),
    "amd": (
        "Auf dem Rechner muss der amdgpu-Treiber geladen sein (/dev/kfd und /dev/dri vorhanden), und der Container "
        "muss mit 'docker-compose.amd.yml' gestartet werden; in der .env stehen VIDEO_GID und RENDER_GID "
        "('getent group video render'). Mit SELinux (Fedora, RHEL) braucht der Container "
        "'security_opt: label:disable'."
    ),
    "intel": (
        "Auf dem Rechner muss der Intel-Grafiktreiber (i915 oder xe) geladen sein (/dev/dri vorhanden), und der "
        "Container muss mit 'docker-compose.intel.yml' gestartet werden."
    ),
}


def abhilfe(kartenart: str) -> str:
    return ABHILFE.get(kartenart, "")


def pflichttext(kartenart: str) -> str:
    return (
        f"Dieses Image ist fuer eine Grafikkarte ({kartenart}) gebaut, und {PFLICHT_VARIABLE} ist an. "
        f"{abhilfe(kartenart)} Wer bewusst auf dem Prozessor rechnen will, setzt {PFLICHT_VARIABLE}=0."
    )


# ---------------------------------------------------------------- Laufzeit
def transkription_pruefen(geraet: str, umgebung: Mapping[str, str] | None = None) -> None:
    """Vor dem Laden von Whisper: Faellt die Transkription auf den Prozessor zurueck, obwohl sie auf der Karte
    laufen muss, bricht der Auftrag ab (die fertigen Abschnitte bleiben fuer "Fortsetzen" erhalten)."""
    if geraet != "cuda" and erwartet(umgebung).transkription:
        kartenart = art(umgebung)
        raise GrafikkarteFehlt(
            f"Die Transkription wuerde auf dem Prozessor laufen, die Grafikkarte ist nicht nutzbar. "
            f"{pflichttext(kartenart)}"
        )


def sprechertrennung_pruefen(geraet: str, umgebung: Mapping[str, str] | None = None, grund: str = "") -> None:
    """Wie ``transkription_pruefen`` fuer pyannote. ``grund``: warum es nicht die Karte ist (z. B. der Fehler des
    eigenen Prozesses auf der Karte)."""
    if geraet != "cuda" and erwartet(umgebung).sprechertrennung:
        kartenart = art(umgebung)
        zusatz = f" ({grund})" if grund else ""
        raise GrafikkarteFehlt(
            f"Die Sprechertrennung wuerde auf dem Prozessor laufen{zusatz}. {pflichttext(kartenart)}"
        )


def sprachmodell_text(modell: str, groesse: int, auf_karte: int) -> tuple[bool, str]:
    """Bewertet einen Eintrag aus Ollamas ``/api/ps``: ganz, teilweise oder gar nicht im Grafikspeicher."""
    gb = 1024**3
    if auf_karte <= 0:
        return False, f"{modell} liegt ganz im Arbeitsspeicher (Ollama rechnet auf dem Prozessor)"
    if groesse > 0 and auf_karte < groesse:
        anteil = auf_karte / groesse * 100
        return True, (
            f"{modell}: {auf_karte / gb:.1f} von {groesse / gb:.1f} GB im Grafikspeicher ({anteil:.0f} %, der Rest "
            "rechnet auf dem Prozessor -- ein kleineres Modell oder eine kleinere Kontextgroesse waere schneller)"
        )
    return True, f"{modell}: {auf_karte / gb:.1f} GB im Grafikspeicher"


def sprachmodell_nachpruefen(
    modell: str,
    belegung: Callable[[str], tuple[int, int] | None],
    umgebung: Mapping[str, str] | None = None,
) -> None:
    """Nach einer Antwort von Ollama: Liegt das Modell ganz im Arbeitsspeicher, obwohl es auf der Karte laufen
    muss, ist das ein Fehler (``belegung`` liefert ``(groesse, im_grafikspeicher)`` oder ``None``, wenn das Modell
    nicht mehr geladen ist -- dann laesst sich nichts sagen)."""
    if not erwartet(umgebung).sprachmodell:
        return
    werte = belegung(modell)
    if werte is None:
        return
    ok, text = sprachmodell_text(modell, *werte)
    if not ok:
        raise GrafikkarteFehlt(f"{text}. {pflichttext(art(umgebung))}")
