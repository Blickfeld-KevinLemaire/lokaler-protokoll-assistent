"""Treiber fuer den Ende-zu-Ende-Test der Upload-Komponente (siehe run_e2e.sh).

Startet im selben Container
  * den echten Empfang der Protokoll-Software (GeraeteEmpfang, nur 127.0.0.1:8765),
  * einen kleinen HTTP-Proxy auf 127.0.0.1:8766, der fuer Fall (e) eine Verbindung mitten im
    Stueck kappt und fuer Fall (i) vor der Antwort auf eine Statusabfrage den Stand der Software
    veraendert (dann bekommt das Geraet auf sein naechstes Stueck 409),
  * QEMU mit der Test-App (main/e2e_main.c). Aus QEMU ist der Container 10.0.2.2.
Nichts lauscht ausserhalb des Containers.

Vorher legt der Treiber Teilstaende an (b: richtige erste 300000 Bytes, g: 300000 falsche Bytes,
h: 150000 Bytes bei einer 100000-Byte-Datei). Danach prueft er, ob jede Datei Byte fuer Byte im
Eingangsordner liegt, und wertet Ausgaben von Geraet und Proxy als Beleg aus.
"""

from __future__ import annotations

import argparse
import hashlib
import http.client
import importlib
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

TOKEN = "nur-fuer-den-qemu-test-kein-echtes-token-0"  # noqa: S105 - Test-Token, kein Geheimnis
GERAET = "E2E"
EMPFANG_PORT = 8765
PROXY_PORT = 8766
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
# QEMU
# --------------------------------------------------------------------------
def qemu_starten(build: Path, arbeit: Path) -> subprocess.Popen[bytes]:
    flash = arbeit / "qemu_flash.bin"
    efuse = arbeit / "qemu_efuse.bin"
    subprocess.run(
        [
            sys.executable,
            "-m",
            "esptool",
            "--chip=esp32",
            "merge_bin",
            f"--output={flash}",
            "--fill-flash-size=4MB",
            "@flash_args",
        ],
        cwd=build,
        check=True,
        stdout=subprocess.DEVNULL,
    )
    efuse.write_bytes(EFUSE_ESP32)
    befehl = [
        "qemu-system-xtensa",
        "-M",
        "esp32",
        "-m",
        "4M",
        "-drive",
        f"file={flash},if=mtd,format=raw",
        "-drive",
        f"file={efuse},if=none,format=raw,id=efuse",
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
        # Serielle Ausgabe in eine Datei: "-serial stdio" verstummt, sobald stdin zu ist.
        "-serial",
        f"file:{arbeit / 'serial.log'}",
    ]
    print("Starte: " + " ".join(befehl), flush=True)
    with (arbeit / "qemu.log").open("wb") as protokoll:
        return subprocess.Popen(befehl, stdout=protokoll, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)


def seriell_lesen(qemu: subprocess.Popen[bytes], datei: Path, zeitlimit: float) -> list[str]:
    """Liest die serielle Ausgabe bis zur Ergebniszeile, bis QEMU endet oder bis zum Zeitlimit."""
    zeilen: list[str] = []
    rest = ""
    gelesen = 0
    ende = time.monotonic() + zeitlimit
    while time.monotonic() < ende:
        if datei.exists():
            with datei.open("rb") as handle:
                handle.seek(gelesen)
                neu = handle.read()
            gelesen += len(neu)
            rest += neu.decode("utf-8", errors="replace")
            *fertig, rest = rest.split("\n")
            for zeile in fertig:
                zeile = zeile.rstrip("\r")
                zeilen.append(zeile)
                print(f"QEMU| {zeile}", flush=True)
                if zeile.startswith("E2E ERGEBNIS"):
                    return zeilen
        if qemu.poll() is not None:
            print(f"QEMU beendet (Code {qemu.returncode})", flush=True)
            return zeilen
        time.sleep(0.5)
    print(f"Zeitlimit {zeitlimit:.0f} s erreicht", flush=True)
    return zeilen


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--empfang-root", required=True, type=Path, help="Ordner mit protokoll_assistent/")
    parser.add_argument("--build", required=True, type=Path, help="Build-Ordner der Test-App")
    parser.add_argument("--arbeit", required=True, type=Path)
    parser.add_argument("--zeitlimit", type=float, default=1800.0)
    args = parser.parse_args()

    sys.path.insert(0, str(args.empfang_root))
    # Erst zur Laufzeit: Der Empfang liegt in einem anderen Arbeitsbaum bzw. erst nach dem Zusammenfuehren im Repository.
    g = importlib.import_module("protokoll_assistent.services.geraete_empfang_service")

    shutil.rmtree(args.arbeit, ignore_errors=True)
    args.arbeit.mkdir(parents=True)
    eingang = args.arbeit / "eingang"
    inhalt = {k: daten(groesse, saat) for k, (_, groesse, saat) in DATEIEN.items()}

    empfang = g.GeraeteEmpfang(eingang, [g.Geraet(GERAET, g.token_hash(TOKEN))], port=EMPFANG_PORT, adresse="127.0.0.1")
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
    qemu = qemu_starten(args.build, args.arbeit)
    try:
        zeilen = seriell_lesen(qemu, args.arbeit / "serial.log", args.zeitlimit)
        dauer = time.monotonic() - beginn
    finally:
        qemu.kill()
        qemu.wait()
        kontakte = empfang.kontakte()
        empfang.stoppen()

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

    print("\n================ Ende-zu-Ende (QEMU + echter Empfang) ================")
    for fall, ok, beleg in ergebnisse:
        print(f"{'PASS' if ok else 'FAIL'}  {fall:24s} {beleg}")
    print(f"Geraet: {ergebnis_zeile}")
    alles = all(ok for _, ok, _ in ergebnisse) and "PASS" in ergebnis_zeile
    print(f"Dauer in QEMU: {dauer:.0f} s (Zeitlimit {args.zeitlimit:.0f} s)")
    print(f"GESAMT: {'PASS' if alles else 'FAIL'}")
    return 0 if alles else 1


if __name__ == "__main__":
    sys.exit(main())
