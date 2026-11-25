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

Die Regeln und die Pruefungen zur Laufzeit stehen in ``grafikkarte_vorgabe`` (ohne Importe aus ``services/``,
damit ``ollama_service`` und ``pipeline_service`` sie benutzen koennen, ohne einen Importkreis zu bilden).
Dieses Modul enthaelt die Startpruefung. Die eigentlichen Pruefungen werden als Funktionen uebergeben, damit die
Tests ohne Grafikkarte laufen.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

from protokoll_assistent.services.grafikkarte_vorgabe import (
    ART_VARIABLE,
    ERWARTUNGEN,
    KEINE,
    PFLICHT_VARIABLE,
    EinstellungFalsch,
    art,
    pflicht,
    pflichttext,
    sprachmodell_text,
)


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
    return f"Die Grafikkarte ist fuer {', '.join(fehlend)} nicht nutzbar. {pflichttext(kartenart)}"


HERSTELLER_IDS = {"0x10de": "NVIDIA", "0x1002": "AMD", "0x8086": "Intel"}


def _lesen(datei: Path) -> str:
    try:
        return datei.read_text(encoding="ascii", errors="replace").strip().lower()
    except OSError:
        return ""


def _eintraege(ordner: Path) -> list[Path]:
    """Inhalt eines Ordners unter ``/sys``; fehlt er (Windows, kein PCI-Bus), ist er leer."""
    try:
        return list(ordner.iterdir())
    except OSError:
        return []


def karten_des_rechners(sys_ordner: Path = Path("/sys")) -> list[str]:
    """Hersteller der Grafikkarten des Rechners, so wie ``grafikkarte-erkennen.sh`` sie findet: PCI-Geraete der
    Klasse "Anzeige" und die Karten unter ``/sys/class/drm``. ``/sys`` ist auch im Container sichtbar (nur
    lesend), deshalb bemerkt das Prozessor-Image, wenn die Erkennung vergessen wurde. Ohne ``/sys`` (Windows):
    leer."""
    gefunden = {
        _lesen(geraet / "vendor")
        for geraet in _eintraege(sys_ordner / "bus" / "pci" / "devices")
        if _lesen(geraet / "class").startswith("0x03")
    }
    gefunden |= {
        _lesen(karte / "device" / "vendor")
        for karte in _eintraege(sys_ordner / "class" / "drm")
        if karte.name.startswith("card") and "-" not in karte.name
    }
    return [name for kennung, name in HERSTELLER_IDS.items() if kennung in gefunden]


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
        vorhanden = karten_des_rechners()
        if vorhanden:
            ausgabe(
                f"WARNUNG: Auf diesem Rechner steckt eine Grafikkarte ({', '.join(vorhanden)}), die ungenutzt "
                "bleibt. Im Projektordner './grafikkarte-erkennen.sh' ausfuehren und mit "
                "'docker compose up -d --build' neu starten."
            )
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
