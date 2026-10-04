"""Tests fuer den Servermodus (``protokoll_assistent/server``) -- ohne ML, ohne Netz, ohne Fenster."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

from protokoll_assistent.server import dienst as dienst_modul
from protokoll_assistent.server import verarbeitung, warteschlange
from protokoll_assistent.server.__main__ import main, pruefe_umgebung
from protokoll_assistent.server.einstellungen import EinstellungsFehler, ServerEinstellungen
from protokoll_assistent.services import pipeline_service


# --------------------------------------------------------------------------
# Einstellungen
# --------------------------------------------------------------------------
def test_standardeinstellungen_aus_leerer_umgebung():
    e = ServerEinstellungen.aus_umgebung({})
    assert (e.eingang, e.ausgang) == (Path("/daten/eingang"), Path("/daten/ausgang"))
    assert (e.sprache, e.sprechertrennung, e.protokoll, e.modelle_laden, e.geraet) == ("de", True, True, True, "cuda")
    assert e.stabil_sekunden == 30.0 and e.abfrage_sekunden == 10.0 and e.export_formate == ()
    assert e.webhook_url == "" and e.min_sprecher is None


def test_einstellungen_aus_der_umgebung():
    e = ServerEinstellungen.aus_umgebung(
        {
            "PROTOKOLL_EINGANG": "/in",
            "PROTOKOLL_AUSGANG": "/out",
            "PROTOKOLL_STABIL_SEKUNDEN": "5,5",
            "PROTOKOLL_ABFRAGE_SEKUNDEN": "2",
            "PROTOKOLL_SPRACHE": "AUTO",
            "PROTOKOLL_WHISPER_MODELL": "small",
            "PROTOKOLL_OLLAMA_MODELL": "qwen3:4b",
            "PROTOKOLL_SPRECHERTRENNUNG": "nein",
            "PROTOKOLL_PROTOKOLL_ERSTELLEN": "0",
            "PROTOKOLL_MODELLE_LADEN": "aus",
            "PROTOKOLL_GERAET": "CPU",
            "PROTOKOLL_MIN_SPRECHER": "2",
            "PROTOKOLL_MAX_SPRECHER": "6",
            "PROTOKOLL_EXPORT_FORMATE": "md, TXT",
            "PROTOKOLL_WEBHOOK_URL": "https://geraet.test/fertig",
            "PROTOKOLL_WEBHOOK_TOKEN": " geheim ",
        }
    )
    assert (e.eingang, e.ausgang, e.stabil_sekunden, e.abfrage_sekunden) == (Path("/in"), Path("/out"), 5.5, 2.0)
    assert (e.sprache, e.whisper_modell, e.ollama_modell) == (None, "small", "qwen3:4b")
    assert (e.sprechertrennung, e.protokoll, e.modelle_laden, e.geraet) == (False, False, False, "cpu")
    assert (e.min_sprecher, e.max_sprecher, e.export_formate) == (2, 6, ("md", "txt"))
    assert (e.webhook_url, e.webhook_token) == ("https://geraet.test/fertig", "geheim")


@pytest.mark.parametrize(
    ("variable", "wert", "text"),
    [
        ("PROTOKOLL_SPRECHERTRENNUNG", "vielleicht", "weder an noch aus"),
        ("PROTOKOLL_STABIL_SEKUNDEN", "abc", "keine Zahl"),
        ("PROTOKOLL_ABFRAGE_SEKUNDEN", "0", "mindestens"),
        ("PROTOKOLL_GERAET", "tpu", "nicht erlaubt"),
        ("PROTOKOLL_EXPORT_FORMATE", "pdf", "gibt es im Server nicht"),
        ("PROTOKOLL_WEBHOOK_URL", "ftp://x", "http://"),
        ("PROTOKOLL_MIN_SPRECHER", "0", "mindestens"),
    ],
)
def test_ungueltige_einstellungen_werden_lesbar_gemeldet(variable, wert, text):
    with pytest.raises(EinstellungsFehler, match=text):
        ServerEinstellungen.aus_umgebung({variable: wert})


# --------------------------------------------------------------------------
# Warteschlange
# --------------------------------------------------------------------------
class _Uhr:
    def __init__(self, jetzt: float):
        self.jetzt = jetzt

    def __call__(self) -> float:
        return self.jetzt


def _datei(ordner: Path, name: str, inhalt: bytes = b"audio", alter: float = 3600.0, uhr: float | None = None) -> Path:
    pfad = ordner / name
    pfad.parent.mkdir(parents=True, exist_ok=True)
    pfad.write_bytes(inhalt)
    zeit = (uhr if uhr is not None else time.time()) - alter
    os.utime(pfad, (zeit, zeit))
    return pfad


def _beobachter(eingang: Path, stabil: float = 30.0, uhr=None, zustand=None):
    return warteschlange.Beobachter(
        eingang, stabil, zustand or warteschlange.Zustand(eingang.parent / "zustand.json"), jetzt=uhr or time.time
    )


def test_datei_wird_erst_bei_der_zweiten_unveraenderten_abfrage_freigegeben(tmp_path):
    eingang = tmp_path / "in"
    datei = _datei(eingang, "a.mp3")
    beobachter = _beobachter(eingang)
    assert beobachter.bereite_dateien() == []  # erste Abfrage: nur gemerkt
    assert beobachter.bereite_dateien() == [datei]


def test_wachsende_datei_wartet(tmp_path):
    eingang = tmp_path / "in"
    datei = _datei(eingang, "a.wav", b"123")
    beobachter = _beobachter(eingang)
    beobachter.bereite_dateien()
    datei.write_bytes(b"123456")  # Geraet schreibt noch
    os.utime(datei, (time.time() - 3600, time.time() - 3600))
    assert beobachter.bereite_dateien() == []
    assert beobachter.bereite_dateien() == [datei]


def test_frische_datei_wartet_bis_zur_stabilen_zeit(tmp_path):
    eingang = tmp_path / "in"
    uhr = _Uhr(1_000_000.0)
    datei = _datei(eingang, "a.mp3", alter=10.0, uhr=uhr.jetzt)
    beobachter = _beobachter(eingang, stabil=30.0, uhr=uhr)
    beobachter.bereite_dateien()
    assert beobachter.bereite_dateien() == []  # erst 10 s alt
    uhr.jetzt += 25
    assert beobachter.bereite_dateien() == [datei]


def test_nicht_passende_dateien_werden_ignoriert(tmp_path):
    eingang = tmp_path / "in"
    _datei(eingang, "notiz.txt")
    _datei(eingang, "a.mp3.part")
    _datei(eingang, "b.mp3.tmp")
    _datei(eingang, "~lock.mp3")
    _datei(eingang, ".versteckt.mp3")
    _datei(eingang, "leer.mp3", b"")
    _datei(eingang, warteschlange.ORDNER_VERARBEITET + "/alt.mp3")
    _datei(eingang, warteschlange.ORDNER_FEHLER + "/kaputt.mp3")
    (eingang / "ordner.mp3").mkdir()
    gut = _datei(eingang, "tag/gut.M4A")
    beobachter = _beobachter(eingang)
    beobachter.bereite_dateien()
    assert beobachter.bereite_dateien() == [gut]


def test_aelteste_zuerst_und_weg_gefallene_dateien_werden_vergessen(tmp_path):
    eingang = tmp_path / "in"
    neu = _datei(eingang, "neu.mp3", alter=100)
    alt = _datei(eingang, "alt.mp3", alter=5000)
    beobachter = _beobachter(eingang)
    beobachter.bereite_dateien()
    assert beobachter.bereite_dateien() == [alt, neu]
    alt.unlink()
    beobachter.bereite_dateien()
    assert alt not in beobachter._gesehen


def test_fehlender_eingangsordner_ist_kein_fehler(tmp_path):
    assert _beobachter(tmp_path / "gibt-es-nicht").bereite_dateien() == []


def test_zustand_ueberdauert_neustart_und_verhindert_doppelte_verarbeitung(tmp_path):
    eingang = tmp_path / "in"
    datei = _datei(eingang, "a.mp3")
    zustand = warteschlange.Zustand(tmp_path / "z" / "zustand.json")
    beobachter = _beobachter(eingang, zustand=zustand)
    schluessel = beobachter.schluessel(datei)
    assert schluessel is not None and schluessel.startswith("a.mp3|5|")
    zustand.merke(schluessel, "fertig", "/out/a")

    neu = _beobachter(eingang, zustand=warteschlange.Zustand(tmp_path / "z" / "zustand.json"))
    neu.bereite_dateien()
    assert neu.bereite_dateien() == []  # schon erledigt
    assert not list((tmp_path / "z").glob("*.tmp"))
    assert beobachter.schluessel(eingang / "weg.mp3") is None


def test_beschaedigter_zustand_wird_ignoriert(tmp_path):
    datei = tmp_path / "zustand.json"
    datei.write_text("{kaputt", encoding="utf-8")
    assert not warteschlange.Zustand(datei).bekannt("x")
    datei.write_text("[1]", encoding="utf-8")
    assert not warteschlange.Zustand(datei).bekannt("x")


def test_verschieben_behaelt_die_struktur_und_zaehlt_hoch(tmp_path):
    eingang = tmp_path / "in"
    erste = _datei(eingang, "tag/a.mp3")
    ziel = warteschlange.verschiebe_nach(erste, eingang, warteschlange.ORDNER_VERARBEITET)
    assert ziel == eingang / "verarbeitet" / "tag" / "a.mp3" and ziel.is_file() and not erste.exists()
    zweite = _datei(eingang, "tag/a.mp3")
    assert warteschlange.verschiebe_nach(zweite, eingang, warteschlange.ORDNER_VERARBEITET).name == "a_2.mp3"  # type: ignore[union-attr]
    # Datei ausserhalb des Eingangs: nur der Name zaehlt
    fremd = _datei(tmp_path, "fremd.mp3")
    assert warteschlange.verschiebe_nach(fremd, eingang, "fehler") == eingang / "fehler" / "fremd.mp3"


def test_verschieben_ohne_schreibrecht_gibt_none(tmp_path, monkeypatch):
    eingang = tmp_path / "in"
    datei = _datei(eingang, "a.mp3")

    def verweigern(self, ziel):
        raise PermissionError("schreibgeschuetzt")

    monkeypatch.setattr(Path, "replace", verweigern)
    assert warteschlange.verschiebe_nach(datei, eingang, "verarbeitet") is None


# --------------------------------------------------------------------------
# Verarbeitung
# --------------------------------------------------------------------------
class _PipelineErgebnis:
    def __init__(self, ausgabe: Path, mit_protokoll: bool = True, protokoll_fehler=None):
        transkript = ausgabe / "t.json"
        protokoll = ausgabe / "p.json"
        ausgabe.mkdir(parents=True, exist_ok=True)
        transkript.write_text(
            json.dumps(
                {
                    "quelldatei": "a.mp3",
                    "quelldatei_stamm": "a",
                    "sprechertrennung_aktiv": False,
                    "segmente": [{"start": "0", "start_sekunden": 0, "ende_sekunden": 1, "text": "Hallo", "sprecher": ""}],
                }
            ),
            encoding="utf-8",
        )
        self.export_paths = type("P", (), {"json": transkript})()
        self.protocol_paths = None
        self.protokoll_fehler = protokoll_fehler
        if mit_protokoll:
            protokoll.write_text(json.dumps({"titel": "Titel", "kurzzusammenfassung": "Kurz."}), encoding="utf-8")
            self.protocol_paths = (protokoll, ausgabe / "p.md")


def _einstellungen(tmp_path, **umgebung):
    return ServerEinstellungen.aus_umgebung(
        {"PROTOKOLL_EINGANG": str(tmp_path / "in"), "PROTOKOLL_AUSGANG": str(tmp_path / "out"), **umgebung}
    )


def test_verarbeitung_uebergibt_die_einstellungen_an_die_kette(tmp_path):
    aufgerufen = {}

    def kette(settings, callbacks):
        aufgerufen["settings"] = settings
        callbacks.on_stage("transkription", "Transkription laeuft")
        callbacks.on_log("Hinweis")
        aufgerufen["abbrechen"] = callbacks.should_cancel()
        return _PipelineErgebnis(settings.output_dir)

    meldungen: list[str] = []
    einstellungen = _einstellungen(
        tmp_path, PROTOKOLL_SPRACHE="en", PROTOKOLL_WHISPER_MODELL="small", PROTOKOLL_GERAET="cpu", PROTOKOLL_SPRECHERTRENNUNG="0"
    )
    datei = tmp_path / "in" / "a.mp3"
    ergebnis = verarbeitung.verarbeite(
        datei, einstellungen, pipeline_fn=kette, abbrechen=lambda: True, protokollieren=meldungen.append
    )

    s = aufgerufen["settings"]
    assert (s.source_path, s.language, s.whisper_modell if hasattr(s, "whisper_modell") else s.whisper_model) == (datei, "en", "small")
    assert (s.device_preference, s.enable_diarization, s.run_protocol, s.allow_download) == ("cpu", False, True, True)
    assert s.output_dir.parent == tmp_path / "out" and s.output_dir.name.startswith("a_")
    assert aufgerufen["abbrechen"] is True and meldungen == ["Transkription laeuft", "Hinweis"]
    assert ergebnis.status == verarbeitung.STATUS_FERTIG and ergebnis.ausgabe == s.output_dir
    daten = json.loads((ergebnis.ausgabe / verarbeitung.ERGEBNIS_DATEI).read_text(encoding="utf-8"))
    assert daten["status"] == "fertig" and daten["datei"] == "a.mp3" and "t.json" in daten["dateien"]
    assert verarbeitung.ERGEBNIS_DATEI not in daten["dateien"]


def test_zusaetzliche_formate_werden_geschrieben(tmp_path):
    einstellungen = _einstellungen(tmp_path, PROTOKOLL_EXPORT_FORMATE="md,txt")
    ergebnis = verarbeitung.verarbeite(
        tmp_path / "in" / "a.mp3", einstellungen, pipeline_fn=lambda s, c: _PipelineErgebnis(s.output_dir)
    )
    assert "a_gesamt.md" in ergebnis.dateien and "a_gesamt.txt" in ergebnis.dateien

    ohne_protokoll = verarbeitung.verarbeite(
        tmp_path / "in" / "b.mp3",
        einstellungen,
        pipeline_fn=lambda s, c: _PipelineErgebnis(s.output_dir, mit_protokoll=False),
    )
    assert "a_transkript.md" in ohne_protokoll.dateien


def test_fehlgeschlagenes_protokoll_ist_ein_teilerfolg(tmp_path):
    ergebnis = verarbeitung.verarbeite(
        tmp_path / "in" / "a.mp3",
        _einstellungen(tmp_path),
        pipeline_fn=lambda s, c: _PipelineErgebnis(s.output_dir, mit_protokoll=False, protokoll_fehler="Ollama weg"),
    )
    assert ergebnis.status == verarbeitung.STATUS_FERTIG and ergebnis.protokoll_fehler == "Ollama weg"


def test_fehler_der_kette_werden_zum_ergebnis(tmp_path):
    def kaputt(settings, callbacks):
        raise pipeline_service.PipelineError("Datei defekt")

    ergebnis = verarbeitung.verarbeite(tmp_path / "in" / "a.mp3", _einstellungen(tmp_path), pipeline_fn=kaputt)
    assert ergebnis.status == verarbeitung.STATUS_FEHLER and ergebnis.fehler == "Datei defekt"
    assert (ergebnis.ausgabe / verarbeitung.ERGEBNIS_DATEI).is_file()

    def stumm(settings, callbacks):
        raise RuntimeError()

    assert verarbeitung.verarbeite(tmp_path / "in" / "b.mp3", _einstellungen(tmp_path), pipeline_fn=stumm).fehler == "RuntimeError"


def test_abbruch_gibt_abgebrochen_ohne_ausgabe(tmp_path):
    def abbrechen(settings, callbacks):
        raise pipeline_service.PipelineCancelled("stopp")

    ergebnis = verarbeitung.verarbeite(tmp_path / "in" / "a.mp3", _einstellungen(tmp_path), pipeline_fn=abbrechen)
    assert ergebnis.status == verarbeitung.STATUS_ABGEBROCHEN and ergebnis.ausgabe is None
    assert not (tmp_path / "out").exists()


def test_ergebnis_schreiben_ohne_ausgabeordner_und_mit_schreibfehler(tmp_path, monkeypatch):
    verarbeitung._ergebnis_schreiben(verarbeitung.Ergebnis(verarbeitung.STATUS_ABGEBROCHEN, tmp_path / "a.mp3"))

    def verweigern(self, *a, **k):
        raise OSError("voll")

    monkeypatch.setattr(Path, "mkdir", verweigern)
    verarbeitung._ergebnis_schreiben(verarbeitung.Ergebnis(verarbeitung.STATUS_FERTIG, tmp_path / "a.mp3", tmp_path / "x"))


# --------------------------------------------------------------------------
# Webhook
# --------------------------------------------------------------------------
class _Antwort:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_webhook_sendet_json_mit_token():
    gesehen = {}

    def oeffnen(anfrage, timeout=None):
        gesehen["adresse"] = anfrage.full_url
        gesehen["kopf"] = dict(anfrage.headers)
        gesehen["koerper"] = json.loads(anfrage.data.decode("utf-8"))
        return _Antwort()

    assert verarbeitung.melde_webhook("https://x.test/h", {"status": "fertig"}, "tok", oeffnen=oeffnen) is None
    assert gesehen["adresse"] == "https://x.test/h" and gesehen["koerper"] == {"status": "fertig"}
    assert gesehen["kopf"]["Authorization"] == "Bearer tok"
    verarbeitung.melde_webhook("https://x.test/h", {}, oeffnen=lambda a, timeout=None: gesehen.update(kopf=dict(a.headers)) or _Antwort())
    assert "Authorization" not in gesehen["kopf"]


def test_webhook_fehler_werden_gemeldet_nicht_geworfen():
    import urllib.error

    def http_fehler(anfrage, timeout=None):
        raise urllib.error.HTTPError("u", 503, "x", {}, None)

    def netz_fehler(anfrage, timeout=None):
        raise urllib.error.URLError("nicht erreichbar")

    assert verarbeitung.melde_webhook("https://x.test", {}, oeffnen=http_fehler) == "HTTP 503"
    assert "nicht erreichbar" in (verarbeitung.melde_webhook("https://x.test", {}, oeffnen=netz_fehler) or "")


# --------------------------------------------------------------------------
# Dienst
# --------------------------------------------------------------------------
def _dienst(tmp_path, ergebnisse, **umgebung):
    einstellungen = _einstellungen(tmp_path, PROTOKOLL_STABIL_SEKUNDEN="0", **umgebung)
    aufrufe: list[Path] = []
    gemeldet: list[dict] = []

    def verarbeiten(datei, e, abbrechen=None, protokollieren=None):
        aufrufe.append(datei)
        status = ergebnisse.get(datei.name, verarbeitung.STATUS_FERTIG)
        return verarbeitung.Ergebnis(
            status, datei, tmp_path / "out" / datei.stem, fehler="kaputt" if status == verarbeitung.STATUS_FEHLER else None
        )

    dienst = dienst_modul.Dienst(
        einstellungen,
        tmp_path / "zustand.json",
        verarbeiten=verarbeiten,
        webhook=lambda url, nutzlast, token="": gemeldet.append({"url": url, **nutzlast}) or None,
        schlafen=lambda s: None,
    )
    return dienst, aufrufe, gemeldet


def test_dienst_verarbeitet_und_raeumt_auf(tmp_path):
    eingang = tmp_path / "in"
    gut = _datei(eingang, "gut.mp3")
    schlecht = _datei(eingang, "schlecht.mp3", alter=7200)
    dienst, aufrufe, gemeldet = _dienst(
        tmp_path, {"schlecht.mp3": verarbeitung.STATUS_FEHLER}, PROTOKOLL_WEBHOOK_URL="https://x.test/h"
    )
    assert dienst.einmal() == 0  # erste Abfrage: Dateien erst merken
    assert dienst.einmal() == 2

    assert aufrufe == [schlecht, gut]  # aelteste zuerst
    assert (eingang / "verarbeitet" / "gut.mp3").is_file() and (eingang / "fehler" / "schlecht.mp3").is_file()
    assert not gut.exists() and not schlecht.exists()
    assert [(m["datei"], m["status"]) for m in gemeldet] == [("schlecht.mp3", "fehler"), ("gut.mp3", "fertig")]
    assert dienst.einmal() == 0  # nichts mehr zu tun


def test_dienst_ohne_webhook_meldet_nichts(tmp_path):
    _datei(tmp_path / "in", "a.mp3")
    dienst, _, gemeldet = _dienst(tmp_path, {})
    dienst.einmal()
    dienst.einmal()
    assert gemeldet == []


def test_abgebrochene_datei_bleibt_im_eingang(tmp_path):
    datei = _datei(tmp_path / "in", "a.mp3")
    dienst, _aufrufe, gemeldet = _dienst(tmp_path, {"a.mp3": verarbeitung.STATUS_ABGEBROCHEN}, PROTOKOLL_WEBHOOK_URL="https://x.test/h")
    dienst.einmal()
    dienst.einmal()
    assert datei.is_file() and gemeldet == []


def test_dienst_ohne_verschieben_verarbeitet_nicht_doppelt(tmp_path, monkeypatch):
    datei = _datei(tmp_path / "in", "a.mp3")
    monkeypatch.setattr(warteschlange, "verschiebe_nach", lambda *a, **k: None)
    dienst, aufrufe, _ = _dienst(tmp_path, {})
    dienst.einmal()
    dienst.einmal()
    dienst.einmal()
    assert aufrufe == [datei]  # der Zustand verhindert den zweiten Lauf


def test_stoppen_beendet_die_schleife_und_bricht_laufende_dateien_nicht_neu_an(tmp_path):
    _datei(tmp_path / "in", "a.mp3")
    _datei(tmp_path / "in", "b.mp3", alter=9999)
    dienst, _, _ = _dienst(tmp_path, {})
    dienst.einmal()
    dienst._verarbeiten = lambda datei, e, abbrechen=None, protokollieren=None: (  # noqa: E731
        dienst.stoppen() or verarbeitung.Ergebnis(verarbeitung.STATUS_FERTIG, datei, tmp_path / "out")
    )
    assert dienst.einmal() == 1  # nach dem Stopp wird die zweite Datei nicht mehr begonnen
    assert dienst.gestoppt


def test_lauf_legt_ordner_an_und_endet_nach_stopp(tmp_path):
    dienst, _, _ = _dienst(tmp_path, {})
    dienst._schlafen = lambda s: dienst.stoppen()
    dienst.lauf()
    assert (tmp_path / "in").is_dir() and (tmp_path / "out").is_dir()


def test_wirkliches_schlafen_endet_beim_stoppen(tmp_path):
    einstellungen = _einstellungen(tmp_path)
    dienst = dienst_modul.Dienst(einstellungen, tmp_path / "z.json")
    dienst.stoppen()
    start = time.monotonic()
    dienst._schlafen(5.0)
    assert time.monotonic() - start < 1.0


# --------------------------------------------------------------------------
# Start (__main__)
# --------------------------------------------------------------------------
def test_main_meldet_einstellungsfehler(capsys):
    assert main([], {"PROTOKOLL_GERAET": "tpu"}) == 2
    assert "Einstellungsfehler" in capsys.readouterr().err


def test_pruefen_listet_die_umgebung(tmp_path, capsys, monkeypatch):
    from protokoll_assistent.services import ollama_service

    monkeypatch.setattr(ollama_service, "is_service_running", lambda *a, **k: False)
    monkeypatch.setattr("protokoll_assistent.server.__main__.shutil.which", lambda name: f"/usr/bin/{name}")
    umgebung = {"PROTOKOLL_EINGANG": str(tmp_path / "in"), "PROTOKOLL_AUSGANG": str(tmp_path / "out")}
    code = main(["--pruefen"], umgebung)
    ausgabe = capsys.readouterr().out
    assert "FFmpeg im Suchpfad" in ausgabe and "Ollama erreichbar" in ausgabe and "HF_TOKEN" in ausgabe
    assert "[FEHLT] Ollama" in ausgabe  # nicht kritisch
    assert isinstance(code, int)

    ohne_ffmpeg = pruefe_umgebung(ServerEinstellungen.aus_umgebung(umgebung))
    assert any(text.startswith("Eingangordner beschreibbar") or "beschreibbar" in text for _, text in ohne_ffmpeg)


def test_pruefen_ohne_protokoll_fragt_ollama_nicht(tmp_path):
    umgebung = {
        "PROTOKOLL_EINGANG": str(tmp_path / "in"),
        "PROTOKOLL_AUSGANG": str(tmp_path / "out"),
        "PROTOKOLL_PROTOKOLL_ERSTELLEN": "0",
    }
    texte = [t for _, t in pruefe_umgebung(ServerEinstellungen.aus_umgebung(umgebung))]
    assert not any("Ollama" in t for t in texte)


def test_pruefen_meldet_nicht_beschreibbare_ordner(tmp_path, monkeypatch):
    umgebung = {"PROTOKOLL_EINGANG": str(tmp_path / "in"), "PROTOKOLL_AUSGANG": str(tmp_path / "out"), "PROTOKOLL_PROTOKOLL_ERSTELLEN": "0"}

    def verweigern(self, *a, **k):
        raise PermissionError("nur lesbar")

    monkeypatch.setattr(Path, "mkdir", verweigern)
    ergebnisse = pruefe_umgebung(ServerEinstellungen.aus_umgebung(umgebung))
    assert [ok for ok, text in ergebnisse if "ordner" in text] == [False, False]


def test_main_einmal_arbeitet_den_eingang_ab(tmp_path, monkeypatch):
    from protokoll_assistent.server import __main__ as start

    aufrufe = []
    monkeypatch.setattr(start, "_daten_ordner", lambda name: tmp_path / name)
    monkeypatch.setattr(start, "ensure_system_prompt_file_exists", lambda: None)
    monkeypatch.setattr(start, "get_work_dir", lambda: tmp_path)
    monkeypatch.setattr(start.signal, "signal", lambda *a, **k: None)  # keine Handler im Testprozess hinterlassen
    monkeypatch.setattr(start.Dienst, "einmal", lambda self: aufrufe.append("einmal") or 0)
    umgebung = {"PROTOKOLL_EINGANG": str(tmp_path / "in"), "PROTOKOLL_AUSGANG": str(tmp_path / "out")}
    assert start.main(["--einmal"], umgebung) == 0
    assert aufrufe == ["einmal", "einmal"] and (tmp_path / "in").is_dir()


def test_main_ohne_einmal_startet_die_schleife(tmp_path, monkeypatch):
    from protokoll_assistent.server import __main__ as start

    gestartet = []
    monkeypatch.setattr(start, "_daten_ordner", lambda name: tmp_path / name)
    monkeypatch.setattr(start, "ensure_system_prompt_file_exists", lambda: None)
    monkeypatch.setattr(start, "get_work_dir", lambda: tmp_path)
    monkeypatch.setattr(start.signal, "signal", lambda *a, **k: None)
    monkeypatch.setattr(start.Dienst, "lauf", lambda self: gestartet.append(True))
    assert start.main([], {"PROTOKOLL_EINGANG": str(tmp_path / "in"), "PROTOKOLL_AUSGANG": str(tmp_path / "out")}) == 0
    assert gestartet == [True]


# --------------------------------------------------------------------------
# Daten- und Ollama-Adresse aus der Umgebung
# --------------------------------------------------------------------------
def test_datenordner_aus_der_umgebung(tmp_path, monkeypatch):
    from protokoll_assistent.utils import paths

    monkeypatch.setenv("PROTOKOLL_DATEN_DIR", str(tmp_path / "daten"))
    assert paths.get_work_dir() == tmp_path / "daten" / "arbeitsdaten"
    assert paths.get_logs_dir() == tmp_path / "daten" / "logs"
    monkeypatch.delenv("PROTOKOLL_DATEN_DIR")
    assert paths.get_work_dir() == paths.get_app_dir() / "arbeitsdaten"


def test_ollama_adresse_aus_der_umgebung():
    from protokoll_assistent.services import ollama_service

    assert ollama_service.basis_url_aus_umgebung({"OLLAMA_URL": " http://ollama:11434/ "}) == "http://ollama:11434"
    assert ollama_service.basis_url_aus_umgebung({}) == "http://127.0.0.1:11434"
    assert ollama_service.basis_url_aus_umgebung({"OLLAMA_URL": "  "}) == "http://127.0.0.1:11434"


def test_server_kennt_weder_oberflaeche_noch_qt():
    """Der Servermodus laeuft im Container ohne Qt: Er darf 'gui' und PySide6 nie importieren."""
    import re

    ordner = Path(__file__).resolve().parent.parent / "server"
    verboten = re.compile(r"^\s*(from|import)\s+(PySide6|protokoll_assistent\.gui)", re.MULTILINE)
    for datei in ordner.glob("*.py"):
        assert not verboten.search(datei.read_text(encoding="utf-8")), datei.name
