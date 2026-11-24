"""Geraeteautomatik: Empfang nach Einstellungen, automatische Verarbeitung, Rueckfrage am Geraet, Ollama-Wache."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from protokoll_assistent.ablauf import auftraege
from protokoll_assistent.ablauf import geraete_automatik as modul
from protokoll_assistent.ablauf.auftraege import Status
from protokoll_assistent.ablauf.geraete_automatik import Abhaengigkeiten, GeraeteAutomatik
from protokoll_assistent.services import geraete_empfang_service, live_service
from protokoll_assistent.tests.ablauf_hilfen import alle_auftraege_ausfuehren, steuerung_fuer_test

TOKEN_HASH = "a" * 64


class FalscherDienst:
    def __init__(self, ziel: Path, geraete: Any, *, port: int, scheitern: bool = False, **rueckrufe: Any):
        self.ziel = ziel
        self.geraete = geraete
        self.port = port
        self.rueckrufe = rueckrufe
        self.gestartet = False
        self.gestoppt = False
        self._scheitern = scheitern

    def starten(self) -> None:
        if self._scheitern:
            raise OSError(10048, "belegt")
        self.gestartet = True

    def stoppen(self) -> None:
        self.gestoppt = True

    def kontakte(self) -> dict[str, Any]:
        return {"Raum-1": "kontakt"}


class Umgebung:
    def __init__(self, tmp_path: Path, **konfig: Any):
        self.konfig: dict[str, Any] = {
            "ausgabeordner": str(tmp_path / "aus"),
            "eingabeordner": str(tmp_path / "ein"),
            "geraete_empfang_aktiv": True,
            "geraete_empfang_geraete": [{"name": "Raum-1", "token_sha256": TOKEN_HASH}],
            "geraete_live_auswertung_vorab": False,
            **konfig,
        }
        self.steuerung, self.pipeline = steuerung_fuer_test(self.konfig)
        self.dienste: list[FalscherDienst] = []
        self.nebenher = True
        self.ollama_laeuft = True
        self.ollama_startet = True
        self.modell_fehlt = False

        def fabrik(ziel: Path, geraete: Any, **kw: Any) -> FalscherDienst:
            dienst = FalscherDienst(ziel, geraete, scheitern=self.konfig.get("_scheitern", False), **kw)
            self.dienste.append(dienst)
            return dienst

        self.automatik = GeraeteAutomatik(
            self.steuerung,
            Abhaengigkeiten(
                dienst_fabrik=fabrik,
                nebenher_moeglich=lambda config: self.nebenher,
                transkribierer_fabrik=lambda m, s, d: lambda: lambda wav: [],
                ollama_laeuft=lambda: self.ollama_laeuft,
                ollama_starten=lambda: self.ollama_startet,
                modell_fehlt=lambda modell: self.modell_fehlt,
                arbeitsordner=lambda: tmp_path / "arbeit",
                standard_ziel=lambda: tmp_path / "aufnahmen",
            ),
        )
        self.audio = tmp_path / "ein" / "H5_001.opus"
        self.audio.parent.mkdir(parents=True, exist_ok=True)
        self.audio.write_bytes(b"OggS")

    def status(self, datei: str = "H5_001.opus") -> dict[str, Any]:
        return self.automatik.status.hole("Raum-1", datei) or {}


@pytest.fixture
def umgebung(tmp_path: Path) -> Umgebung:
    return Umgebung(tmp_path)


def test_empfang_starten_stoppen_und_neu(umgebung: Umgebung) -> None:
    a = umgebung.automatik
    a.anwenden()
    assert a.laeuft and umgebung.dienste[0].gestartet
    assert umgebung.dienste[0].port == geraete_empfang_service.STANDARD_PORT
    assert "bei_teil" in umgebung.dienste[0].rueckrufe
    a.anwenden()  # unveraendert: kein neuer Dienst
    assert len(umgebung.dienste) == 1
    assert a.kontakte() == {"Raum-1": "kontakt"}
    beschreibung = a.beschreibung()
    assert beschreibung["aktiv"] and beschreibung["geraete"] == 1
    umgebung.konfig["geraete_empfang_port"] = "9000"
    umgebung.konfig["geraete_live_aktiv"] = False
    a.anwenden()
    assert umgebung.dienste[0].gestoppt and umgebung.dienste[1].port == 9000
    assert "bei_teil" not in umgebung.dienste[1].rueckrufe
    umgebung.konfig["geraete_empfang_aktiv"] = False
    a.anwenden()
    assert not a.laeuft and a.beschreibung()["aktiv"] is False
    assert a.kontakte() == {}
    a.stoppen()


def test_neuer_kontakt_meldet_den_empfang(umgebung: Umgebung) -> None:
    # Die Seite "VERMERK Raum" laedt die Geraeteliste beim Ereignis "empfang" neu: Meldet sich ein Geraet (nach dem
    # Start oder nach einem Neustart des Empfangs), muss das Ereignis kommen, sonst bleibt es "Noch nicht verbunden".
    a = umgebung.automatik
    a.anwenden()
    ereignisse: list[str] = []
    umgebung.steuerung.bus.abonnieren(lambda e: ereignisse.append(e.art))
    umgebung.dienste[0].rueckrufe["bei_kontakt"]("Raum-1")
    assert ereignisse == ["empfang"]


def test_empfang_port_belegt(umgebung: Umgebung) -> None:
    umgebung.konfig["_scheitern"] = True
    umgebung.automatik.anwenden()
    assert not umgebung.automatik.laeuft
    assert umgebung.automatik.fehler is not None and umgebung.automatik.fehler_code == "port_belegt"
    assert umgebung.automatik.beschreibung()["fehler_code"] == "port_belegt"


def test_eingangsordner_nicht_erreichbar_ist_nicht_port_belegt(umgebung: Umgebung, tmp_path: Path) -> None:
    # Eingabeordner auf einem Laufwerk, das gerade fehlt: Das ist kein belegter Anschluss (sonst sucht man am Port).
    datei = tmp_path / "keine_ordner"
    datei.write_text("x", encoding="utf-8")
    umgebung.konfig["eingabeordner"] = str(datei / "eingang")
    umgebung.automatik.anwenden()
    assert not umgebung.automatik.laeuft
    assert umgebung.automatik.fehler_code == "ordner"
    assert str(datei / "eingang") in (umgebung.automatik.fehler or "")
    # Ist der Ordner wieder da, startet der Empfang beim naechsten Anwenden.
    umgebung.konfig["eingabeordner"] = str(tmp_path / "ein")
    umgebung.automatik.anwenden()
    assert umgebung.automatik.laeuft and umgebung.automatik.fehler_code is None


def test_port_auslegen() -> None:
    assert modul._port("abc") == geraete_empfang_service.STANDARD_PORT
    assert modul._port(70000) == geraete_empfang_service.STANDARD_PORT
    assert modul._port(1234) == 1234


def test_aufnahme_ohne_rueckfrage_wird_ganz_verarbeitet(umgebung: Umgebung) -> None:
    a = umgebung.automatik
    a.anwenden()
    dienst = umgebung.dienste[0]
    dienst.rueckrufe["bei_neuer_aufnahme"](umgebung.audio, "Raum-1")
    dienst.rueckrufe["bei_abschluss"]("Raum-1", "H5_001.opus", umgebung.audio)  # ohne Live-Sitzung: sofort bereit
    alle_auftraege_ausfuehren(umgebung.steuerung)
    arten = [(x.art, x.status, x.vorrang) for x in umgebung.steuerung.auftraege.liste()]
    assert arten == [
        ("transkription", Status.FERTIG, auftraege.VORRANG_GERAET),
        ("auswertung", Status.FERTIG, auftraege.VORRANG_GERAET),
    ]
    assert umgebung.status()["zustand"] == live_service.FERTIG
    assert umgebung.status()["meldung"] == "Transkription erfolgreich"
    assert a._frage_bereit("Raum-1", "H5_001.opus")
    assert "Transkription erfolgreich" in a.zuletzt


def test_rueckfrage_freigabe_geht_vor(umgebung: Umgebung) -> None:
    a = umgebung.automatik
    a.wuensche.merke("Raum-1", "H5_001.opus", None, True)
    a.aufnahme_bereit(umgebung.audio, "Raum-1", "H5_001.opus")
    alle_auftraege_ausfuehren(umgebung.steuerung)
    assert umgebung.status()["zustand"] == live_service.TRANSKRIPT
    assert a.wartende_freigaben() == [{"geraet": "Raum-1", "datei": "H5_001.opus", "pfad": str(umgebung.audio)}]
    # Ein anderer Auftrag wartet schon -- die Freigabe ueberholt ihn.
    umgebung.steuerung.auftraege.einreihen("andere", "andere", lambda f: {})
    a.zusammenfassung_gewuenscht("Raum-1", "H5_001.opus")
    a.zusammenfassung_gewuenscht("Raum-1", "H5_001.opus")  # doppelt harmlos
    a.zusammenfassung_abgelehnt("Raum-1", "H5_001.opus")  # "Ja" kam zuerst
    assert umgebung.steuerung.auftraege.ausfuehren_im_aufrufer()
    erledigt = [x for x in umgebung.steuerung.auftraege.liste() if x.status is Status.FERTIG]
    assert erledigt[-1].art == "auswertung" and erledigt[-1].vorrang == auftraege.VORRANG_FREIGABE
    alle_auftraege_ausfuehren(umgebung.steuerung)
    assert umgebung.status()["meldung"] == "Zusammenfassung fertig"
    assert a.wartende_freigaben() == []


def test_rueckfrage_abgelehnt(umgebung: Umgebung) -> None:
    a = umgebung.automatik
    a._wunsch("Raum-1", "H5_001.opus", None, True)
    a.aufnahme_bereit(umgebung.audio, "Raum-1", "H5_001.opus")
    alle_auftraege_ausfuehren(umgebung.steuerung)
    a.zusammenfassung_abgelehnt("Raum-1", "H5_001.opus")
    assert umgebung.status()["zustand"] == live_service.FERTIG
    assert "abgelehnt" in a.zuletzt
    assert [x.art for x in umgebung.steuerung.auftraege.liste()] == ["transkription"]


def test_weitergezogen_holt_nach_oder_schliesst_ab(umgebung: Umgebung) -> None:
    a = umgebung.automatik
    a._wunsch("Raum-1", "H5_001.opus", None, True)
    a.aufnahme_bereit(umgebung.audio, "Raum-1", "H5_001.opus")
    alle_auftraege_ausfuehren(umgebung.steuerung)
    a._wunsch("Raum-1", "H5_002.opus", None, True)  # neue Aufnahme: nach der alten fragt das Geraet nicht mehr
    nachholen = [x for x in umgebung.steuerung.auftraege.liste() if x.status is Status.WARTET]
    assert [x.vorrang for x in nachholen] == [auftraege.VORRANG_NACHHOLEN]
    alle_auftraege_ausfuehren(umgebung.steuerung)
    assert umgebung.status()["zustand"] == live_service.FERTIG

    zweite = umgebung.audio.with_name("H5_002.opus")
    zweite.write_bytes(b"OggS")
    umgebung.nebenher = False
    a.aufnahme_bereit(zweite, "Raum-1", "H5_002.opus")
    alle_auftraege_ausfuehren(umgebung.steuerung)
    a.geraet_weitergezogen("Raum-1", "H5_003.opus")
    assert umgebung.status("H5_002.opus")["zustand"] == live_service.FERTIG
    assert "Grafikspeicher" in a.zuletzt


def test_transkription_weitergezogen_waehrend_sie_lief(umgebung: Umgebung) -> None:
    a = umgebung.automatik
    a._wunsch("Raum-1", "H5_001.opus", None, True)
    a.aufnahme_bereit(umgebung.audio, "Raum-1", "H5_001.opus")
    a._wunsch("Raum-1", "H5_002.opus", None, True)  # noch vor dem Ende der Transkription
    alle_auftraege_ausfuehren(umgebung.steuerung)
    assert umgebung.status()["zustand"] == live_service.FERTIG
    assert [x.vorrang for x in umgebung.steuerung.auftraege.liste()][-1] == auftraege.VORRANG_NACHHOLEN


def test_fehlerfaelle(umgebung: Umgebung, tmp_path: Path) -> None:
    a = umgebung.automatik
    hinweise: list[str] = []
    umgebung.steuerung.bus.abonnieren(lambda e: hinweise.append(e.daten["text"]) if e.art == "hinweis" else None)
    assert a.aufnahme_bereit(tmp_path / "fehlt.opus", "Raum-1", "fehlt.opus") is None
    assert umgebung.status("fehlt.opus")["zustand"] == live_service.FEHLER
    assert hinweise

    umgebung.pipeline.transkription_fehler = RuntimeError("weg")
    a.aufnahme_bereit(umgebung.audio, "Raum-1", "H5_001.opus")
    alle_auftraege_ausfuehren(umgebung.steuerung)
    assert umgebung.status()["meldung"] == "Die Transkription ist fehlgeschlagen."

    umgebung.pipeline.transkription_fehler = None
    umgebung.pipeline.protokoll_fehler = "Modell antwortet nicht"
    a.aufnahme_bereit(umgebung.audio, "Raum-1", "H5_001.opus")
    alle_auftraege_ausfuehren(umgebung.steuerung)
    assert umgebung.status()["meldung"] == "Die Auswertung ist fehlgeschlagen."

    umgebung.pipeline.protokoll_fehler = None
    umgebung.steuerung.abh.modell_fehlt = lambda modell: True
    a.aufnahme_bereit(umgebung.audio, "Raum-1", "H5_001.opus")
    alle_auftraege_ausfuehren(umgebung.steuerung)
    assert umgebung.status()["meldung"].startswith("Auswertung nicht möglich")


def test_abbruch_wird_dem_geraet_gemeldet(umgebung: Umgebung) -> None:
    a = umgebung.automatik
    auftrag = a.aufnahme_bereit(umgebung.audio, "Raum-1", "H5_001.opus")
    assert auftrag is not None
    umgebung.steuerung.abbrechen(auftrag.id)
    assert umgebung.status()["meldung"] == "Die Transkription wurde abgebrochen."
    a._auswertung_beendet(auftrag, umgebung.audio, "Raum-1", "H5_001.opus", False)
    assert umgebung.status()["meldung"] == "Die Auswertung wurde abgebrochen."


def test_vorab_auswertung_und_live_ereignis(umgebung: Umgebung) -> None:
    umgebung.konfig["geraete_live_auswertung_vorab"] = True
    a = umgebung.automatik
    ereignisse: list[str] = []
    umgebung.steuerung.bus.abonnieren(lambda e: ereignisse.append(e.art))
    a._live_geaendert("Raum-1", "H5_001.opus", "Hallo", 12.0)
    a.aufnahme_bereit(umgebung.audio, "Raum-1", "H5_001.opus")
    alle_auftraege_ausfuehren(umgebung.steuerung)
    einstellungen = umgebung.pipeline.auswertungen[0]
    assert einstellungen.ohne_sprecher and einstellungen.vorab_auswertung is not None
    assert einstellungen.vorab_auswertung() is None
    assert {"live", "geraet_status", "empfang"} <= set(ereignisse)


def test_live_auswertung_lesen(umgebung: Umgebung) -> None:
    a = umgebung.automatik
    assert a._live_auswertung_lesen({"geraete_live_auswertung_vorab": False}) is None
    assert a._live_auswertung_lesen({"ollama_modell": "qwen"}) is not None
    api: dict[str, Any] = {"nachbearbeitung_modus": "api"}
    assert a._live_auswertung_lesen(api) is None
    api.update(api_nachbearbeitung_endpunkt="https://x.example/v1/chat/completions", api_nachbearbeitung_modell="m")
    assert a._live_auswertung_lesen(api) is None  # kein Schluessel
    umgebung.steuerung.schluessel.fuer_sitzung("transkription", "k")
    assert a._live_auswertung_lesen(api) is not None


def test_auftrag_des_geraets(umgebung: Umgebung, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(modul, "alle_vorlagen", lambda: {"Kurz": "Fasse kurz zusammen."})
    a = umgebung.automatik
    assert a._auftrag_des_geraets("Raum-1", "x") is None
    a.wuensche.merke("Raum-1", "x", "Kurz", False)
    assert a._auftrag_des_geraets("Raum-1", "x") == "Fasse kurz zusammen."


def test_ollama_wache(umgebung: Umgebung) -> None:
    a = umgebung.automatik
    hinweise: list[tuple[str, str]] = []
    umgebung.steuerung.bus.abonnieren(
        lambda e: hinweise.append((e.daten["stufe"], e.daten["text"])) if e.art == "hinweis" else None
    )
    a.ollama_pruefen()  # Ersteinrichtung nicht abgeschlossen: nichts
    assert hinweise == []
    umgebung.konfig["einrichtung_abgeschlossen"] = True
    umgebung.ollama_laeuft = False
    umgebung.ollama_startet = False
    a.ollama_pruefen()
    assert hinweise[-1][0] == "fehler"
    umgebung.ollama_startet = True
    a.ollama_pruefen()
    assert "neu gestartet" in hinweise[-1][1]
    umgebung.ollama_laeuft = True
    umgebung.modell_fehlt = True
    a.ollama_pruefen()
    a.ollama_pruefen()  # nur einmal melden
    assert sum("Sprachmodell für Zusammenfassungen fehlt" in text for _s, text in hinweise) == 1
    umgebung.modell_fehlt = False
    a.ollama_pruefen()
    assert hinweise[-1] == ("erledigt", "")
    umgebung.konfig["nachbearbeitung_modus"] = "api"
    assert not a.ollama_wird_gebraucht(umgebung.konfig)


def test_wache_faden_startet_und_stoppt(umgebung: Umgebung, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(modul, "OLLAMA_WACHE_SEKUNDEN", 0.01)
    a = umgebung.automatik
    a.wache_starten()
    a.wache_starten()
    a.stoppen()
    assert a._wache_faden is not None
    a._wache_faden.join(2)
    assert not a._wache_faden.is_alive()


def test_frage_beantworten_nutzt_unterlagen(umgebung: Umgebung, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    a = umgebung.automatik
    transkript = tmp_path / "t.json"
    transkript.write_text("{}", encoding="utf-8")
    a._ergebnis_merken("Raum-1", "x", transkript=transkript)
    gesehen: dict[str, Any] = {}

    def antwort(frage: str, unterlagen: list[Path], chat_fn: Any, ausgabe: str) -> str:
        gesehen.update(frage=frage, unterlagen=unterlagen, ausgabe=ausgabe)
        return "42"

    monkeypatch.setattr(modul.geraete_fragen, "antwort_aus_unterlagen", antwort)
    assert a._frage_beantworten("Wie viel?", "Raum-1", "x", "anzeige") == "42"
    assert gesehen["unterlagen"] == [transkript]
    monkeypatch.setattr(modul.geraete_fragen, "frage_verstehen", lambda ton, endung, **kw: "erkannt")
    assert a._frage_erkennen(b"ton", ".opus") == "erkannt"
