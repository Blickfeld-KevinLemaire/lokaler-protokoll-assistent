"""Treiber fuer den Ende-zu-Ende-Test der Upload-Komponente (siehe run_e2e.sh).

Startet im selben Container
  * den echten Empfang der Protokoll-Software (GeraeteEmpfang, nur 127.0.0.1:8765),
  * einen kleinen HTTP-Proxy auf 127.0.0.1:8766, der fuer Fall (e) eine Verbindung mitten im
    Stueck kappt und fuer Fall (i) vor der Antwort auf eine Statusabfrage den Stand der Software
    veraendert (dann bekommt das Geraet auf sein naechstes Stueck 409),
  * QEMU mit der Test-App (main/e2e_main.c). Aus QEMU ist der Container 10.0.2.2.
Nichts lauscht ausserhalb des Containers.

Danach richtet er das Geraet ueber die serielle Konsole ein ("#VERMERK ...", Einrichtung ueber USB),
prueft den Upload mit den Werten aus dem NVS und loescht die Einrichtung wieder.

Vorher legt der Treiber Teilstaende an (b: richtige erste 300000 Bytes, g: 300000 falsche Bytes,
h: 150000 Bytes bei einer 100000-Byte-Datei). Danach prueft er, ob jede Datei Byte fuer Byte im
Eingangsordner liegt, und wertet Ausgaben von Geraet und Proxy als Beleg aus.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import http.client
import importlib
import json
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

TOKEN = "nur-fuer-den-qemu-test-kein-echtes-token-0"  # noqa: S105 - Test-Token, kein Geheimnis
GERAET = "E2E"
EMPFANG_PORT = 8765
PROXY_PORT = 8766
KONSOLE_PORT = 5555  # serielle Konsole von QEMU, nur 127.0.0.1 im Container
TEIL = 256 * 1024

# (Name, Groesse, Saat) - dieselben Werte wie in main/e2e_main.c
DATEIEN = {
    "A": ("E2E_A.opus", 600000, 0xA1),
    "B": ("E2E_B.opus", 600000, 0xB2),
    "C": ("E2E_C.opus", 10000, 0xC3),
    "D": ("E2E_D.opus", 100000, 0xD4),
    "E": ("E2E_E.opus", 600000, 0xE5),
    "F": ("E2E_F.opus", 600000, 0xF6),
    "G": ("E2E_G.opus", 600000, 0x67),
    "H": ("E2E_H.opus", 100000, 0x48),
    "I": ("E2E_I.opus", 600000, 0x19),
}

# eFuse-Abbild fuer QEMU (ESP32, Chip-Revision 3) wie in $IDF_PATH/tools/idf_py_actions/qemu_ext.py
EFUSE_ESP32 = bytes.fromhex(
    "00000000000000000000000000800000000000000000100000000000000000000000000000000000"
    "00000000000000000000000000000000000000000000000000000000000000000000000000000000"
    "00000000000000000000000000000000000000000000000000000000000000000000000000000000"
    "00000000"
)


def daten(groesse: int, saat: int) -> bytes:
    """xorshift32, ein Byte je Schritt - dieselbe Folge wie datei_schreiben() im Geraet."""
    x = saat
    aus = bytearray(groesse)
    for i in range(groesse):
        x ^= (x << 13) & 0xFFFFFFFF
        x ^= x >> 17
        x ^= (x << 5) & 0xFFFFFFFF
        aus[i] = x & 0xFF
    return bytes(aus)


def put(name: str, offset: int, inhalt: bytes, token: str = TOKEN) -> tuple[int, bytes]:
    verbindung = http.client.HTTPConnection("127.0.0.1", EMPFANG_PORT, timeout=30)
    try:
        verbindung.request(
            "PUT",
            f"/api/v1/aufnahmen/{name}",
            body=inhalt,
            headers={"Authorization": f"Bearer {token}", "X-Offset": str(offset), "Content-Length": str(len(inhalt))},
        )
        antwort = verbindung.getresponse()
        return antwort.status, antwort.read()
    finally:
        verbindung.close()


# --------------------------------------------------------------------------
# Proxy
# --------------------------------------------------------------------------
class Proxy:
    """Eine Anfrage je Verbindung (so arbeitet das Geraet). Protokolliert jede Anfrage mit Antwort."""

    def __init__(self, daten_i: bytes):
        self.protokoll: list[str] = []
        self._puts: dict[str, int] = {}
        self._gekappt = False
        self._eingeschoben = False
        self._daten_i = daten_i
        self._sperre = threading.Lock()
        self._lauscher = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._lauscher.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._lauscher.bind(("127.0.0.1", PROXY_PORT))
        self._lauscher.listen(8)
        threading.Thread(target=self._annehmen, daemon=True).start()

    def _log(self, text: str) -> None:
        with self._sperre:
            self.protokoll.append(text)
        print(f"PROXY| {text}", flush=True)

    def _annehmen(self) -> None:
        while True:
            try:
                geraet, _ = self._lauscher.accept()
            except OSError:
                return
            threading.Thread(target=self._bedienen, args=(geraet,), daemon=True).start()

    @staticmethod
    def _kopf_lesen(sock: socket.socket) -> tuple[bytes, bytes]:
        puffer = b""
        while b"\r\n\r\n" not in puffer:
            block = sock.recv(65536)
            if not block:
                raise ConnectionError("Verbindung vor Ende der Kopfzeilen geschlossen")
            puffer += block
        kopf, _, rest = puffer.partition(b"\r\n\r\n")
        return kopf + b"\r\n\r\n", rest

    @staticmethod
    def _laenge(kopf: bytes) -> int:
        treffer = re.search(rb"(?im)^content-length:\s*(\d+)", kopf)
        return int(treffer.group(1)) if treffer else 0

    @staticmethod
    def _kopfwert(kopf: bytes, name: str) -> str:
        treffer = re.search(rb"(?im)^" + name.encode() + rb":\s*([^\r\n]*)", kopf)
        return treffer.group(1).decode() if treffer else "-"

    def _bedienen(self, geraet: socket.socket) -> None:
        server = socket.create_connection(("127.0.0.1", EMPFANG_PORT), timeout=60)
        try:
            kopf, rest = self._kopf_lesen(geraet)
            zeile = kopf.split(b"\r\n", 1)[0].decode()
            methode, pfad = zeile.split(" ")[0], zeile.split(" ")[1]
            laenge = self._laenge(kopf)
            offset = self._kopfwert(kopf, "X-Offset")

            kappen_nach = None
            if methode == "PUT" and pfad.endswith("/E2E_E.opus"):
                with self._sperre:
                    self._puts[pfad] = self._puts.get(pfad, 0) + 1
                    if self._puts[pfad] == 2 and not self._gekappt:
                        self._gekappt = True
                        kappen_nach = 100000

            server.sendall(kopf)
            gesendet = 0
            while gesendet < laenge:
                block = rest if rest else geraet.recv(65536)
                rest = b""
                if not block:
                    break
                if kappen_nach is not None and gesendet + len(block) >= kappen_nach:
                    server.sendall(block[: kappen_nach - gesendet])
                    self._log(f"{methode} {pfad} X-Offset={offset} Laenge={laenge} -> nach {kappen_nach} Bytes GEKAPPT")
                    return  # beide Seiten schliessen, ohne Antwort
                server.sendall(block)
                gesendet += len(block)

            antwort_kopf, antwort_rest = self._kopf_lesen(server)
            antwort_laenge = self._laenge(antwort_kopf)
            while len(antwort_rest) < antwort_laenge:
                block = server.recv(65536)
                if not block:
                    break
                antwort_rest += block
            status = antwort_kopf.split(b"\r\n", 1)[0].decode()

            if methode == "GET" and pfad.endswith("/E2E_I.opus") and not self._eingeschoben:
                # Vor der Antwort (naechstes_byte 0) nimmt die Software schon das erste Stueck an:
                # Das Geraet sendet ab 0 und muss mit 409 beim gemeldeten Byte weitermachen.
                self._eingeschoben = True
                s, text = put("E2E_I.opus", 0, self._daten_i[:TEIL])
                self._log(f"(Treiber legt vor der Antwort {TEIL} Bytes von E2E_I.opus vor: HTTP {s} {text.decode()})")

            self._log(
                f"{methode} {pfad} X-Offset={offset} Laenge={laenge} -> {status} {antwort_rest.decode(errors='replace')}"
            )
            geraet.sendall(antwort_kopf + antwort_rest)
        except (OSError, ConnectionError) as fehler:
            self._log(f"Verbindung abgebrochen: {fehler}")
        finally:
            for sock in (geraet, server):
                try:
                    sock.close()
                except OSError:
                    pass


# --------------------------------------------------------------------------
# QEMU und serielle Konsole
# --------------------------------------------------------------------------
class Qemu:
    """QEMU mit der Test-App. Die serielle Konsole (UART0) ist ein TCP-Server auf 127.0.0.1 im Container
    (nur Loopback): der Treiber oder - fuer den App-Fall - pyserial ("socket://") verbindet sich damit,
    immer nur einer zur Zeit. Der Flash liegt in einer Datei und bleibt ueber Neustarts erhalten (NVS)."""

    def __init__(self, build: Path, arbeit: Path):
        self.arbeit = arbeit
        self.flash = arbeit / "qemu_flash.bin"
        self.efuse = arbeit / "qemu_efuse.bin"
        self.zeilen: list[str] = []
        self._bedingung = threading.Condition()
        self._prozess: subprocess.Popen[bytes] | None = None
        self._konsole: socket.socket | None = None
        subprocess.run(
            [
                sys.executable,
                "-m",
                "esptool",
                "--chip=esp32",
                "merge_bin",
                f"--output={self.flash}",
                "--fill-flash-size=4MB",
                "@flash_args",
            ],
            cwd=build,
            check=True,
            stdout=subprocess.DEVNULL,
        )
        self.efuse.write_bytes(EFUSE_ESP32)

    def starten(self) -> None:
        befehl = [
            "qemu-system-xtensa",
            "-M",
            "esp32",
            "-m",
            "4M",
            "-drive",
            f"file={self.flash},if=mtd,format=raw",
            "-drive",
            f"file={self.efuse},if=none,format=raw,id=efuse",
            "-global",
            "driver=nvram.esp32.efuse,property=drive,value=efuse",
            "-global",
            "driver=timer.esp32.timg,property=wdt_disable,value=true",
            "-nic",
            "user,model=open_eth",  # QEMU-User-Netz: der Container ist fuer das Geraet 10.0.2.2
            "-display",
            "none",
            "-monitor",
            "none",
            "-chardev",
            f"socket,id=konsole,host=127.0.0.1,port={KONSOLE_PORT},server=on,wait=on",
            "-serial",
            "chardev:konsole",
        ]
        print("Starte: " + " ".join(befehl), flush=True)
        with (self.arbeit / "qemu.log").open("ab") as protokoll:
            self._prozess = subprocess.Popen(
                befehl, stdout=protokoll, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL
            )
        self.verbinden()

    def verbinden(self) -> None:
        ende = time.monotonic() + 60
        while True:
            try:
                konsole = socket.create_connection(("127.0.0.1", KONSOLE_PORT), timeout=5)
                konsole.settimeout(None)
                break
            except OSError:
                if time.monotonic() > ende or not self.laeuft():
                    raise RuntimeError("QEMU-Konsole nicht erreichbar") from None
                time.sleep(0.2)
        self._konsole = konsole
        threading.Thread(target=self._lesen, args=(konsole,), daemon=True).start()

    def trennen(self) -> None:
        """Konsole freigeben (z. B. fuer pyserial im App-Fall)."""
        if self._konsole is not None:
            # shutdown weckt den lesenden Faden und beendet die Verbindung wirklich; QEMU nimmt erst dann
            # den naechsten Client an (close allein laesst sie offen, solange recv() noch wartet)
            with contextlib.suppress(OSError):
                self._konsole.shutdown(socket.SHUT_RDWR)
            self._konsole.close()
            self._konsole = None

    def zeile_aufnehmen(self, zeile: str, quelle: str = "QEMU") -> None:
        with self._bedingung:
            self.zeilen.append(zeile)
            print(f"{quelle}| {zeile}", flush=True)
            self._bedingung.notify_all()

    def _lesen(self, konsole: socket.socket) -> None:
        rest = b""
        while True:
            try:
                block = konsole.recv(65536)
            except OSError:
                block = b""
            if not block:
                with self._bedingung:
                    self._bedingung.notify_all()
                return
            rest += block
            *fertig, rest = rest.split(b"\n")
            for roh in fertig:
                self.zeile_aufnehmen(roh.decode("utf-8", errors="replace").rstrip("\r"))

    def laeuft(self) -> bool:
        return self._prozess is not None and self._prozess.poll() is None

    def senden(self, text: str) -> int:
        """Schickt eine Zeile; liefert die Position, ab der Antworten gesucht werden."""
        with self._bedingung:
            ab = len(self.zeilen)
        print(f"AN GERAET| {text[:120]}{'...' if len(text) > 120 else ''}", flush=True)
        if self._konsole is None:
            raise RuntimeError("Konsole nicht verbunden")
        self._konsole.sendall(text.encode("ascii") + b"\n")
        return ab

    def warten(self, praefix: str, ab: int, zeitlimit: float) -> str | None:
        """Erste Zeile ab Position `ab`, die mit `praefix` beginnt. Startet QEMU neu, falls es sich beim
        Neustart des Geraets beendet hat (dann bleibt der Flash erhalten)."""
        ende = time.monotonic() + zeitlimit
        with self._bedingung:
            while True:
                for zeile in self.zeilen[ab:]:
                    if zeile.startswith(praefix):
                        return zeile
                if time.monotonic() > ende:
                    return None
                if not self.laeuft():
                    print("QEMU hat sich beendet - starte neu (gleicher Flash)", flush=True)
                    self._bedingung.release()
                    try:
                        self.starten()
                    finally:
                        self._bedingung.acquire()
                self._bedingung.wait(timeout=1.0)

    def anfrage(self, text: str, zeitlimit: float = 120.0) -> str:
        """Anweisung schicken, auf die naechste '#VERMERK '-Antwort warten."""
        ab = self.senden(text)
        return self.warten("#VERMERK ", ab, zeitlimit) or "(keine Antwort)"

    def stoppen(self) -> None:
        self.trennen()
        if self._prozess is not None:
            self._prozess.kill()
            self._prozess.wait()


def hexwert(text: str) -> str:
    return text.encode("utf-8").hex()


def info_lesen(antwort: str) -> dict[str, object]:
    praefix = "#VERMERK INFO "
    if not antwort.startswith(praefix):
        return {}
    try:
        daten_json = json.loads(antwort[len(praefix) :])
    except ValueError:
        return {}
    return daten_json if isinstance(daten_json, dict) else {}


def einrichtung_pruefen(
    qemu: Qemu, token: str, eingang: Path, kontakte: Callable[[], dict[str, object]]
) -> list[tuple[str, bool, str]]:
    """Einrichtung ueber USB: INFO, Fehlerfaelle, SETZE/SPEICHERN, Neustart, Upload mit den Werten aus
    dem NVS, LOESCHEN, Neustart. Liefert (Fall, ok, Beleg)."""
    ergebnisse: list[tuple[str, bool, str]] = []
    ssid = 'Büro WLAN "5"'
    passwort = "geheim-1234"
    url = f"http://10.0.2.2:{EMPFANG_PORT}"

    # 1. Start, nicht eingerichtet
    antwort = qemu.anfrage("#VERMERK INFO")
    info = info_lesen(antwort)
    ergebnisse.append(
        (
            "USB INFO (nicht eingerichtet)",
            info.get("eingerichtet") is False
            and info.get("board") == "e2e-qemu"
            and info.get("firmware") == "1.0.0"
            and info.get("pc_url_hex") == ""
            and info.get("token_pc") is False,
            antwort,
        )
    )

    fehlerfaelle = [
        ("#VERMERK SETZE farbe 00", "#VERMERK FEHLER farbe unbekannter Schluessel"),
        ("#VERMERK SETZE wlan_ssid 4", "#VERMERK FEHLER wlan_ssid Wert ist kein gueltiges Hex"),
        (
            f"#VERMERK SETZE wlan_passwort {hexwert('1234567')}",
            "#VERMERK FEHLER wlan_passwort WLAN-Passwort: leer oder 8 bis 63 Bytes",
        ),
        ("#VERMERK SETZE pc_token " + "61" * 290, "#VERMERK FEHLER ZEILE zu lang (hoechstens 512 Zeichen)"),
        (f"#VERMERK SETZE wlan_ssid {hexwert('QEMU')}", "#VERMERK OK SETZE wlan_ssid"),
        (f"#VERMERK SETZE pc_url {hexwert(url)}", "#VERMERK OK SETZE pc_url"),
        ("#VERMERK SPEICHERN", "#VERMERK FEHLER SPEICHERN pc_token fehlt (pc_url ist gesetzt)"),
        ("#VERMERK VERWERFEN", "#VERMERK OK VERWERFEN"),
        ("#VERMERK SPEICHERN", "#VERMERK FEHLER SPEICHERN wlan_ssid fehlt"),
    ]
    for anweisung, erwartet in fehlerfaelle:
        antwort = qemu.anfrage(anweisung)
        kurz = anweisung if len(anweisung) < 60 else anweisung[:40] + f"... ({len(anweisung)} Zeichen)"
        ergebnisse.append((f"USB {kurz}", antwort == erwartet, antwort))

    # Einrichten und speichern
    setzen = [
        ("wlan_ssid", ssid),
        ("wlan_passwort", passwort),
        ("pc_url", url),
        ("pc_token", token),
        ("erste_nummer", "1"),
    ]
    alle_ok = True
    for schluessel, wert in setzen:
        antwort = qemu.anfrage(f"#VERMERK SETZE {schluessel} {hexwert(wert)}")
        alle_ok = alle_ok and antwort == f"#VERMERK OK SETZE {schluessel}"
    ergebnisse.append(
        ("USB SETZE (5 Werte, WLAN-Name mit Umlaut und Anfuehrungszeichen)", alle_ok, "alle OK" if alle_ok else antwort)
    )
    ab = qemu.senden("#VERMERK SPEICHERN")
    antwort = qemu.warten("#VERMERK ", ab, 120) or "(keine Antwort)"
    ergebnisse.append(("USB SPEICHERN", antwort == "#VERMERK OK SPEICHERN", antwort))

    # 2. Start: eingerichtet, Upload nur mit den Werten aus dem NVS
    start = qemu.warten("E2E KONSOLE: eingerichtet=", ab, 300) or ""
    ergebnisse.append(("USB Neustart nach SPEICHERN", start == "E2E KONSOLE: eingerichtet=1", start or "kein Neustart"))
    n = qemu.warten("E2E n:", ab, 300) or "(kein Ergebnis)"
    datei = eingang / "USB_E2E_N.opus"
    gleich = datei.exists() and datei.read_bytes() == daten(300000, 0x4E)
    kontakt = kontakte().get("USB")
    ergebnisse.append(
        (
            "USB Upload mit NVS-Einstellungen",
            n.startswith("E2E n: OK") and gleich and getattr(kontakt, "firmware", None) == "e2e-qemu/1.0.0",
            f"{n} | {datei.name} {'byte-gleich' if gleich else 'FEHLT/ABWEICHEND'} | kontakte()['USB']: {kontakt}",
        )
    )
    qemu.warten("E2E BEREIT", ab, 120)
    antwort = qemu.anfrage("#VERMERK INFO")
    info = info_lesen(antwort)
    ergebnisse.append(
        (
            "USB INFO (eingerichtet)",
            info.get("eingerichtet") is True
            and info.get("wlan_hex") == hexwert(ssid)
            and info.get("pc_url_hex") == hexwert(url)
            and info.get("server_url_hex") == ""
            and info.get("token_pc") is True
            and info.get("token_server") is False,
            antwort,
        )
    )

    # LOESCHEN, 3. Start: wieder nicht eingerichtet
    ab = qemu.senden("#VERMERK LOESCHEN")
    antwort = qemu.warten("#VERMERK ", ab, 120) or "(keine Antwort)"
    ergebnisse.append(("USB LOESCHEN", antwort == "#VERMERK OK LOESCHEN", antwort))
    start = qemu.warten("E2E KONSOLE: eingerichtet=", ab, 300) or ""
    qemu.warten("E2E BEREIT", ab, 120)
    antwort = qemu.anfrage("#VERMERK INFO")
    info = info_lesen(antwort)
    ergebnisse.append(
        (
            "USB INFO nach LOESCHEN",
            start == "E2E KONSOLE: eingerichtet=0"
            and info.get("eingerichtet") is False
            and info.get("pc_url_hex") == ""
            and info.get("token_pc") is False,
            f"{start} | {antwort}",
        )
    )

    # Passwort und Token erscheinen nie in der Ausgabe des Geraets (weder als Text noch als Hex)
    geheim = [token, hexwert(token), passwort, hexwert(passwort)]
    funde = [z for z in qemu.zeilen if any(g in z for g in geheim)]
    ergebnisse.append(
        (
            "USB Passwort/Token nie ausgegeben",
            not funde,
            f"{len(qemu.zeilen)} Zeilen des Geraets durchsucht, Funde: {len(funde)}",
        )
    )
    return ergebnisse


class Mitschnitt:
    """Haengt zwischen dem echten Code der Anwendung und pyserial: reicht alles durch, schreibt jede
    gelesene Zeile des Geraets in qemu.zeilen (fuer die Suche nach Passwort und Token) und zaehlt, was
    die Anwendung sendet."""

    def __init__(self, verbindung: Any, qemu: Qemu, gesendet: list[str]):
        self._verbindung = verbindung
        self._qemu = qemu
        self._gesendet = gesendet

    def write(self, daten: bytes) -> Any:
        text = daten.decode("ascii", errors="replace").rstrip("\n")
        self._gesendet.append(text)
        print(f"APP AN GERAET| {text[:100]}{'...' if len(text) > 100 else ''}", flush=True)
        return self._verbindung.write(daten)

    def readline(self) -> bytes:
        roh: bytes = self._verbindung.readline()
        if roh:
            self._qemu.zeile_aufnehmen(roh.decode("utf-8", errors="replace").rstrip("\r\n"), "APP<-GERAET")
        return roh

    def close(self) -> None:
        self._verbindung.close()


def app_pruefen(
    qemu: Qemu, usb: Any, token: str, eingang: Path, kontakte: Callable[[], dict[str, object]]
) -> list[tuple[str, bool, str]]:
    """Der echte Code der Anwendung (services/geraete_usb_service.py) richtet das Geraet ein - ueber
    pyserial wie am COM-Port, hier mit "socket://" auf die Konsole von QEMU."""
    serial = importlib.import_module("serial")
    ergebnisse: list[tuple[str, bool, str]] = []
    gesendet: list[str] = []
    url = f"http://10.0.2.2:{EMPFANG_PORT}"
    ssid = 'Gäste "Büro" ÄÖÜ'
    passwort = "Passwort mit Leerzeichen!"

    def oeffnen(_port: str) -> Mitschnitt:
        return Mitschnitt(serial.serial_for_url(f"socket://127.0.0.1:{KONSOLE_PORT}", timeout=0.2), qemu, gesendet)

    def kurz_schlafen(sekunden: float) -> None:
        # nach_neustart_verbinden() wartet sonst 1,5 s, bevor es neu oeffnet. Am echten Geraet verschwindet der
        # COM-Port beim Neustart ohnehin. In QEMU bleibt die Konsole bestehen, und ein Neustart OHNE
        # verbundenen Client endete zweimal in einer Panik beim Start (Task-Watchdog-ISR, weil QEMU die
        # Timergruppe beim Software-Reset nicht zuruecksetzt). Deshalb hier sofort wieder verbinden.
        time.sleep(min(sekunden, 0.05))

    def info_mit_geduld(sitzung: Any) -> Any:
        letzter: Exception | None = None
        for _ in range(10):  # das Geraet startet gerade (QEMU ist langsam)
            try:
                return sitzung.info()
            except usb.UsbFehler as fehler:
                letzter = fehler
        raise letzter or RuntimeError("keine Antwort")

    def bis_zeile(sitzung: Any, praefix: str, ab: int, zeitlimit: float) -> str | None:
        """Liest ueber die Verbindung der Anwendung weiter, bis das Geraet `praefix` ausgibt."""
        ende = time.monotonic() + zeitlimit
        while time.monotonic() < ende:
            treffer = next((z for z in qemu.zeilen[ab:] if z.startswith(praefix)), None)
            if treffer is not None:
                return treffer
            sitzung._verbindung.readline()
        return None

    qemu.trennen()
    sitzung = usb.Geraetesitzung(oeffnen("qemu"))
    try:
        info = info_mit_geduld(sitzung)
        ergebnisse.append(
            ("APP info() vor der Einrichtung", info.eingerichtet is False and info.board == "e2e-qemu", str(info))
        )

        # Von der Anwendung selbst abgelehnt (gleiche Regeln wie im Geraet): nichts geht an das Geraet
        for fall, falsch in [
            (
                "7-stelliges Passwort",
                usb.Einrichtung(wlan_ssid=ssid, wlan_passwort="1234567", pc_url=url, pc_token=token),
            ),
            (
                "Passwort mit Umlaut",
                usb.Einrichtung(wlan_ssid=ssid, wlan_passwort="geheimnis-äöü", pc_url=url, pc_token=token),
            ),
            (
                "Adresse mit / am Ende",
                usb.Einrichtung(wlan_ssid=ssid, wlan_passwort=passwort, pc_url=url + "/", pc_token=token),
            ),
        ]:
            vorher = len(gesendet)
            try:
                sitzung.einrichten(falsch)
                ergebnisse.append((f"APP lehnt ab: {fall}", False, "keine Ausnahme"))
            except usb.UsbFehler as fehler:
                ergebnisse.append(
                    (
                        f"APP lehnt ab, nichts gesendet: {fall}",
                        len(gesendet) == vorher and bool(falsch.fehler()),
                        f"UsbFehler: {fehler} | gesendet: {len(gesendet) - vorher} Zeilen",
                    )
                )

        # Vom Geraet abgelehnt, durch den Code der Anwendung (_anweisung/_antwort). Ueber einrichten() geht
        # das nicht mehr: Die Anwendung prueft vorher mindestens so streng wie das Geraet.
        for fall, schritte, erwartet in [
            (
                "SETZE Adresse mit / am Ende",
                [(f"SETZE pc_url {(url + '/').encode().hex()}", "SETZE pc_url", "pc_url")],
                "Das Geraet lehnt 'pc_url' ab: Adresse ohne / am Ende angeben",
            ),
            (
                "SPEICHERN ohne Token",
                [
                    ("VERWERFEN", "VERWERFEN", "VERWERFEN"),
                    (f"SETZE wlan_ssid {ssid.encode().hex()}", "SETZE wlan_ssid", "wlan_ssid"),
                    (f"SETZE pc_url {url.encode().hex()}", "SETZE pc_url", "pc_url"),
                    ("SPEICHERN", "SPEICHERN", "SPEICHERN"),
                ],
                "Das Geraet lehnt 'SPEICHERN' ab: pc_token fehlt (pc_url ist gesetzt)",
            ),
        ]:
            try:
                for befehl, ok, schluessel in schritte:
                    sitzung._anweisung(befehl, ok, schluessel)
                ergebnisse.append((f"APP Geraet lehnt ab: {fall}", False, "keine Ausnahme"))
            except usb.UsbFehler as fehler:
                ergebnisse.append((f"APP Geraet lehnt ab: {fall}", str(fehler) == erwartet, f"UsbFehler: {fehler}"))

        # Einrichten wie die Anwendung
        richtig = usb.Einrichtung(wlan_ssid=ssid, wlan_passwort=passwort, pc_url=url, pc_token=token, erste_nummer=1)
        sitzung.einrichten(richtig)
        ergebnisse.append(("APP einrichten()", True, f"{len(richtig.befehle())} SETZE + SPEICHERN ohne Fehler"))
    finally:
        sitzung.schliessen()

    # Nach dem Neustart neu verbinden, wie die Anwendung es tut
    ab = len(qemu.zeilen)
    sitzung = usb.nach_neustart_verbinden("qemu", oeffnen, zeitlimit=120, schlafen=kurz_schlafen)
    try:
        info = info_mit_geduld(sitzung)
        ergebnisse.append(
            (
                "APP info() nach dem Neustart",
                info.eingerichtet is True
                and info.wlan == ssid
                and info.pc_url == url
                and info.token_pc is True
                and info.token_server is False,
                str(info),
            )
        )
        n = bis_zeile(sitzung, "E2E n:", ab, 300) or "(kein Ergebnis)"
        datei = eingang / "APP_E2E_N.opus"
        gleich = datei.exists() and datei.read_bytes() == daten(300000, 0x4E)
        kontakt = kontakte().get("APP")
        ergebnisse.append(
            (
                "APP Upload mit den eingerichteten Werten",
                n.startswith("E2E n: OK") and gleich and getattr(kontakt, "firmware", None) == "e2e-qemu/1.0.0",
                f"{n} | {datei.name} {'byte-gleich' if gleich else 'FEHLT/ABWEICHEND'} | kontakte()['APP']: {kontakt}",
            )
        )
        bis_zeile(sitzung, "E2E BEREIT", ab, 120)
        sitzung.loeschen()
        ergebnisse.append(("APP loeschen()", True, "OK LOESCHEN"))
    finally:
        sitzung.schliessen()

    sitzung = usb.nach_neustart_verbinden("qemu", oeffnen, zeitlimit=120, schlafen=kurz_schlafen)
    try:
        info = info_mit_geduld(sitzung)
        ergebnisse.append(
            (
                "APP info() nach loeschen()",
                info.eingerichtet is False and info.pc_url == "" and not info.token_pc,
                str(info),
            )
        )
    finally:
        sitzung.schliessen()

    geheim = [token, token.encode().hex(), passwort, passwort.encode().hex()]
    funde = [z for z in qemu.zeilen if any(x in z for x in geheim)]
    ergebnisse.append(
        ("APP Passwort/Token nie vom Geraet ausgegeben", not funde, f"{len(qemu.zeilen)} Zeilen, Funde: {len(funde)}")
    )
    return ergebnisse


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--empfang-root", required=True, type=Path, help="Ordner mit protokoll_assistent/")
    parser.add_argument("--build", required=True, type=Path, help="Build-Ordner der Test-App")
    parser.add_argument("--arbeit", required=True, type=Path)
    parser.add_argument("--zeitlimit", type=float, default=1800.0)
    parser.add_argument(
        "--app-root",
        type=Path,
        help="Ordner mit protokoll_assistent/services/geraete_usb_service.py (Standard: --empfang-root)",
    )
    args = parser.parse_args()

    sys.path.insert(0, str(args.empfang_root))
    # Erst zur Laufzeit: Der Empfang liegt in einem anderen Arbeitsbaum bzw. erst nach dem Zusammenfuehren im Repository.
    g = importlib.import_module("protokoll_assistent.services.geraete_empfang_service")

    shutil.rmtree(args.arbeit, ignore_errors=True)
    args.arbeit.mkdir(parents=True)
    eingang = args.arbeit / "eingang"
    inhalt = {k: daten(groesse, saat) for k, (_, groesse, saat) in DATEIEN.items()}

    # Zweites Geraet "USB": sein Token erzeugt der Empfang wie in der Anwendung, eingerichtet wird es ueber USB
    usb_token = g.token_erzeugen()
    app_token = g.token_erzeugen()
    empfang = g.GeraeteEmpfang(
        eingang,
        [
            g.Geraet(GERAET, g.token_hash(TOKEN)),
            g.Geraet("USB", g.token_hash(usb_token)),
            g.Geraet("APP", g.token_hash(app_token)),
        ],
        port=EMPFANG_PORT,
        adresse="127.0.0.1",
    )
    empfang.starten()
    proxy = Proxy(inhalt["I"])

    # Teilstaende vorlegen
    vorlagen = {
        "b": put("E2E_B.opus", 0, inhalt["B"][:300000]),
        "g": put("E2E_G.opus", 0, daten(300000, 0x99)),  # falsche Bytes
        "h": put("E2E_H.opus", 0, daten(150000, 0x77)),  # mehr als die Datei hat
    }
    for fall, (status, text) in vorlagen.items():
        print(f"VORLAGE ({fall}): HTTP {status} {text.decode()}", flush=True)

    beginn = time.monotonic()
    qemu = Qemu(args.build, args.arbeit)
    usb_ergebnisse: list[tuple[str, bool, str]] = []
    try:
        qemu.starten()
        qemu.warten("E2E ERGEBNIS", 0, args.zeitlimit)
        dauer = time.monotonic() - beginn
        if qemu.warten("E2E BEREIT", 0, 120) is not None:
            usb_ergebnisse = einrichtung_pruefen(qemu, usb_token, eingang, empfang.kontakte)
            app_root = args.app_root or args.empfang_root
            if (app_root / "protokoll_assistent/services/geraete_usb_service.py").exists():
                sys.path.insert(0, str(app_root))
                usb = importlib.import_module("protokoll_assistent.services.geraete_usb_service")
                try:
                    usb_ergebnisse += app_pruefen(qemu, usb, app_token, eingang, empfang.kontakte)
                except Exception as fehler:  # Bericht trotzdem ausgeben
                    usb_ergebnisse.append(("APP Ablauf", False, f"{type(fehler).__name__}: {fehler}"))
            else:
                print("APP-Fall uebersprungen: services/geraete_usb_service.py fehlt", flush=True)
        else:
            usb_ergebnisse = [("USB Einrichtung", False, "Geraet nicht bereit")]
    finally:
        qemu.stoppen()
        kontakte = empfang.kontakte()
        empfang.stoppen()
    zeilen = list(qemu.zeilen)
    dauer_gesamt = time.monotonic() - beginn

    # ------------------------------------------------------------------
    ergebnisse: list[tuple[str, bool, str]] = []

    def pruefen(fall: str, ok: bool, beleg: str) -> None:
        ergebnisse.append((fall, ok, beleg))

    def geraet_ok(fall: str) -> bool:
        return any(z.startswith(f"E2E {fall}: OK") for z in zeilen)

    def diagnose(name: str) -> list[str]:
        return [z for z in zeilen if z.startswith(f"VERMERK Upload-Diagnose {name}")]

    def angekommen(k: str) -> tuple[bool, str]:
        name = DATEIEN[k][0]
        pfad = eingang / f"{GERAET}_{name}"
        if not pfad.exists():
            return False, f"{pfad.name} fehlt"
        gleich = pfad.read_bytes() == inhalt[k]
        sha = hashlib.sha256(inhalt[k]).hexdigest()[:16]
        return gleich, f"{pfad.name} {'byte-gleich' if gleich else 'ABWEICHEND'} (sha256 {sha}...)"

    ergebnis_zeile = next((z for z in zeilen if z.startswith("E2E ERGEBNIS")), "keine Ergebniszeile (Zeitlimit?)")

    pruefen("hallo", geraet_ok("hallo"), next((z for z in zeilen if z.startswith("E2E hallo")), "-"))

    for fall, k, erwartung in [
        ("a", "A", r"ab Byte 0, \d+ KB in 3 Stuecken"),
        ("b", "B", r"ab Byte 300000,"),
        ("e", "E", r"ab Byte 262144,"),
        ("f", "F", r"ab Byte 262144,"),
        ("g", "G", r"ab Byte 300000,"),
        ("h", "H", r"ab Byte 150000,"),
        ("i", "I", r"ab Byte 0,"),
    ]:
        da, beleg = angekommen(k)
        diag = diagnose(DATEIEN[k][0])
        passt = any(re.search(erwartung, d) for d in diag)
        pruefen(fall, geraet_ok(fall) and da and passt, beleg + " | " + " || ".join(d.split(": ", 1)[1] for d in diag))

    for fall, k in (("g", "G"), ("h", "H")):
        von_vorn = any(z.startswith(f"VERMERK Upload {DATEIEN[k][0]}: Groesse oder Pruefsumme") for z in zeilen)
        pruefen(
            f"{fall} (422 -> von vorn)", von_vorn, "Geraet meldet 'beginne von vorn'" if von_vorn else "keine Meldung"
        )

    c_da = (eingang / f"{GERAET}_E2E_C.opus").exists()
    pruefen(
        "c",
        geraet_ok("c") and not c_da,
        next((z for z in zeilen if z.startswith("E2E c")), "-")
        + f" | beim Empfang: {'VORHANDEN (falsch)' if c_da else 'nichts'}",
    )

    d_da, d_beleg = angekommen("D")
    d_doppelt = sorted(p.name for p in eingang.glob("E2E_E2E_D*.opus"))
    pruefen("d", geraet_ok("d") and d_da and d_doppelt == ["E2E_E2E_D.opus"], f"{d_beleg} | Dateien: {d_doppelt}")

    gekappt = [p for p in proxy.protokoll if "GEKAPPT" in p]
    pruefen("e (Abbruch)", bool(gekappt), gekappt[0] if gekappt else "Proxy hat nicht gekappt")
    konflikt = [p for p in proxy.protokoll if "E2E_I.opus" in p and " 409 " in p]
    weiter = [p for p in proxy.protokoll if "E2E_I.opus" in p and "X-Offset=262144" in p and " 200 " in p]
    pruefen(
        "i (409 -> weiter)",
        bool(konflikt) and bool(weiter),
        (konflikt[0] if konflikt else "kein 409") + " || " + (weiter[0] if weiter else "kein Stueck ab 262144"),
    )

    kennung = next((z for z in zeilen if z.startswith("E2E KENNUNG")), "")
    kontakt = kontakte.get(GERAET)
    treffer_id = re.search(r"id=(\S*)", kennung)
    id_geraet = treffer_id.group(1) if treffer_id else ""
    kopf_ok = kontakt is not None and kontakt.firmware == "e2e-qemu/1.0.0" and (kontakt.geraete_id or "") == id_geraet
    pruefen("X-Geraete-Id/X-Firmware", kopf_ok, f"Geraet: {kennung} | Empfang.kontakte(): {kontakt}")

    ergebnisse.extend(usb_ergebnisse)

    print("\n================ Ende-zu-Ende (QEMU + echter Empfang) ================")
    for fall, ok, beleg in ergebnisse:
        print(f"{'PASS' if ok else 'FAIL'}  {fall:24s} {beleg}")
    print(f"Geraet: {ergebnis_zeile}")
    alles = all(ok for _, ok, _ in ergebnisse) and "PASS" in ergebnis_zeile
    print(f"Dauer in QEMU: Upload-Faelle {dauer:.0f} s, mit Einrichtung {dauer_gesamt:.0f} s")
    print(f"GESAMT: {'PASS' if alles else 'FAIL'}")
    return 0 if alles else 1


if __name__ == "__main__":
    sys.exit(main())
