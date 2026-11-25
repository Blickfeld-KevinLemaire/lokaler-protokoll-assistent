"""Grafikkarte im Container: Pflicht statt stillem Ausweichen auf den Prozessor.

Auf dem Desktop ist das Ausweichen richtig: Ohne passende Karte rechnet die CPU, langsamer, aber vollstaendig.
Auf einem Server, fuer den eine Grafikkarte gekauft wurde, ist dasselbe ein Fehler, den niemand bemerkt -- die
Verarbeitung dauert nur ein Vielfaches. Deshalb gilt im Container:

* Das Image sagt, fuer welche Karte es gebaut ist (``PROTOKOLL_GRAFIKKARTE``: ``keine``, ``nvidia``, ``amd``,
  ``intel``; gesetzt im ``Dockerfile`` ueber das Build-Argument ``GRAFIKKARTE``).
* Daraus folgt, welche Schritte auf der Karte laufen muessen (``ERWARTUNGEN``). Bei Intel gibt es fuer die
  Transkription (CTranslate2) kein Rechenwerk auf der Karte; dort laeuft nur das Sprachmodell (Ollama ueber
  Vulkan) auf der Karte.
* Solange ``PROTOKOLL_GRAFIKKARTE_PFLICHT`` nicht ausdruecklich aus ist, startet der Dienst nicht, wenn ein
  erwarteter Schritt die Karte nicht nutzen kann (``startpruefung``), und ein Auftrag bricht ab, statt auf dem
  Prozessor weiterzurechnen (``transkription_pruefen``, ``sprechertrennung_pruefen``,
  ``sprachmodell_nachpruefen``).

Ohne ``PROTOKOLL_GRAFIKKARTE`` (Windows-Anwendung, Tests) ist nichts Pflicht und alles bleibt wie bisher.

Die eigentlichen Pruefungen werden als Funktionen uebergeben, damit die Tests ohne Grafikkarte laufen.
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
    erzwingt hier nichts -- er faellt schon beim Start auf (``startpruefung``), und ein laufender Auftrag soll
    daran nicht scheitern."""
    try:
        return ERWARTUNGEN[art(umgebung)] if pflicht(umgebung) else Erwartung()
    except EinstellungFalsch:
        return Erwartung()


# ---------------------------------------------------------------- Pruefpunkte
@dataclass(frozen=True)
class Pruefpunkt:
    schritt: str
    erwartet: bool
    ok: bool
    meldung: str
    # Liess sich gar nicht pruefen (Ollama nicht erreichbar, Modell noch nicht heruntergeladen) -- das sagt nichts
    # ueber die Karte und wird deshalb getrennt gemeldet.
    offen: bool = False

    @property
    def fehler(self) -> bool:
        return self.erwartet and not self.ok and not self.offen


TRANSKRIPTION = "Transkription"
SPRECHERTRENNUNG = "Sprechertrennung"
SPRACHMODELL = "Sprachmodell"

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


def _pflichttext(kartenart: str) -> str:
    return (
        f"Dieses Image ist fuer eine Grafikkarte ({kartenart}) gebaut, und {PFLICHT_VARIABLE} ist an. "
        f"{abhilfe(kartenart)} Wer bewusst auf dem Prozessor rechnen will, setzt {PFLICHT_VARIABLE}=0."
    )


def startpruefung(
    umgebung: Mapping[str, str] | None = None,
    *,
    whisper_auf_karte: Callable[[], tuple[bool, str]],
    torch_auf_karte: Callable[[], tuple[bool, str]],
    sprachmodell_auf_karte: Callable[[], tuple[bool | None, str]] | None = None,
) -> list[Pruefpunkt]:
    """Prueft jeden Schritt, der fuer diese Kartenart auf der Karte laufen soll. ``sprachmodell_auf_karte`` darf
    ``None`` als Ergebnis liefern ("jetzt nicht pruefbar", etwa weil das Modell noch geladen wird) -- das zaehlt
    nicht als Fehler; zur Laufzeit prueft ``sprachmodell_nachpruefen`` nach jeder Antwort."""
    kartenart = art(umgebung)
    soll = ERWARTUNGEN[kartenart]
    punkte: list[Pruefpunkt] = []
    if kartenart == KEINE:
        return punkte
    ok, text = whisper_auf_karte()
    punkte.append(Pruefpunkt(TRANSKRIPTION, soll.transkription, ok, text))
    ok, text = torch_auf_karte()
    punkte.append(Pruefpunkt(SPRECHERTRENNUNG, soll.sprechertrennung, ok, text))
    if sprachmodell_auf_karte is not None:
        ergebnis, text = sprachmodell_auf_karte()
        punkte.append(Pruefpunkt(SPRACHMODELL, soll.sprachmodell, bool(ergebnis), text, offen=ergebnis is None))
    return punkte


def bericht(punkte: list[Pruefpunkt], kartenart: str, mit_pflicht: bool) -> str:
    """Lesbare Zusammenfassung fuer Log und Konsole."""
    zeilen = [f"Grafikkarte (Image fuer: {kartenart}, Pflicht: {'an' if mit_pflicht else 'aus'}):"]
    for punkt in punkte:
        if punkt.ok:
            zustand = "OK    "
        elif punkt.offen:
            zustand = "OFFEN "
        elif punkt.erwartet:
            zustand = "FEHLER"
        else:
            zustand = "CPU   "
        zeilen.append(f"  [{zustand}] {punkt.schritt}: {punkt.meldung}")
    return "\n".join(zeilen)


def fehlertext(punkte: list[Pruefpunkt], kartenart: str) -> str | None:
    """Meldung, wenn ein erwarteter Schritt die Karte nicht nutzen kann, sonst ``None``."""
    fehlend = [p.schritt for p in punkte if p.fehler]
    if not fehlend:
        return None
    return f"Die Grafikkarte ist fuer {', '.join(fehlend)} nicht nutzbar. {_pflichttext(kartenart)}"


def sprachmodell_pruefer(modell: str) -> Callable[[], tuple[bool | None, str]]:
    """Laedt das Sprachmodell bei Ollama und sieht nach, ob es im Grafikspeicher liegt. ``None`` als Ergebnis:
    jetzt nicht pruefbar (Ollama nicht erreichbar, Modell noch nicht heruntergeladen -- ``ollama-modell`` laeuft
    beim ersten Start parallel)."""

    def pruefen() -> tuple[bool | None, str]:
        from protokoll_assistent.services import ollama_service

        offen = None
        if not ollama_service.is_service_running():
            return offen, f"Ollama ist unter {ollama_service.OLLAMA_BASE_URL} nicht erreichbar"
        if ollama_service.modell_fehlt(modell):
            return offen, f"{modell} ist bei Ollama (noch) nicht vorhanden"
        try:
            ollama_service.modell_laden(modell)
        except ollama_service.OllamaError as fehler:
            return offen, f"{modell} laesst sich nicht laden: {fehler}"
        werte = ollama_service.modell_belegung(modell)
        if werte is None:
            return offen, f"{modell} ist nach dem Laden nicht in Ollamas Liste der geladenen Modelle"
        return sprachmodell_text(modell, *werte)

    return pruefen


def pruefen_und_melden(
    modell: str | None,
    *,
    streng: bool,
    ausgabe: Callable[[str], None],
    umgebung: Mapping[str, str] | None = None,
) -> bool:
    """Startpruefung mit den echten Pruefungen. Schreibt den Bericht ueber ``ausgabe`` und liefert, ob es
    weitergehen darf: ``False`` nur, wenn ein erwarteter Schritt die Karte nicht nutzen kann und die Pflicht an
    ist (``streng``: dann auch ohne Pflicht). ``modell``: das Ollama-Modell, ``None`` = nicht pruefen (etwa,
    weil die Zusammenfassung ueber einen Online-Dienst laeuft)."""
    from protokoll_assistent.services import grafikkarte_probe

    try:
        kartenart, mit_pflicht = art(umgebung), pflicht(umgebung)
    except EinstellungFalsch as fehler:
        ausgabe(str(fehler))
        return False
    if kartenart == KEINE:
        ausgabe(f"Grafikkarte: Dieses Image ist ohne Grafikkarte gebaut ({ART_VARIABLE}={KEINE}); alles rechnet "
                "auf dem Prozessor.")
        return True
    punkte = startpruefung(
        umgebung,
        # Je in einem eigenen Prozess: Ein Absturz der Karte darf den Dienst nicht wortlos mitnehmen.
        whisper_auf_karte=lambda: grafikkarte_probe.im_eigenen_prozess("transkription"),
        torch_auf_karte=lambda: grafikkarte_probe.im_eigenen_prozess("sprechertrennung"),
        sprachmodell_auf_karte=sprachmodell_pruefer(modell) if modell else None,
    )
    ausgabe(bericht(punkte, kartenart, mit_pflicht))
    offen = [p for p in punkte if p.offen and p.erwartet]
    if offen:
        # Beim Start kein Grund, nicht zu starten: Zur Laufzeit prueft 'sprachmodell_nachpruefen' jede Antwort.
        ausgabe(
            ("Nicht pruefbar" if streng else "Noch nicht pruefbar (wird bei der ersten Zusammenfassung geprueft)")
            + ": "
            + "; ".join(f"{p.schritt}: {p.meldung}" for p in offen)
        )
    meldung = fehlertext(punkte, kartenart)
    if meldung is None:
        return not (streng and offen)
    ausgabe(meldung)
    if mit_pflicht or streng:
        return False
    ausgabe(f"{PFLICHT_VARIABLE}=0: Der Dienst startet trotzdem, die genannten Schritte rechnen auf dem Prozessor.")
    return True


# ---------------------------------------------------------------- Laufzeit
def transkription_pruefen(geraet: str, umgebung: Mapping[str, str] | None = None) -> None:
    """Vor dem Laden von Whisper: Faellt die Transkription auf den Prozessor zurueck, obwohl sie auf der Karte
    laufen muss, bricht der Auftrag ab (die fertigen Abschnitte bleiben fuer "Fortsetzen" erhalten)."""
    if geraet != "cuda" and erwartet(umgebung).transkription:
        kartenart = art(umgebung)
        raise GrafikkarteFehlt(
            f"Die Transkription wuerde auf dem Prozessor laufen, die Grafikkarte ist nicht nutzbar. "
            f"{_pflichttext(kartenart)}"
        )


def sprechertrennung_pruefen(geraet: str, umgebung: Mapping[str, str] | None = None, grund: str = "") -> None:
    """Wie ``transkription_pruefen`` fuer pyannote. ``grund``: warum es nicht die Karte ist (z. B. der Fehler des
    eigenen Prozesses auf der Karte)."""
    if geraet != "cuda" and erwartet(umgebung).sprechertrennung:
        kartenart = art(umgebung)
        zusatz = f" ({grund})" if grund else ""
        raise GrafikkarteFehlt(
            f"Die Sprechertrennung wuerde auf dem Prozessor laufen{zusatz}. {_pflichttext(kartenart)}"
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
        raise GrafikkarteFehlt(f"{text}. {_pflichttext(art(umgebung))}")
