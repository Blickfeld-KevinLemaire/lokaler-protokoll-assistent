"""Tests fuer 'services/ollama_einrichtung_service.py'.

Kein Test laedt etwas herunter, startet ein Programm oder liest die echte
Registry: Netz, PowerShell und Installer sind durch Attrappen ersetzt."""

from __future__ import annotations

import io
import json
import os
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from protokoll_assistent.services import ollama_einrichtung_service as oes

URL = "https://ollama.com/download/OllamaSetup.exe"
ENDE = "https://release-assets.githubusercontent.com/github-production-release-asset/1/OllamaSetup.exe"
# Kleine Grenzen statt 100 MB je Test: Die Pruefungen sind dieselben.
MIN_GROESSE, MAX_GROESSE = 1_000, 100_000
GROESSE = 2_000


@pytest.fixture(autouse=True)
def kleine_grenzen(monkeypatch):
    monkeypatch.setattr(oes, "MIN_GROESSE_BYTES", MIN_GROESSE)
    monkeypatch.setattr(oes, "MAX_GROESSE_BYTES", MAX_GROESSE)
    monkeypatch.setattr(oes, "BLOCK_BYTES", 512)


class _Antwort(io.BytesIO):
    def __init__(self, daten: bytes, *, laenge: int | None = None, ende: str = ENDE):
        super().__init__(daten)
        self.headers = {"Content-Length": str(len(daten) if laenge is None else laenge)}
        self._ende = ende

    def geturl(self) -> str:
        return self._ende


def _oeffnen(antwort: _Antwort, aufrufe: list | None = None):
    def oeffnen(url, timeout):
        if aufrufe is not None:
            aufrufe.append(url)
        return antwort

    return oeffnen


def _installer(groesse: int = GROESSE) -> bytes:
    return b"MZ" + b"\0" * (groesse - 2)


# --------------------------------------------------------------------------
# ermittle_status
# --------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("exe", "eintrag", "dienst", "installiert"),
    [
        (None, None, False, False),
        (Path("C:/x/ollama.exe"), None, False, True),
        (None, (None, "0.35.1"), False, True),
        (None, None, True, True),  # Dienst laeuft (z. B. anders installiert): nie neu installieren
    ],
)
def test_status_erkennt_jede_art_von_installation(exe, eintrag, dienst, installiert):
    status = oes.ermittle_status(finde_fn=lambda: exe, registry_fn=lambda: eintrag, dienst_fn=lambda: dienst)
    assert status.installiert is installiert
    assert status.dienst_laeuft is dienst


def test_status_findet_das_programm_ueber_den_registryeintrag(tmp_path):
    (tmp_path / "ollama.exe").write_bytes(b"")
    status = oes.ermittle_status(finde_fn=lambda: None, registry_fn=lambda: (tmp_path, "0.35.1"), dienst_fn=lambda: False)
    assert status.pfad == tmp_path / "ollama.exe"
    assert status.version == "0.35.1"


def test_registry_ohne_eintrag_ist_kein_fehler(monkeypatch):
    winreg = pytest.importorskip("winreg")

    def fehlt(*a):
        raise OSError("nicht da")

    monkeypatch.setattr(winreg, "OpenKey", fehlt)
    assert oes._registry_eintrag() is None


# --------------------------------------------------------------------------
# lade_installer
# --------------------------------------------------------------------------
def test_installer_wird_vollstaendig_geladen(tmp_path):
    meldungen: list[tuple[int, int]] = []
    log: list[str] = []
    aufrufe: list[str] = []
    pfad = oes.lade_installer(
        tmp_path, lambda f, g: meldungen.append((f, g)), oeffnen_fn=_oeffnen(_Antwort(_installer()), aufrufe), log=log.append
    )
    assert pfad == tmp_path / "OllamaSetup.exe"
    assert pfad.stat().st_size == GROESSE
    assert not (tmp_path / "OllamaSetup.exe.part").exists()
    assert aufrufe == [URL]
    assert meldungen[-1] == (GROESSE, GROESSE)
    assert "SHA-256" in log[0]


@pytest.mark.parametrize(
    ("url", "ende"),
    [
        ("http://ollama.com/download/OllamaSetup.exe", ENDE),  # kein HTTPS
        (URL, "https://boese.example/OllamaSetup.exe"),  # Weiterleitung zu fremdem Server
        (URL, "http://release-assets.githubusercontent.com/x"),  # Weiterleitung ohne HTTPS
    ],
)
def test_unerwartete_adressen_werden_abgelehnt(tmp_path, url, ende):
    with pytest.raises(oes.OllamaEinrichtungFehler, match="unerwarteten Adresse"):
        oes.lade_installer(tmp_path, url=url, oeffnen_fn=_oeffnen(_Antwort(_installer(), ende=ende)))
    assert not any(tmp_path.iterdir())


@pytest.mark.parametrize(
    ("fall", "meldung"),
    [
        ("zu_klein", "unerwartete Größe"),
        ("zu_gross", "unerwartete Größe"),
        ("keine_exe", "kein Windows-Programm"),
        ("abgebrochen", "unvollständig"),  # Verbindung brach ab
    ],
)
def test_verdaechtige_downloads_werden_verworfen(tmp_path, fall, meldung):
    daten, laenge = {
        "zu_klein": (_installer(MIN_GROESSE - 1), None),
        "zu_gross": (_installer(), MAX_GROESSE + 1),
        "keine_exe": (b"PK" + b"\0" * (GROESSE - 2), None),
        "abgebrochen": (_installer(), GROESSE + 5),
    }[fall]
    with pytest.raises(oes.OllamaEinrichtungFehler, match=meldung):
        oes.lade_installer(tmp_path, oeffnen_fn=_oeffnen(_Antwort(daten, laenge=laenge)))
    assert not (tmp_path / "OllamaSetup.exe").exists()
    assert not (tmp_path / "OllamaSetup.exe.part").exists()


def test_download_laesst_sich_abbrechen(tmp_path):
    with pytest.raises(oes.OllamaEinrichtungFehler, match="abgebrochen"):
        oes.lade_installer(tmp_path, oeffnen_fn=_oeffnen(_Antwort(_installer())), abbrechen_fn=lambda: True)
    assert not (tmp_path / "OllamaSetup.exe.part").exists()


def test_netzfehler_wird_verstaendlich_gemeldet(tmp_path):
    def kein_netz(url, timeout):
        raise OSError("Name nicht aufloesbar")

    with pytest.raises(oes.OllamaEinrichtungFehler, match="Internetverbindung"):
        oes.lade_installer(tmp_path, oeffnen_fn=kein_netz)


def test_umbenennen_wiederholt_bei_gesperrter_datei(tmp_path, monkeypatch):
    """Ein Virenscanner haelt eine frische .exe kurz offen (CLAUDE.md, Regel 1)."""
    quelle, ziel = tmp_path / "a.part", tmp_path / "a.exe"
    quelle.write_bytes(b"MZ")
    echt = Path.replace
    versuche = []

    def gesperrt_beim_ersten_mal(self, ziel_pfad):
        versuche.append(1)
        if len(versuche) == 1:
            raise PermissionError("WinError 5")
        return echt(self, ziel_pfad)

    monkeypatch.setattr(Path, "replace", gesperrt_beim_ersten_mal)
    oes._umbenennen_mit_wiederholung(quelle, ziel, warten=0)
    assert ziel.read_bytes() == b"MZ" and len(versuche) == 2


def test_umbenennen_gibt_irgendwann_auf(tmp_path, monkeypatch):
    def immer_gesperrt(self, ziel_pfad):
        raise PermissionError("WinError 5")

    monkeypatch.setattr(Path, "replace", immer_gesperrt)
    with pytest.raises(PermissionError):
        oes._umbenennen_mit_wiederholung(tmp_path / "a", tmp_path / "b", versuche=2, warten=0)


# --------------------------------------------------------------------------
# pruefe_signatur
# --------------------------------------------------------------------------
def _powershell(ausgabe: str, aufrufe: list | None = None):
    def ausfuehren(befehl, **kwargs):
        if aufrufe is not None:
            aufrufe.append((befehl, kwargs))
        return SimpleNamespace(stdout=ausgabe, returncode=0)

    return ausfuehren


def _signatur(status: str, unterzeichner: str) -> str:
    return json.dumps({"s": status, "u": unterzeichner})


def test_gueltige_signatur_von_ollama(tmp_path):
    aufrufe: list = []
    pfad = tmp_path / "Max Mustermann" / "Setup; & boese.exe"
    ergebnis = oes.pruefe_signatur(
        pfad, ausfuehren_fn=_powershell(_signatur("Valid", "CN=Ollama Inc., O=Ollama Inc., L=Toronto"), aufrufe)
    )
    assert ergebnis.ok
    befehl, kwargs = aufrufe[0]
    # Der Pfad steht weder im Befehlstext noch als weiteres Argument, sondern in der Umgebung.
    assert not any(str(pfad) in teil for teil in befehl)
    assert kwargs["env"][oes._PFAD_VARIABLE] == str(pfad)


@pytest.mark.parametrize(
    ("ausgabe", "meldung"),
    [
        (_signatur("NotSigned", ""), "nicht gültig signiert"),
        (_signatur("HashMismatch", "CN=Ollama Inc., O=Ollama Inc."), "nicht gültig signiert"),
        (_signatur("Valid", "CN=Jemand, O=Jemand anderes"), "von jemand anderem"),
        ("Get-AuthenticodeSignature : nicht erlaubt", "ließ sich nicht prüfen"),  # kein JSON
        ("", "ließ sich nicht prüfen"),
    ],
)
def test_im_zweifel_wird_nicht_ausgefuehrt(tmp_path, ausgabe, meldung):
    ergebnis = oes.pruefe_signatur(tmp_path / "x.exe", ausfuehren_fn=_powershell(ausgabe))
    assert not ergebnis.ok
    assert meldung in ergebnis.meldung


@pytest.mark.parametrize("fehler", [FileNotFoundError("powershell"), subprocess.TimeoutExpired("powershell", 60)])
def test_ohne_powershell_wird_nicht_ausgefuehrt(tmp_path, fehler):
    def ausfuehren(befehl, **kwargs):
        raise fehler

    assert not oes.pruefe_signatur(tmp_path / "x.exe", ausfuehren_fn=ausfuehren).ok


@pytest.mark.skipif(os.name != "nt", reason="Authenticode gibt es nur unter Windows")
def test_unsignierte_datei_wird_mit_echter_pruefung_abgelehnt(tmp_path):
    """Die einzige echte PowerShell-Pruefung: eine selbst geschriebene Datei ist
    nie gueltig signiert -- auch nicht in einem Ordner mit Leerzeichen."""
    pfad = tmp_path / "Max Mustermann" / "x.exe"
    pfad.parent.mkdir()
    pfad.write_bytes(b"MZ" + b"\0" * 100)
    ergebnis = oes.pruefe_signatur(pfad)
    assert not ergebnis.ok
    # PowerShell hat die Datei wirklich geprueft (und nicht etwa das Modul nicht laden
    # koennen -- dann bliebe der Status leer): NotSigned bzw. UnknownError fuer diese Attrappe.
    assert "Status: unbekannt" not in ergebnis.meldung, ergebnis.meldung
    assert "nicht gültig signiert" in ergebnis.meldung


def test_powershell_bekommt_keinen_fremden_modulpfad(tmp_path, monkeypatch):
    monkeypatch.setenv("PSModulePath", r"C:\Program Files\PowerShell\7\Modules")
    umgebung = oes._signatur_umgebung(tmp_path / "x.exe")
    assert not any(name.upper() == "PSMODULEPATH" for name in umgebung)
    assert umgebung[oes._PFAD_VARIABLE] == str(tmp_path / "x.exe")


# --------------------------------------------------------------------------
# installiere_still / warte_auf_dienst
# --------------------------------------------------------------------------
def test_stille_installation_mit_inno_schaltern(tmp_path):
    aufrufe = []

    def starten(befehl, **kwargs):
        aufrufe.append(befehl)
        return SimpleNamespace(returncode=0)

    oes.installiere_still(tmp_path / "OllamaSetup.exe", starte_fn=starten)
    assert aufrufe == [[str(tmp_path / "OllamaSetup.exe"), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/SP-"]]


@pytest.mark.parametrize(
    ("code", "meldung"), [(2, "abgebrochen"), (5, "abgebrochen"), (8, "Neustart des Computers"), (1, "Code 1")]
)
def test_rueckgabewerte_des_installers(tmp_path, code, meldung):
    with pytest.raises(oes.OllamaEinrichtungFehler, match=meldung):
        oes.installiere_still(tmp_path / "x.exe", starte_fn=lambda befehl, **k: SimpleNamespace(returncode=code))


@pytest.mark.parametrize(
    ("fehler", "meldung"),
    [(subprocess.TimeoutExpired("x", 1), "zu lange"), (OSError("Richtlinie"), "ließ sich nicht starten")],
)
def test_installer_startet_nicht_oder_haengt(tmp_path, fehler, meldung):
    def starten(befehl, **kwargs):
        raise fehler

    with pytest.raises(oes.OllamaEinrichtungFehler, match=meldung):
        oes.installiere_still(tmp_path / "x.exe", starte_fn=starten)


class _Uhr:
    def __init__(self):
        self.jetzt = 0.0

    def __call__(self) -> float:
        return self.jetzt

    def schlafen(self, sekunden: float) -> None:
        self.jetzt += sekunden


def test_dienst_ist_sofort_da():
    uhr = _Uhr()
    assert oes.warte_auf_dienst(dienst_fn=lambda: True, uhr_fn=uhr, schlafen_fn=uhr.schlafen, starte_app_fn=pytest.fail)


def test_dienst_kommt_erst_nach_dem_start_der_app(tmp_path):
    uhr = _Uhr()
    gestartet = []
    laeuft = lambda: bool(gestartet) and uhr.jetzt > 25  # noqa: E731

    assert oes.warte_auf_dienst(
        dienst_fn=laeuft,
        ordner_fn=lambda: tmp_path,
        starte_app_fn=gestartet.append,
        uhr_fn=uhr,
        schlafen_fn=uhr.schlafen,
        nachstart_nach=20,
    )
    assert gestartet == [tmp_path]  # genau einmal


def test_dienst_kommt_nie():
    uhr = _Uhr()
    gestartet = []
    assert not oes.warte_auf_dienst(
        dienst_fn=lambda: False, ordner_fn=lambda: None, starte_app_fn=gestartet.append, uhr_fn=uhr,
        schlafen_fn=uhr.schlafen, zeitlimit=30,
    )
    assert gestartet == [None]


def test_app_starten_ohne_ordner_oder_programm_tut_nichts(tmp_path):
    oes._starte_app(None)
    oes._starte_app(tmp_path)  # kein 'ollama app.exe' darin


# --------------------------------------------------------------------------
# installiere_ollama
# --------------------------------------------------------------------------
def _nicht_installiert():
    return oes.OllamaStatus(installiert=False)


def test_bereits_installiert_und_laufend_wird_nichts_geladen(tmp_path):
    log: list[str] = []
    ok = oes.installiere_ollama(
        tmp_path, log.append, status_fn=lambda: oes.OllamaStatus(True, version="0.35.1", dienst_laeuft=True),
        lade_fn=pytest.fail, install_fn=pytest.fail,
    )
    assert ok and "0.35.1" in log[0]


def test_installiert_aber_aus_wird_nur_gestartet(tmp_path):
    ok = oes.installiere_ollama(
        tmp_path, lambda m: None, status_fn=lambda: oes.OllamaStatus(True), lade_fn=pytest.fail,
        install_fn=pytest.fail, warte_fn=lambda: True,
    )
    assert ok


def test_kompletter_ablauf(tmp_path):
    schritte: list[str] = []
    installer = tmp_path / "OllamaSetup.exe"

    def laden(ordner, fortschritt, *, abbrechen_fn, log):
        installer.write_bytes(b"MZ")
        schritte.append("laden")
        return installer

    def pruefen(pfad):
        schritte.append("pruefen")
        return oes.SignaturErgebnis(True, "O=Ollama Inc.", "Signatur gültig: Ollama Inc.")

    ok = oes.installiere_ollama(
        tmp_path, lambda m: None, status_fn=_nicht_installiert, lade_fn=laden, pruef_fn=pruefen,
        install_fn=lambda pfad: schritte.append("installieren"), warte_fn=lambda: schritte.append("warten") or True,
    )
    assert ok and schritte == ["laden", "pruefen", "installieren", "warten"]
    assert not installer.exists()  # der Installer wird danach geloescht


def test_falsche_signatur_verhindert_die_installation(tmp_path):
    installer = tmp_path / "OllamaSetup.exe"

    def laden(ordner, fortschritt, *, abbrechen_fn, log):
        installer.write_bytes(b"MZ")
        return installer

    with pytest.raises(oes.OllamaEinrichtungFehler, match="jemand anderem"):
        oes.installiere_ollama(
            tmp_path, lambda m: None, status_fn=_nicht_installiert, lade_fn=laden,
            pruef_fn=lambda p: oes.SignaturErgebnis(False, "O=X", "von jemand anderem signiert"),
            install_fn=pytest.fail,
        )
    assert not installer.exists()
