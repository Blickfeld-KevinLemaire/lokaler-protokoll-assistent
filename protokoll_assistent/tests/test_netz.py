"""Tests fuer 'utils/netz.py'. Kein Netz, kein curl, kein PowerShell: Alles ist durch Attrappen ersetzt."""

from __future__ import annotations

import io
import ssl
import subprocess
import sys
import urllib.error
from pathlib import Path
from types import SimpleNamespace

import pytest

from protokoll_assistent.utils import netz

ZERTIFIKAT = ssl.SSLCertVerificationError("certificate verify failed: unable to get local issuer certificate")
URL = "https://e.example/x"


@pytest.fixture
def windows(monkeypatch):
    """So tun, als laeuft es unter Windows mit curl.exe und PowerShell, ohne Proxy."""
    monkeypatch.setattr(netz.sys, "platform", "win32")
    monkeypatch.setattr(netz, "_curl", lambda: "curl.exe")
    monkeypatch.setattr(netz, "_powershell", lambda: "powershell.exe")
    monkeypatch.setattr(netz, "_proxy_fuer", lambda url: None)


def _ok(ende: str = "https://cdn.example/x.exe", datei: bytes | None = b"inhalt"):
    def lauf(befehl, **kwargs):
        return SimpleNamespace(returncode=0, stdout=ende, stderr="")

    return lauf


def _fehler(text: str, code: int = 35):
    return SimpleNamespace(returncode=code, stdout="", stderr=text)


# --------------------------------------------------------------------------
# Stufe 1: truststore
# --------------------------------------------------------------------------
def test_systemzertifikate_ohne_paket_sind_kein_fehler(monkeypatch):
    monkeypatch.setitem(sys.modules, "truststore", None)  # Import schlaegt fehl
    assert netz.systemzertifikate_nutzen() is False


def test_systemzertifikate_werden_eingehaengt(monkeypatch):
    aufrufe = []
    monkeypatch.setitem(sys.modules, "truststore", SimpleNamespace(inject_into_ssl=lambda: aufrufe.append(1)))
    assert netz.systemzertifikate_nutzen() is True
    assert aufrufe == [1]


def test_zertifikatsfehler_wird_auch_eingepackt_erkannt():
    assert netz.ist_zertifikatsfehler(ZERTIFIKAT)
    assert netz.ist_zertifikatsfehler(urllib.error.URLError(ZERTIFIKAT))
    assert not netz.ist_zertifikatsfehler(urllib.error.URLError("Name nicht aufloesbar"))
    assert not netz.ist_zertifikatsfehler(OSError("anderes"))


# --------------------------------------------------------------------------
# lade_datei
# --------------------------------------------------------------------------
class _Antwort(io.BytesIO):
    def __enter__(self):
        return self


def test_lade_datei_normaler_weg(tmp_path):
    ziel = tmp_path / "x.bin"
    netz.lade_datei(URL, ziel, oeffnen_fn=lambda url, timeout: _Antwort(b"daten"), windows_fn=None)
    assert ziel.read_bytes() == b"daten"


def test_lade_datei_weicht_bei_zertifikatsfehler_auf_windows_aus(tmp_path):
    ziel = tmp_path / "x.bin"
    aufrufe = []

    def kaputt(url, timeout):
        raise urllib.error.URLError(ZERTIFIKAT)

    def windows_laedt(url, pfad, timeout):
        aufrufe.append(url)
        pfad.write_bytes(b"von windows")

    netz.lade_datei(URL, ziel, oeffnen_fn=kaputt, windows_fn=windows_laedt)
    assert aufrufe == [URL]
    assert ziel.read_bytes() == b"von windows"


def test_lade_datei_andere_fehler_gehen_nicht_ueber_windows(tmp_path):
    def kein_netz(url, timeout):
        raise urllib.error.URLError("kein Netz")

    def windows_laedt(*a):
        raise AssertionError("darf nicht aufgerufen werden")

    with pytest.raises(urllib.error.URLError):
        netz.lade_datei(URL, tmp_path / "x", oeffnen_fn=kein_netz, windows_fn=windows_laedt)


def test_lade_datei_meldet_beide_fehler(tmp_path):
    def kaputt(url, timeout):
        raise urllib.error.URLError(ZERTIFIKAT)

    def windows_laedt(*a):
        raise OSError("curl fehlt")

    with pytest.raises(OSError, match="curl fehlt"):
        netz.lade_datei(URL, tmp_path / "x", oeffnen_fn=kaputt, windows_fn=windows_laedt)
    assert not (tmp_path / "x").exists()


# --------------------------------------------------------------------------
# Stufe 2 und 3: curl und PowerShell
# --------------------------------------------------------------------------
def test_curl_nur_https_und_ohne_sperrlistenverzicht(tmp_path, windows):
    befehle = []

    def lauf(befehl, **kwargs):
        befehle.append(befehl)
        return SimpleNamespace(returncode=0, stdout="https://cdn.example/x.exe", stderr="")

    assert netz.herunterladen_mit_windows(URL, tmp_path / "x", ausfuehren_fn=lauf) == "https://cdn.example/x.exe"
    assert len(befehle) == 1
    assert befehle[0][-1] == URL
    assert befehle[0].count("=https") == 2
    assert "--ssl-revoke-best-effort" not in befehle[0]
    assert "--proxy" not in befehle[0]
    # Die Zeitgrenze gilt dem Stillstand, nicht der ganzen Uebertragung (der Ollama-Installer hat knapp 2 GB).
    assert "--max-time" not in befehle[0]
    assert befehle[0][befehle[0].index("--speed-time") + 1] == "300"


def test_curl_bekommt_den_windows_proxy(tmp_path, windows, monkeypatch):
    monkeypatch.setattr(netz, "_proxy_fuer", lambda url: "http://proxy.firma:8080")
    befehle = []

    def lauf(befehl, **kwargs):
        befehle.append(befehl)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    netz.herunterladen_mit_windows(URL, tmp_path / "x", ausfuehren_fn=lauf)
    assert befehle[0][befehle[0].index("--proxy") + 1] == "http://proxy.firma:8080"


def test_curl_versucht_es_ohne_sperrliste_nur_bei_dem_einen_fehler(tmp_path, windows):
    befehle = []

    def lauf(befehl, **kwargs):
        befehle.append(befehl)
        if "--ssl-revoke-best-effort" in befehl:
            return SimpleNamespace(returncode=0, stdout="https://cdn.example/x.exe", stderr="")
        return _fehler("schannel: CRYPT_E_NO_REVOCATION_CHECK (0x80092012)")

    netz.herunterladen_mit_windows(URL, tmp_path / "x", ausfuehren_fn=lauf)
    assert len(befehle) == 2 and "--ssl-revoke-best-effort" in befehle[1]
    # Nie ganz ohne Sperrpruefung: Ein gesperrtes Zertifikat muss ein Fehler bleiben.
    assert not any("--ssl-no-revoke" in befehl for befehl in befehle)


def test_curl_unvertrauenswuerdige_wurzel_geht_nicht_ohne_pruefung_weiter(tmp_path, windows):
    befehle = []

    def lauf(befehl, **kwargs):
        befehle.append(befehl)
        if befehl[0] == "powershell.exe":
            return _fehler("PS kaputt", 1)
        return _fehler("schannel: SEC_E_UNTRUSTED_ROOT")

    with pytest.raises(OSError, match=r"SEC_E_UNTRUSTED_ROOT.*PS kaputt"):
        netz.herunterladen_mit_windows(URL, tmp_path / "x", ausfuehren_fn=lauf)
    assert not any("--ssl-revoke-best-effort" in b for b in befehle)  # kein zweiter curl-Versuch
    assert [b[0] for b in befehle] == ["curl.exe", "powershell.exe"]


def test_powershell_springt_ein_wenn_curl_scheitert(tmp_path, windows):
    ziel = tmp_path / "x"
    aufrufe = []

    def lauf(befehl, **kwargs):
        aufrufe.append((befehl, kwargs))
        if befehl[0] == "curl.exe":
            return _fehler("kaputt", 7)
        return SimpleNamespace(returncode=0, stdout="https://cdn.example/x.exe", stderr="")

    assert netz.herunterladen_mit_windows(URL, ziel, ausfuehren_fn=lauf) == "https://cdn.example/x.exe"
    befehl, kwargs = aufrufe[-1]
    # Adresse und Ziel nur ueber die Umgebung, nie im Befehlstext (Leerzeichen, ';' im Benutzerordner).
    assert URL not in " ".join(befehl) and str(ziel) not in " ".join(befehl)
    assert kwargs["env"]["VERMERK_URL"] == URL and kwargs["env"]["VERMERK_ZIEL"] == str(ziel)
    assert "PSMODULEPATH" not in {name.upper() for name in kwargs["env"]}
    assert kwargs["env"]["VERMERK_STILLSTAND_MS"] == "300000"
    # PowerShell schreibt UTF-8 (im Skript eingestellt) -- sonst gingen deutsche Fehlertexte verloren.
    assert kwargs["encoding"] == "utf-8"
    assert "OutputEncoding" in befehl[-1] and "PassThru" not in befehl[-1]


def test_curl_fehlt_dann_powershell(tmp_path, windows, monkeypatch):
    monkeypatch.setattr(netz, "_curl", lambda: None)
    assert netz.herunterladen_mit_windows(URL, tmp_path / "x", ausfuehren_fn=_ok()) == "https://cdn.example/x.exe"


def test_weder_curl_noch_powershell(tmp_path, windows, monkeypatch):
    monkeypatch.setattr(netz, "_curl", lambda: None)
    monkeypatch.setattr(netz, "_powershell", lambda: None)
    with pytest.raises(OSError, match=r"curl.exe fehlt.*PowerShell fehlt"):
        netz.herunterladen_mit_windows(URL, tmp_path / "x", ausfuehren_fn=_ok())


def test_zeitueberschreitung_ist_ein_oserror_und_raeumt_auf(tmp_path, windows):
    ziel = tmp_path / "x"
    ziel.write_bytes(b"halb")

    def lauf(befehl, **kwargs):
        raise subprocess.TimeoutExpired(befehl, 1)

    with pytest.raises(OSError, match="fehlgeschlagen") as fehler:
        netz.herunterladen_mit_windows(URL, ziel, ausfuehren_fn=lauf)
    assert not ziel.exists()
    # Die Befehlszeile (darin kann der Proxy samt Kennwort stehen) gehoert nicht in die Meldung.
    assert "curl.exe" not in str(fehler.value) and "Zeitüberschreitung" in str(fehler.value)


def test_proxy_zugangsdaten_stehen_nie_in_der_meldung(tmp_path, windows, monkeypatch):
    # Aus Teilen zusammengesetzt: kein echtes Kennwort, und kein Muster, an dem die Geheimnissuche der CI anschlaegt.
    kennwort = "-".join(("nur", "im", "test"))
    proxy = f"http://max:{kennwort}@proxy.firma:8080"
    monkeypatch.setattr(netz, "_proxy_fuer", lambda url: proxy)

    def lauf(befehl, **kwargs):
        return _fehler(f"curl: (56) CONNECT tunnel failed via {proxy}", 56)

    with pytest.raises(OSError) as fehler:
        netz.herunterladen_mit_windows(URL, tmp_path / "x", ausfuehren_fn=lauf)
    assert kennwort not in str(fehler.value)
    assert "***@proxy.firma" in str(fehler.value)


def test_abbruch_wird_durchgereicht_und_raeumt_auf(tmp_path, windows):
    ziel = tmp_path / "x"
    aufrufe = []

    def lauf(befehl, **kwargs):
        aufrufe.append(befehl[0])
        ziel.write_bytes(b"halb")
        assert kwargs["abbrechen_fn"]() is True
        raise netz.Abgebrochen("Der Download wurde abgebrochen.")

    with pytest.raises(netz.Abgebrochen):
        netz.herunterladen_mit_windows(URL, ziel, ausfuehren_fn=lauf, abbrechen_fn=lambda: True)
    assert aufrufe == ["curl.exe"]  # nach einem Abbruch kein zweiter Weg
    assert not ziel.exists()


def test_fortschritt_meldet_die_geladenen_bytes(tmp_path, windows):
    ziel = tmp_path / "x"
    werte: list[int] = []

    def lauf(befehl, **kwargs):
        kwargs["takt_fn"]()  # Datei gibt es noch nicht: kein Fehler, keine Meldung
        ziel.write_bytes(b"12345")
        kwargs["takt_fn"]()
        return SimpleNamespace(returncode=0, stdout="https://cdn.example/x.exe", stderr="")

    netz.herunterladen_mit_windows(URL, ziel, ausfuehren_fn=lauf, fortschritt_fn=werte.append)
    assert werte == [5]


def test_powershell_meldung_ohne_skriptstelle(tmp_path, windows, monkeypatch):
    monkeypatch.setattr(netz, "_curl", lambda: None)
    text = 'Ausnahme beim Aufrufen von "GetResponse":  "Für den geschützten\nKanal"\nIn Zeile:1 Zeichen:432\n+ ... $antwort'

    with pytest.raises(OSError, match="geschützten Kanal") as fehler:
        netz.herunterladen_mit_windows(URL, tmp_path / "x", ausfuehren_fn=lambda befehl, **kw: _fehler(text, 1))
    assert "Zeichen:432" not in str(fehler.value)


# --------------------------------------------------------------------------
# Der echte Hilfsprozess (ohne Netz: nur der eigene Python-Interpreter)
# --------------------------------------------------------------------------
def test_ausfuehren_verliert_keine_meldung_in_fremder_codepage():
    # Windows PowerShell 5.1 schreibt deutsche Meldungen in Codepage 850: "ü" ist dort das Byte 0x81, das es
    # in cp1252 nicht gibt. Mit 'subprocess.run(text=True)' blieb 'stderr' dann leer ("Exit-Code 1").
    skript = "import sys; sys.stderr.buffer.write(b'Pr\\x81fung gescheitert'); sys.exit(3)"
    ergebnis = netz._ausfuehren([sys.executable, "-c", skript], encoding="cp1252")
    assert ergebnis.returncode == 3
    assert ergebnis.stderr.startswith("Pr") and ergebnis.stderr.endswith("fung gescheitert")


def test_ausfuehren_laesst_sich_abbrechen(monkeypatch):
    monkeypatch.setattr(netz, "_TAKT_SEKUNDEN", 0.05)
    takte: list[int] = []
    with pytest.raises(netz.Abgebrochen):
        netz._ausfuehren(
            [sys.executable, "-c", "import time; time.sleep(60)"],
            abbrechen_fn=lambda: len(takte) >= 2,
            takt_fn=lambda: takte.append(1),
        )
    assert len(takte) == 2


def test_ausfuehren_hoechstdauer_ohne_befehlszeile_in_der_meldung(monkeypatch):
    monkeypatch.setattr(netz, "_TAKT_SEKUNDEN", 0.05)
    with pytest.raises(OSError, match="Zeitüberschreitung") as fehler:
        netz._ausfuehren([sys.executable, "-c", "import time; time.sleep(60)"], hoechstdauer=0.1)
    assert not isinstance(fehler.value, netz.Abgebrochen)
    assert "sleep" not in str(fehler.value)


def test_weiterleitung_ohne_https_wird_verworfen(tmp_path, windows):
    ziel = tmp_path / "x"

    def lauf(befehl, **kwargs):
        ziel.write_bytes(b"x")
        return SimpleNamespace(returncode=0, stdout="http://boese.example/x", stderr="")

    with pytest.raises(OSError, match="ohne HTTPS"):
        netz.herunterladen_mit_windows(URL, ziel, ausfuehren_fn=lauf)
    assert not ziel.exists()


def test_nur_https_wird_geladen(tmp_path, windows):
    with pytest.raises(OSError, match="Nur HTTPS"):
        netz.herunterladen_mit_windows("http://e.example/x", tmp_path / "x", ausfuehren_fn=_ok())


def test_nicht_unter_linux(tmp_path, monkeypatch):
    monkeypatch.setattr(netz.sys, "platform", "linux")
    with pytest.raises(OSError, match="kein Windows"):
        netz.herunterladen_mit_windows(URL, tmp_path / "x")


# --------------------------------------------------------------------------
# Hilfen
# --------------------------------------------------------------------------
def test_programme_werden_im_systemordner_gesucht(tmp_path, monkeypatch):
    (tmp_path / "System32" / "WindowsPowerShell" / "v1.0").mkdir(parents=True)
    curl = tmp_path / "System32" / "curl.exe"
    ps = tmp_path / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    curl.write_bytes(b"")
    ps.write_bytes(b"")
    monkeypatch.setenv("SystemRoot", str(tmp_path))
    assert Path(netz._curl() or "") == curl
    assert Path(netz._powershell() or "") == ps


def test_proxy_kommt_aus_den_windows_einstellungen(monkeypatch):
    monkeypatch.setattr(netz.urllib.request, "proxy_bypass", lambda host: False)
    monkeypatch.setattr(netz.urllib.request, "getproxies", lambda: {"https": "http://p:3128"})
    assert netz._proxy_fuer(URL) == "http://p:3128"
    monkeypatch.setattr(netz.urllib.request, "proxy_bypass", lambda host: True)
    assert netz._proxy_fuer(URL) is None


def test_unlesbarer_proxy_verhindert_nichts(monkeypatch):
    def kaputt():
        raise RuntimeError("Registry")

    monkeypatch.setattr(netz.urllib.request, "proxy_bypass", lambda host: False)
    monkeypatch.setattr(netz.urllib.request, "getproxies", kaputt)
    assert netz._proxy_fuer(URL) is None
