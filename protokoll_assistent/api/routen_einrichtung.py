"""Ersteinrichtung der Windows-Anwendung: was dieser Rechner kann, was es kostet, was gewaehlt ist -- und das
Herunterladen erst nach ausdruecklicher Zustimmung.

Dieselben Schritte wie frueher ``gui/ersteinrichtung.py`` (Willkommen, Ihr Computer, Arbeitsweise, Was noetig
ist, Einrichtung, Mitschrift, Fertig), nur ohne Fenster: Die Oberflaeche fuehrt durch die Seiten, dieser Dienst
liefert Zahlen und schreibt dieselben Einstellungen wie der alte Assistent. Was lange dauert (FFmpeg, Ollama,
Modelle), laeuft als Auftrag in der gemeinsamen Warteschlange -- mit Fortschritt, nie im HTTP-Aufruf.

Regeln, die hier gelten (CLAUDE.md):

* Ohne Zustimmung wird nichts geladen: Jeder Endpunkt, der etwas herunterlaedt, verlangt ``zustimmung: true``
  im Aufruf. Die schwere Rechenumgebung (PyTorch & Co.) richtet ``bootstrap.py`` beim naechsten Start des
  Dienstes ein -- aber nur, wenn ``einrichtung_fortsetzen`` gesetzt ist (Zustimmung) und die Einrichtung nicht
  zurueckgestellt ist (``bootstrap.laufzeit_beim_start_einrichten``).
* Ollama wird nie mitgeliefert, sondern vom Hersteller geladen, auf Echtheit geprueft und still fuer das eigene
  Konto installiert (``services/ollama_einrichtung_service.py``).
* Nur in der Windows-Anwendung (Rolle ``desktop``); der Servermodus bringt seine Pakete im Container mit.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status

from protokoll_assistent.ablauf.auftraege import ERLEDIGT, AuftragAbgebrochen, Fortschritt
from protokoll_assistent.api import modelle
from protokoll_assistent.api.kontext import Angemeldet, Dienste, dienste, nur_admin, nur_desktop
from protokoll_assistent.services import (
    api_anbieter,
    einrichtungsplan_service,
    ffmpeg_service,
    model_download_service,
    model_service,
    ollama_einrichtung_service,
    ollama_service,
    rechner_analyse_service,
    secret_store,
)
from protokoll_assistent.services.rechner_analyse_service import Analyse, RechnerProfil
from protokoll_assistent.utils import app_config, hf_env, paths

router = APIRouter(prefix="/api/einrichtung", tags=["einrichtung"], dependencies=[Depends(nur_desktop)])

# Wert von 'einrichtung_fortsetzen': zugestimmt, die Rechenumgebung beim naechsten Start einzurichten.
FORTSETZEN_TRANSKRIPTION = "transkription"
# Arten der Auftraege dieser Seite (die Oberflaeche erkennt sie daran wieder, auch nach einem Neuladen).
ART_FFMPEG = "einrichtung_ffmpeg"
ART_OLLAMA = "einrichtung_ollama"
ART_MODELLE = "einrichtung_modelle"
# Vorrang: wie das Laden eines Ollama-Modells -- eine laufende Verarbeitung geht vor.
VORRANG_EINRICHTUNG = -5
# So oft wird ein Modell-Download versucht, wenn Ollama dabei wegfaellt (wie im alten Assistenten).
MODELL_VERSUCHE = 3
# Annahme fuer die Downloaddauer: eine uebliche Internetverbindung.
UEBLICHE_MBIT = 50

BEREICHE = {
    "transkription": "transkription_modus",
    "nachbearbeitung": "nachbearbeitung_modus",
    "chatbot": "chatbot_modus",
}
_SCHRITT_KENNUNG = {
    einrichtungsplan_service.SCHRITT_MITSCHRIFT: "mitschrift",
    einrichtungsplan_service.SCHRITT_SPRECHER: "sprecher",
    einrichtungsplan_service.SCHRITT_PROTOKOLL: "protokoll",
    einrichtungsplan_service.SCHRITT_CHAT: "chat",
}
_BEREICH_KENNUNG = {
    rechner_analyse_service.BEREICH_TRANSKRIPTION: "transkription",
    rechner_analyse_service.BEREICH_NACHBEARBEITUNG: "nachbearbeitung",
    rechner_analyse_service.BEREICH_SUCHE: "suche",
}


# --------------------------------------------------------------------------
# Was ist schon da? (fragt nur Platte, Registry und den lokalen Ollama-Dienst -- nie das Internet)
# --------------------------------------------------------------------------
def laufzeit_eingerichtet() -> bool:
    """Liegt die Rechenumgebung vollstaendig auf der Platte (auch wenn dieser Prozess nicht in ihr laeuft)?"""
    from protokoll_assistent import bootstrap

    return bootstrap.laufzeit_eingerichtet()


def _modell_da(name: str, vorhanden: set[str]) -> bool:
    return name in vorhanden or (":" not in name and f"{name}:latest" in vorhanden)


def _sprachmodelle(konfig: dict[str, Any]) -> tuple[str, str]:
    """(Sprachmodell, Einbettungsmodell) fuer die gewaehlte Arbeitsweise -- wie im alten Assistenten."""
    sprache = konfig["ollama_modell"] if konfig["nachbearbeitung_modus"] == "lokal" else konfig["chatbot_ollama_modell"]
    return sprache or ollama_service.DEFAULT_MODEL, konfig["chatbot_embedding_modell"]


def _whisper_modell(konfig: dict[str, Any]) -> str:
    return str(konfig.get("whisper_modell") or model_service.WHISPER_MODEL_NAME)


def _vorhanden(d: Dienste, konfig: dict[str, Any]) -> dict[str, Any]:
    ollama = ollama_einrichtung_service.ermittle_status()
    installiert: list[str] = []
    if ollama.dienst_laeuft:
        try:
            installiert = list(ollama_service.list_models(timeout=3))
        except ollama_service.OllamaError:
            installiert = []
    im_prozess = d.steuerung.abh.laufzeit_verfuegbar()
    sprache, einbettung = _sprachmodelle(konfig)
    namen = set(installiert)
    return {
        "ffmpeg": ffmpeg_service.find_ffmpeg() is not None,
        "ollama": ollama.installiert,
        "ollama_laeuft": ollama.dienst_laeuft,
        "ollama_version": ollama.version,
        "ollama_modelle": installiert,
        "laufzeit": im_prozess or laufzeit_eingerichtet(),
        "laufzeit_aktiv": im_prozess,
        "sprachmodell": _modell_da(sprache, namen),
        "einbettung": _modell_da(einbettung, namen),
        # Ohne Rechenumgebung in diesem Prozess laesst sich das nicht pruefen: dann "nein".
        "whisper": im_prozess and model_download_service.whisper_schon_geladen(_whisper_modell(konfig)),
        "pyannote": im_prozess and model_download_service.pyannote_schon_geladen(),
        "hf_token": hf_env.has_hf_token(),
    }


def _bausteine(
    konfig: dict[str, Any], vorhanden: dict[str, Any], profil: RechnerProfil, arbeitsweise: dict[str, str] | None = None
) -> list[einrichtungsplan_service.Baustein]:
    wahl = arbeitsweise or {bereich: konfig[schluessel] for bereich, schluessel in BEREICHE.items()}
    sprache, einbettung = _sprachmodelle({**konfig, "nachbearbeitung_modus": wahl["nachbearbeitung"]})
    return einrichtungsplan_service.bausteine_fuer(
        transkription_lokal=wahl["transkription"] == "lokal",
        nachbearbeitung_lokal=wahl["nachbearbeitung"] == "lokal",
        chat_lokal=wahl["chatbot"] == "lokal",
        cuda_gpu=profil.cuda_gpu,
        amd_rocm=profil.amd_rocm,
        whisper_modell=_whisper_modell(konfig),
        sprachmodell=sprache,
        einbettungsmodell=einbettung,
        vorhanden={k: bool(vorhanden.get(k)) for k in ("ffmpeg", "ollama", "laufzeit", "sprachmodell", "einbettung", "whisper", "pyannote")},
    )


def _neustart(konfig: dict[str, Any], vorhanden: dict[str, Any]) -> tuple[bool, bool]:
    """(Rechenumgebung fehlt noch auf der Platte, Neustart des Dienstes noetig).

    Neu starten muss der Dienst, wenn die Mitschrift lokal laufen soll, dieser Prozess die Rechenumgebung aber
    nicht hat -- und entweder liegt sie schon auf der Platte (dann wechselt ``bootstrap`` nur hinein) oder der
    Anwender hat dem Einrichten zugestimmt."""
    lokal = konfig["transkription_modus"] == "lokal"
    fehlt = lokal and not vorhanden["laufzeit"]
    zugestimmt = konfig.get("einrichtung_fortsetzen") == FORTSETZEN_TRANSKRIPTION
    noetig = lokal and not vorhanden["laufzeit_aktiv"] and (vorhanden["laufzeit"] or zugestimmt)
    return fehlt, noetig


def _online_ohne_anbieter(konfig: dict[str, Any]) -> list[str]:
    endpunkte = {
        "transkription": "api_transkription_endpunkt",
        "nachbearbeitung": "api_nachbearbeitung_endpunkt",
        "chatbot": "chatbot_api_endpunkt",
    }
    return [b for b, schluessel in BEREICHE.items() if konfig[schluessel] == "api" and not konfig[endpunkte[b]]]


def _einrichtungs_auftraege(d: Dienste) -> list[dict[str, Any]]:
    return [a.als_dict() for a in d.steuerung.auftraege.liste() if a.art.startswith("einrichtung_")]


def _naechster_schritt(konfig: dict[str, Any], vorhanden: dict[str, Any]) -> str:
    if konfig.get("einrichtung_fortsetzen") == FORTSETZEN_TRANSKRIPTION:
        # Nach dem Neustart in der Rechenumgebung: weiter mit den Modellen fuer die Mitschrift -- auch wenn die
        # Einrichtung schon abgeschlossen wurde und der Neustart erst spaeter kam.
        if vorhanden["laufzeit_aktiv"]:
            return "mitschrift"
        return "fertig" if konfig.get("einrichtung_abgeschlossen") else "neustart"
    if konfig.get("einrichtung_abgeschlossen"):
        return "fertig"
    return "willkommen"


def _stand(d: Dienste) -> dict[str, Any]:
    konfig = d.steuerung.konfiguration()
    vorhanden = _vorhanden(d, konfig)
    fehlt, neustart = _neustart(konfig, vorhanden)
    sprache, einbettung = _sprachmodelle(konfig)
    return {
        "einrichtung_abgeschlossen": bool(konfig.get("einrichtung_abgeschlossen")),
        "naechster_schritt": _naechster_schritt(konfig, vorhanden),
        "einrichtung_fortsetzen": str(konfig.get("einrichtung_fortsetzen") or ""),
        "lokale_einrichtung_zurueckgestellt": bool(konfig.get("lokale_einrichtung_zurueckgestellt")),
        "arbeitsweise": {bereich: konfig[schluessel] for bereich, schluessel in BEREICHE.items()},
        "modelle": {
            "whisper": _whisper_modell(konfig),
            "sprachmodell": sprache,
            "chat_sprachmodell": konfig["chatbot_ollama_modell"],
            "einbettung": einbettung,
        },
        "vorhanden": vorhanden,
        "offen": [b.kennung for b in _bausteine(konfig, vorhanden, RechnerProfil()) if not b.vorhanden],
        "rechenumgebung_fehlt": fehlt,
        "neustart_noetig": neustart,
        "online_ohne_anbieter": _online_ohne_anbieter(konfig),
        "geraete": len([g for g in konfig.get("geraete_empfang_geraete") or [] if isinstance(g, dict)]),
        "geraete_empfang_aktiv": bool(konfig.get("geraete_empfang_aktiv")),
        "auftraege": _einrichtungs_auftraege(d),
    }


def _speichern(d: Dienste, **aenderungen: Any) -> dict[str, Any]:
    """Wie ``PATCH /api/einstellungen``: schreiben, Folgeaufrufe (Empfang usw.), Ereignis an die Oberflaeche."""
    neu = app_config.update_config(**aenderungen)
    for aufruf in d.nach_einstellungen:
        aufruf(neu)
    d.steuerung.bus.senden("einstellungen", {"geaendert": sorted(aenderungen)})
    return neu


# --------------------------------------------------------------------------
# Rechner-Analyse (einmal je Dienst; mit ?neu=true erneut)
# --------------------------------------------------------------------------
def analyse_ermitteln(ordner: Path) -> Analyse:
    """Hardware ansehen (Arbeitsspeicher, Grafikkarte, Platz) und alle Modelle dafuer bewerten. Laedt nichts."""
    return rechner_analyse_service.analysiere(rechner_analyse_service.ermittle_profil(ordner))


def _analyse(request: Request, d: Dienste, neu: bool = False) -> Analyse:
    gespeichert: Analyse | None = getattr(request.app.state, "einrichtung_analyse", None)
    if gespeichert is not None and not neu:
        return gespeichert
    try:
        analyse = analyse_ermitteln(d.ausgabe_basis())
    except Exception:  # Die Einrichtung darf daran nicht scheitern -- dann eben ohne Kenntnis der Hardware.
        analyse = rechner_analyse_service.analysiere(RechnerProfil())
    request.app.state.einrichtung_analyse = analyse
    return analyse


def _profil(profil: RechnerProfil) -> dict[str, Any]:
    return {
        "arbeitsspeicher_gb": profil.ram_gb,
        "prozessorkerne": profil.cpu_kerne,
        "grafikkarte": profil.gpu_name,
        "grafikspeicher_gb": profil.grafikspeicher_gb,
        "grafikkarte_integriert": profil.gpu_integriert,
        "nvidia_cuda": profil.cuda_gpu,
        "amd_rocm": profil.amd_rocm,
        "sprachmodell_auf_grafikkarte": profil.ollama_gpu,
        "freier_platz_gb": profil.freier_platz_gb,
        "beschreibung": rechner_analyse_service.beschreibe_profil(profil).splitlines(),
    }


# --------------------------------------------------------------------------
# Endpunkte (literale Pfade; es gibt hier keine Platzhalter)
# --------------------------------------------------------------------------
@router.get("/stand", response_model=modelle.EinrichtungStand)
def stand(d: Dienste = Depends(dienste)) -> dict[str, Any]:
    """Wo die Einrichtung steht: abgeschlossen?, naechster Schritt, Arbeitsweise, was schon da ist und was fuer
    die gewaehlte Arbeitsweise noch fehlt, laufende Einrichtungsauftraege. Laedt nichts."""
    return _stand(d)


@router.get("/rechner", response_model=modelle.EinrichtungRechner)
def rechner(request: Request, neu: bool = False, d: Dienste = Depends(dienste)) -> dict[str, Any]:
    """Seite "Ihr Computer": Hardware, je Arbeitsschritt "gut / maessig / nicht" mit Dauer als Zahlen, die
    Empfehlung (lokal / gemischt / online / keine) und die Modelle, die hier laufen. Laedt nichts."""
    analyse = _analyse(request, d, neu)
    moeglichkeiten = einrichtungsplan_service.schaetze(analyse)
    empfohlen = {_BEREICH_KENNUNG[b]: m for b, m in analyse.empfehlung.items() if b in _BEREICH_KENNUNG}

    def modellliste(bereich: str, optionen: list[Any]) -> list[dict[str, Any]]:
        bewertung = {b.modell_id: b for b in analyse.bewertungen if b.bereich == bereich}
        liste = []
        for option in optionen:
            b = bewertung.get(option.id)
            if b is None:
                continue
            liste.append(
                {
                    "id": option.id,
                    "name": option.label,
                    "groesse_gb": getattr(option, "groesse_gb", None),
                    "stufe": b.stufe,
                    "text": b.text,
                    "auf_grafikkarte": b.auf_grafikkarte,
                    "empfohlen": analyse.empfehlung.get(bereich) == option.id,
                }
            )
        return liste

    return {
        "profil": _profil(analyse.profil),
        "schritte": [
            {
                "kennung": _SCHRITT_KENNUNG[s.schritt],
                "name": s.schritt,
                "stufe": s.stufe,
                "text": s.text,
                "dauer_von": s.dauer_von,
                "dauer_bis": s.dauer_bis,
                "einheit": s.einheit,
                "ort": s.ort,
            }
            for s in moeglichkeiten.schritte
        ],
        "empfehlung": moeglichkeiten.empfehlung,
        "begruendung": moeglichkeiten.begruendung,
        "hinweise": list(analyse.hinweise),
        "empfohlene_modelle": empfohlen,
        "whisper_modelle": modellliste(rechner_analyse_service.BEREICH_TRANSKRIPTION, model_service.WHISPER_MODELLE),
        "sprachmodelle": modellliste(rechner_analyse_service.BEREICH_NACHBEARBEITUNG, ollama_service.OLLAMA_MODELLE),
        "einbettungsmodelle": modellliste(rechner_analyse_service.BEREICH_SUCHE, ollama_service.OLLAMA_EMBEDDING_MODELLE),
    }


@router.get("/kosten", response_model=modelle.EinrichtungKosten)
def kosten(
    request: Request,
    transkription: modelle.Modus | None = None,
    nachbearbeitung: modelle.Modus | None = None,
    chatbot: modelle.Modus | None = None,
    d: Dienste = Depends(dienste),
) -> dict[str, Any]:
    """Seite "Was noetig ist": Bausteine mit Download und Platz (GB), Summe, ungefaehre Downloaddauer. Ohne
    Angaben fuer die gespeicherte Arbeitsweise; mit ``transkription``/``nachbearbeitung``/``chatbot`` als
    Vorschau, ohne etwas zu speichern."""
    konfig = d.steuerung.konfiguration()
    wahl = {bereich: konfig[schluessel] for bereich, schluessel in BEREICHE.items()}
    for bereich, wert in (("transkription", transkription), ("nachbearbeitung", nachbearbeitung), ("chatbot", chatbot)):
        if wert is not None:
            wahl[bereich] = wert
    vorhanden = _vorhanden(d, konfig)
    profil = _analyse(request, d).profil
    bausteine = _bausteine(konfig, vorhanden, profil, wahl)
    download, platz = einrichtungsplan_service.summe(bausteine)
    minuten = einrichtungsplan_service.download_minuten(download, UEBLICHE_MBIT)
    ollama_noetig = any(b.kennung == "ollama" and not b.vorhanden for b in bausteine)
    laufzeit_noetig = any(b.kennung == "laufzeit" and not b.vorhanden for b in bausteine)
    return {
        "arbeitsweise": wahl,
        "bausteine": [
            {
                "kennung": b.kennung,
                "name": b.name,
                "download_gb": round(b.download_gb, 2),
                "platz_gb": round(b.platz_gb, 2),
                "hinweis": b.hinweis,
                "vorhanden": b.vorhanden,
            }
            for b in bausteine
        ],
        "download_gb": round(download, 2),
        "platz_gb": round(platz, 2),
        "download_minuten_von": round(minuten, 1),
        "download_minuten_bis": round(minuten * 1.3, 1),
        "annahme_mbit": UEBLICHE_MBIT,
        "freier_platz_gb": profil.freier_platz_gb,
        "platz_knapp": profil.freier_platz_gb is not None and download > 0 and profil.freier_platz_gb < platz + 2,
        "zustimmung_noetig": download > 0,
        "neustart_noetig": laufzeit_noetig or (wahl["transkription"] == "lokal" and not vorhanden["laufzeit_aktiv"]),
        "ollama_lizenz": {
            "lizenz_url": ollama_einrichtung_service.OLLAMA_LIZENZ_URL,
            "bedingungen_url": ollama_einrichtung_service.OLLAMA_BEDINGUNGEN_URL,
        }
        if ollama_noetig
        else None,
    }


@router.post("/entscheidung", response_model=modelle.EinrichtungStand)
def entscheidung(
    daten: modelle.EinrichtungEntscheidung,
    request: Request,
    d: Dienste = Depends(dienste),
    _a: Angemeldet = Depends(nur_admin),
) -> dict[str, Any]:
    """Seite "Arbeitsweise" (und die Zustimmung zur Rechenumgebung von "Was noetig ist"). Schreibt dieselben
    Einstellungen wie der alte Assistent. Ein Online-Dienst wird nie von selbst gewaehlt -- das entscheidet der
    Aufruf."""
    konfig = d.steuerung.konfiguration()
    if daten.whisper_modell is not None and model_service.get_whisper_model_option(daten.whisper_modell) is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Unbekanntes Whisper-Modell „{daten.whisper_modell}“.")
    if daten.sprachmodell is not None and ollama_service.get_modell_option(daten.sprachmodell) is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Unbekanntes Sprachmodell „{daten.sprachmodell}“.")
    aenderungen: dict[str, Any] = {
        "transkription_modus": daten.transkription,
        "nachbearbeitung_modus": daten.nachbearbeitung,
        "chatbot_modus": daten.chatbot,
    }
    if daten.transkription == "lokal":
        if daten.whisper_modell is not None:
            aenderungen["whisper_modell"] = daten.whisper_modell
        elif not konfig["whisper_modell"]:
            # Die Empfehlung der Seite "Ihr Computer" (sofern sie schon ermittelt ist -- hier wird nicht gerechnet).
            gespeichert: Analyse | None = getattr(request.app.state, "einrichtung_analyse", None)
            empfohlen = gespeichert.empfehlung.get(rechner_analyse_service.BEREICH_TRANSKRIPTION) if gespeichert else None
            if empfohlen:
                aenderungen["whisper_modell"] = empfohlen
    # Das gewaehlte Sprachmodell nur, wenn das Protokoll lokal laeuft, und nur dort, wo noch der Standard steht
    # (wie im alten Assistenten: eine eigene Wahl aus den Einstellungen bleibt).
    if daten.nachbearbeitung == "lokal" and daten.sprachmodell and daten.sprachmodell != ollama_service.DEFAULT_MODEL:
        for schluessel in ("ollama_modell", "chatbot_ollama_modell"):
            if konfig[schluessel] == ollama_service.DEFAULT_MODEL:
                aenderungen[schluessel] = daten.sprachmodell

    if daten.transkription == "lokal":
        im_prozess = d.steuerung.abh.laufzeit_verfuegbar()
        if im_prozess or laufzeit_eingerichtet():
            # Nichts zu laden: hoechstens in die vorhandene Umgebung wechseln.
            aenderungen["lokale_einrichtung_zurueckgestellt"] = False
            aenderungen["einrichtung_fortsetzen"] = "" if im_prozess else FORTSETZEN_TRANSKRIPTION
        elif daten.zustimmung_rechenumgebung:
            # Zugestimmt: Beim naechsten Start richtet 'bootstrap' die Rechenumgebung ein.
            aenderungen["lokale_einrichtung_zurueckgestellt"] = False
            aenderungen["einrichtung_fortsetzen"] = FORTSETZEN_TRANSKRIPTION
        else:
            # Ohne Zustimmung nie ungefragt gut 5 GB laden -- auch nicht, wenn die Einrichtung schon einmal
            # abgeschlossen war (dann schuetzte sonst nichts davor).
            aenderungen["lokale_einrichtung_zurueckgestellt"] = True
            aenderungen["einrichtung_fortsetzen"] = ""
    else:
        aenderungen["einrichtung_fortsetzen"] = ""
    _speichern(d, **aenderungen)
    return _stand(d)


def _zustimmung_pruefen(zustimmung: bool) -> None:
    if not zustimmung:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Ohne Ihre Zustimmung wird nichts heruntergeladen (zustimmung: true)."
        )


def _laufender(d: Dienste, art: str) -> dict[str, Any] | None:
    for auftrag in d.steuerung.auftraege.liste():
        if auftrag.art == art and auftrag.status not in ERLEDIGT:
            return auftrag.als_dict()
    return None


def _meldungen(fortschritt: Fortschritt, stufe: str) -> Any:
    def melden(text: str) -> None:
        fortschritt.meldung(text)
        fortschritt.stufe(stufe, text)

    return melden


def _bytes_fortschritt(fortschritt: Fortschritt) -> Any:
    def melden(fertig: Any, gesamt: Any) -> None:
        if gesamt:
            fortschritt.gesamt(float(fertig or 0) / float(gesamt))

    return melden


@router.post("/ffmpeg", status_code=201, response_model=modelle.Auftrag)
def ffmpeg(daten: modelle.EinrichtungZustimmung, d: Dienste = Depends(dienste), _a: Angemeldet = Depends(nur_admin)) -> dict[str, Any]:
    """FFmpeg (liest Audio- und Videodateien) als portable Fassung laden -- nur, wenn es fehlt. Als Auftrag."""
    _zustimmung_pruefen(daten.zustimmung)
    laufend = _laufender(d, ART_FFMPEG)
    if laufend is not None:
        return laufend

    def ausfuehren(fortschritt: Fortschritt) -> dict[str, Any]:
        melden = _meldungen(fortschritt, "ffmpeg")
        ffmpeg_service.ensure_ffmpeg_available(progress_cb=melden)
        if ffmpeg_service.find_ffmpeg() is None or ffmpeg_service.find_ffprobe() is None:
            raise RuntimeError("FFmpeg ließ sich nicht einrichten. Die Gründe stehen in den Meldungen.")
        return {"ffmpeg": True}

    return d.steuerung.auftraege.einreihen(ART_FFMPEG, "FFmpeg einrichten", ausfuehren, vorrang=VORRANG_EINRICHTUNG).als_dict()


def installer_ordner() -> Path:
    return paths.get_app_dir() / "runtime" / "installer"


@router.post("/ollama", status_code=201, response_model=modelle.Auftrag)
def ollama(daten: modelle.EinrichtungZustimmung, d: Dienste = Depends(dienste), _a: Angemeldet = Depends(nur_admin)) -> dict[str, Any]:
    """Ollama vom Hersteller laden, Signatur pruefen ("Ollama Inc."), still fuer das eigene Konto installieren und
    den Dienst starten. Ist Ollama schon installiert, wird nur gestartet. Als Auftrag mit Fortschritt (Bytes)."""
    _zustimmung_pruefen(daten.zustimmung)
    laufend = _laufender(d, ART_OLLAMA)
    if laufend is not None:
        return laufend

    def ausfuehren(fortschritt: Fortschritt) -> dict[str, Any]:
        e = ollama_einrichtung_service
        # Die Dienstfunktionen erst hier nachschlagen (nicht als Vorgabe beim Import): So lassen sie sich ersetzen.
        laeuft = e.installiere_ollama(
            installer_ordner(),
            _meldungen(fortschritt, "ollama"),
            _bytes_fortschritt(fortschritt),
            status_fn=e.ermittle_status,
            lade_fn=e.lade_installer,
            pruef_fn=e.pruefe_signatur,
            install_fn=e.installiere_still,
            warte_fn=e.warte_auf_dienst,
            abbrechen_fn=fortschritt.abbruch_gewuenscht,
            igpu_fn=e.igpu_freischalten,
        )
        if not laeuft:
            raise e.OllamaEinrichtungFehler(
                "Ollama ist installiert, antwortet aber nicht. Bitte Ollama einmal selbst starten (Startmenü) "
                "oder den Rechner neu starten."
            )
        return {"ollama": True}

    return d.steuerung.auftraege.einreihen(ART_OLLAMA, "Ollama einrichten", ausfuehren, vorrang=VORRANG_EINRICHTUNG).als_dict()


def _benoetigte_ollama_modelle(konfig: dict[str, Any], vorhanden: dict[str, Any]) -> list[str]:
    """Was die gewaehlte Arbeitsweise an Ollama-Modellen braucht und noch fehlt (wie der alte Assistent)."""
    nachbearbeitung_lokal = konfig["nachbearbeitung_modus"] == "lokal"
    chat_lokal = konfig["chatbot_modus"] == "lokal"
    sprache, einbettung = _sprachmodelle(konfig)
    namen = set(vorhanden.get("ollama_modelle") or [])
    modelle_: list[str] = []
    if (nachbearbeitung_lokal or chat_lokal) and not _modell_da(sprache, namen):
        modelle_.append(sprache)
    chat = konfig["chatbot_ollama_modell"]
    if chat_lokal and chat and chat != sprache and not _modell_da(chat, namen):
        modelle_.append(chat)
    if chat_lokal and not _modell_da(einbettung, namen):
        modelle_.append(einbettung)
    return modelle_


def _ollama_modell_laden(name: str, fortschritt: Fortschritt) -> None:
    def melden(text: str, fertig: Any, gesamt: Any) -> None:
        fortschritt.stufe(f"modell:{name}", f"{name}: {text}")
        if gesamt:
            fortschritt.gesamt(float(fertig or 0) / float(gesamt))

    # Faellt Ollama mitten im Download weg, startet der Dienst neu und der Download geht dort weiter, wo er war.
    for versuch in range(1, MODELL_VERSUCHE + 1):
        try:
            ollama_service.pull_model(name, progress_cb=melden)
            break
        except ollama_service.OllamaError as fehler:
            if versuch == MODELL_VERSUCHE or fortschritt.abbruch_gewuenscht():
                raise
            fortschritt.meldung(f"Der Download wurde unterbrochen ({fehler}). Ollama wird neu gestartet …")
            ollama_service.dienst_starten()
    # "Fertig" gilt erst, wenn das Modell wirklich da ist.
    if not ollama_service.is_model_available(name):
        raise ollama_service.OllamaError(f"{name} wurde nicht vollständig geladen.")


@router.post("/modelle", status_code=201, response_model=modelle.Auftrag)
def modelle_laden(
    daten: modelle.EinrichtungModelle, d: Dienste = Depends(dienste), _a: Angemeldet = Depends(nur_admin)
) -> dict[str, Any]:
    """Seiten "Einrichtung" und "Mitschrift": Sprachmodelle (Ollama), Spracherkennung (Whisper) und
    Sprechererkennung (pyannote) laden -- der Reihe nach, als ein Auftrag. Was einzeln gelang, steht waehrend
    und nach dem Lauf in ``angaben.teile``; scheitert etwas, endet der Auftrag mit ``fehler``."""
    _zustimmung_pruefen(daten.zustimmung)
    laufend = _laufender(d, ART_MODELLE)
    if laufend is not None:
        return laufend
    konfig = d.steuerung.konfiguration()
    if daten.sprachmodelle is None:
        ollama_modelle = _benoetigte_ollama_modelle(konfig, _vorhanden(d, konfig))
    else:
        ollama_modelle = [m.strip() for m in daten.sprachmodelle if m.strip()]
    whisper_modell: str | None = None
    if daten.whisper or daten.sprechertrennung:
        if not d.steuerung.abh.laufzeit_verfuegbar():
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "Für die Mitschrift auf diesem Computer fehlt noch die Rechenumgebung. Die App muss dafür erst "
                "neu starten.",
            )
    if daten.whisper:
        whisper_modell = daten.whisper_modell or _whisper_modell(konfig)
        if model_service.get_whisper_model_option(whisper_modell) is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Unbekanntes Whisper-Modell „{whisper_modell}“.")
        _speichern(d, whisper_modell=whisper_modell)
    token = (daten.hf_token or "").strip() or None
    gemerkt = False
    if daten.sprechertrennung:
        if token is None and not hf_env.has_hf_token():
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "Für die Sprechererkennung fehlt der Zugang zu Hugging Face (hf_token).",
            )
        if token is not None and daten.hf_token_merken:
            try:
                secret_store.save_api_key(hf_env.SCHLUESSEL_NAME, token)
                gemerkt = True
            except secret_store.SecretStoreUnavailableError:
                gemerkt = False  # gilt dann nur fuer diese Sitzung (download_pyannote setzt HF_TOKEN)
    if not ollama_modelle and whisper_modell is None and not daten.sprechertrennung:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Es ist nichts zu laden.")
    sprechertrennung = daten.sprechertrennung

    def ausfuehren(fortschritt: Fortschritt) -> dict[str, Any]:
        teile: dict[str, bool] = {}
        fehler: list[str] = []

        def ergebnis(kennung: str, ok: bool, grund: str = "") -> None:
            teile[kennung] = ok
            if not ok:
                fehler.append(f"{kennung.removeprefix('modell:')}: {grund}" if grund else kennung.removeprefix("modell:"))
            fortschritt.angaben(teile=dict(teile))

        def abbruch_pruefen() -> None:
            # Ein Ergebnis zurueckzugeben hiesse "fertig" -- obwohl der Rest nicht geladen wurde.
            if fortschritt.abbruch_gewuenscht():
                raise AuftragAbgebrochen("Modelle laden abgebrochen")

        for name in ollama_modelle:
            abbruch_pruefen()
            fortschritt.stufe(f"modell:{name}", f"{name} wird geladen …")
            try:
                _ollama_modell_laden(name, fortschritt)
                ergebnis(f"modell:{name}", True)
            except ollama_service.OllamaError as grund:
                fortschritt.meldung(str(grund))
                ergebnis(f"modell:{name}", False, str(grund))
        melden_whisper = _meldungen(fortschritt, "whisper")
        if whisper_modell is not None:
            abbruch_pruefen()
            fortschritt.stufe("whisper", f"Spracherkennung {whisper_modell} wird geladen …")
            ergebnis("whisper", bool(model_download_service.download_whisper_and_alignment(melden_whisper, model_name=whisper_modell)))
        if sprechertrennung:
            abbruch_pruefen()
            fortschritt.stufe("pyannote", "Sprechererkennung wird geladen …")
            ok = model_download_service.download_pyannote(_meldungen(fortschritt, "pyannote"), get_token=lambda: token)
            ergebnis("pyannote", bool(ok))
        if whisper_modell is not None or sprechertrennung:
            # Die Rechenumgebung steht -- ein weiterer Neustart ist nicht noetig. Erst hier: Nach einem Abbruch
            # (oben) wurden Whisper/pyannote gar nicht geladen, dann bleibt die Einrichtung offen.
            app_config.update_config(einrichtung_fortsetzen="")
        if fehler:
            raise RuntimeError("Nicht geklappt: " + "; ".join(fehler))
        return {"teile": teile}

    titel = "Modelle laden"
    angaben = {"ollama_modelle": ollama_modelle, "whisper": whisper_modell, "sprechertrennung": sprechertrennung, "hf_token_gemerkt": gemerkt}
    return d.steuerung.auftraege.einreihen(ART_MODELLE, titel, ausfuehren, vorrang=VORRANG_EINRICHTUNG, angaben=angaben).als_dict()


def _schluessel_ablegen(d: Dienste, name: str, wert: str, merken: bool) -> bool:
    """Wie ``PUT /api/einstellungen/schluessel/{name}``: gemerkt in der Anmeldeinformationsverwaltung oder nur fuer
    diese Sitzung. Der Wert verlaesst den Dienst nie wieder."""
    if merken:
        try:
            secret_store.save_api_key(name, wert)
            return True
        except secret_store.SecretStoreUnavailableError:
            pass
    d.steuerung.schluessel.fuer_sitzung(name, wert)
    return False


@router.post("/anbieter", response_model=modelle.EinrichtungAnbieterErgebnis)
def anbieter(
    daten: modelle.EinrichtungAnbieter, d: Dienste = Depends(dienste), _a: Angemeldet = Depends(nur_admin)
) -> dict[str, Any]:
    """Online-Dienst fuer einen Bereich: traegt Adresse und Modell des Anbieters ein (wie die Auswahl in den
    Einstellungen) und legt auf Wunsch den Schluessel ab. Die Liste der Anbieter: ``GET /api/einstellungen/anbieter``."""
    eigener = daten.anbieter == api_anbieter.ANBIETER_EIGENER
    gefunden = api_anbieter.finde_anbieter(daten.anbieter)
    if gefunden is None and not eigener:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Den Anbieter „{daten.anbieter}“ gibt es nicht.")
    aenderungen: dict[str, Any] = {}
    if daten.bereich == "transkription":
        if gefunden is not None and not gefunden.kann_transkription:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"{gefunden.name} bietet keine Transkription an.")
        endpunkt = daten.endpunkt or (gefunden.transkription_url() if gefunden else "")
        modell = daten.modell or (gefunden.transkription_modell if gefunden else "")
        aenderungen = {
            "api_transkription_voreinstellung": daten.anbieter,
            "api_transkription_endpunkt": endpunkt,
            "api_transkription_modell": modell,
            "api_transkription_anbieter": gefunden.diarisierung_anbieter if gefunden else "",
        }
        schluessel_name, merken_feld, eigener_feld = "transkription", "api_transkription_schluessel_merken", None
    elif daten.bereich == "nachbearbeitung":
        if gefunden is not None and not gefunden.kann_chat:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"{gefunden.name} bietet kein Sprachmodell an.")
        endpunkt = daten.endpunkt or (gefunden.chat_url() if gefunden else "")
        modell = daten.modell or (gefunden.chat_modell if gefunden else "")
        aenderungen = {
            "api_nachbearbeitung_voreinstellung": daten.anbieter,
            "api_nachbearbeitung_endpunkt": endpunkt,
            "api_nachbearbeitung_modell": modell,
        }
        schluessel_name, merken_feld = "nachbearbeitung", "api_nachbearbeitung_schluessel_merken"
        eigener_feld = "api_nachbearbeitung_eigener_schluessel"
    else:
        if gefunden is not None and not (gefunden.kann_chat and gefunden.kann_embeddings):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"{gefunden.name} bietet nicht Chat und Suche zusammen an.")
        endpunkt = daten.endpunkt or (gefunden.chat_url() if gefunden else "")
        modell = daten.modell or (gefunden.chat_modell if gefunden else "")
        aenderungen = {
            "chatbot_api_voreinstellung": daten.anbieter,
            "chatbot_api_endpunkt": endpunkt,
            "chatbot_api_modell": modell,
            "chatbot_api_embedding_endpunkt": daten.einbettung_endpunkt or (gefunden.embedding_url() if gefunden else ""),
            "chatbot_api_embedding_modell": daten.einbettung_modell or (gefunden.embedding_modell if gefunden else ""),
        }
        schluessel_name, merken_feld, eigener_feld = "chatbot", "chatbot_api_schluessel_merken", "chatbot_api_eigener_schluessel"
    if eigener and not (endpunkt and modell):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Für einen eigenen Endpunkt bitte Adresse und Modell angeben.")
    gemerkt = False
    wert = (daten.schluessel or "").strip()
    if wert:
        gemerkt = _schluessel_ablegen(d, schluessel_name, wert, daten.merken)
        aenderungen[merken_feld] = daten.merken
        if eigener_feld is not None:
            aenderungen[eigener_feld] = True
    _speichern(d, **aenderungen)
    return {
        "bereich": daten.bereich,
        "anbieter": daten.anbieter,
        "endpunkt": endpunkt,
        "modell": modell,
        "adresse_vollstaendig": api_anbieter.adresse_vollstaendig(endpunkt),
        "schluessel_vorhanden": d.steuerung.schluessel.vorhanden(schluessel_name),
        "gemerkt": gemerkt,
    }


@router.post("/spaeter", response_model=modelle.EinrichtungStand)
def spaeter(daten: modelle.EinrichtungSpaeter, d: Dienste = Depends(dienste), _a: Angemeldet = Depends(nur_admin)) -> dict[str, Any]:
    """"Spaeter einrichten": Ohne ``nicht_mehr_fragen`` aendert sich nichts (die Einrichtung erscheint beim
    naechsten Start wieder). Mit: gilt als abgeschlossen -- und ohne Zustimmung wird die Rechenumgebung
    zurueckgestellt, damit der naechste Start nichts ungefragt laedt."""
    for auftrag in d.steuerung.auftraege.liste():
        if auftrag.art.startswith("einrichtung_") and auftrag.status not in ERLEDIGT:
            d.steuerung.auftraege.abbrechen(auftrag.id)
    if daten.nicht_mehr_fragen:
        konfig = d.steuerung.konfiguration()
        aenderungen: dict[str, Any] = {"einrichtung_abgeschlossen": True, "einrichtung_fortsetzen": ""}
        zugestimmt = konfig.get("einrichtung_fortsetzen") == FORTSETZEN_TRANSKRIPTION
        if not zugestimmt and not d.steuerung.abh.laufzeit_verfuegbar() and not laufzeit_eingerichtet():
            aenderungen["lokale_einrichtung_zurueckgestellt"] = True
        _speichern(d, **aenderungen)
    return _stand(d)


@router.post("/abschliessen", response_model=modelle.EinrichtungStand)
def abschliessen(d: Dienste = Depends(dienste), _a: Angemeldet = Depends(nur_admin)) -> dict[str, Any]:
    """Seite "Fertig": Einrichtung abgeschlossen. ``neustart_noetig`` in der Antwort sagt, ob der Dienst fuer die
    lokale Mitschrift noch einmal starten muss ("Die App startet kurz neu"); ``online_ohne_anbieter``, wo noch
    Anbieter und Schluessel fehlen."""
    konfig = d.steuerung.konfiguration()
    zugestimmt = konfig.get("einrichtung_fortsetzen") == FORTSETZEN_TRANSKRIPTION
    braucht_laufzeit = (
        konfig["transkription_modus"] == "lokal" and not d.steuerung.abh.laufzeit_verfuegbar() and not laufzeit_eingerichtet()
    )
    _speichern(
        d,
        einrichtung_abgeschlossen=True,
        # Bleibt gesetzt, solange der Neustart fuer die zugestimmte Rechenumgebung noch aussteht.
        einrichtung_fortsetzen=FORTSETZEN_TRANSKRIPTION if zugestimmt and braucht_laufzeit else "",
        # Ohne Zustimmung laedt der naechste Start nichts.
        lokale_einrichtung_zurueckgestellt=braucht_laufzeit and not zugestimmt,
    )
    return _stand(d)
