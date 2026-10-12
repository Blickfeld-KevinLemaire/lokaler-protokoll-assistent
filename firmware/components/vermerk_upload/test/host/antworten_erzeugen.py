"""Erzeugt antworten_software.h: echte Antworten des Empfangs der Protokoll-Software als C-Texte.

Die Host-Tests (test_vermerk_protokoll.c) lesen diese Texte mit dem reinen C-Teil der Firmware. Aendert
die Software ihr Antwortformat, schlagen sie fehl - dann diese Datei neu erzeugen und pruefen, ob die
Firmware noch passt:

    python antworten_erzeugen.py <Ordner mit protokoll_assistent/> > antworten_software.h

Die meisten Antworten kommen ueber echtes HTTP vom laufenden Dienst (nur 127.0.0.1, freier Port);
503, 507 und "Stueck unvollstaendig" entstehen ohne HTTP ueber dieselben Funktionen wie im Dienst.
"""

from __future__ import annotations

import hashlib
import http.client
import importlib
import socket
import sys
import tempfile
from pathlib import Path

TOKEN = "nur-fuer-den-vertragstest-kein-echtes-token"  # noqa: S105 - Test-Token, kein Geheimnis


def c_text(daten: bytes) -> str:
    aus = []
    for b in daten:
        zeichen = chr(b)
        if zeichen in '"\\':
            aus.append("\\" + zeichen)
        elif 0x20 <= b < 0x7F:
            aus.append(zeichen)
        else:
            aus.append(f'\\x{b:02x}""')  # Ende der Hex-Folge erzwingen
    return '"' + "".join(aus) + '"'


def main() -> int:
    wurzel = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[5]
    sys.path.insert(0, str(wurzel))
    g = importlib.import_module("protokoll_assistent.services.geraete_empfang_service")

    faelle: list[tuple[str, int, bytes]] = []

    with tempfile.TemporaryDirectory() as tmp:
        empfang = g.GeraeteEmpfang(Path(tmp), [g.Geraet("Vertrag", g.token_hash(TOKEN))], port=0, adresse="127.0.0.1")
        empfang.starten()
        port = empfang.port

        def anfrage(methode: str, pfad: str, body: bytes | None = None, **kopf: str) -> tuple[int, bytes]:
            v = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
            try:
                kopfzeilen = {"Authorization": f"Bearer {TOKEN}", **{k.replace("_", "-"): w for k, w in kopf.items()}}
                v.request(methode, pfad, body=body, headers=kopfzeilen)
                r = v.getresponse()
                return r.status, r.read()
            finally:
                v.close()

        def roh(anfrage_text: bytes) -> tuple[int, bytes]:
            with socket.create_connection(("127.0.0.1", port), timeout=10) as s:
                s.sendall(anfrage_text)
                antwort = b""
                while True:
                    block = s.recv(65536)
                    if not block:
                        break
                    antwort += block
            kopf, _, body = antwort.partition(b"\r\n\r\n")
            return int(kopf.split(b" ")[1]), body

        inhalt = b"0123456789"
        sha = hashlib.sha256(inhalt).hexdigest()
        a = "/api/v1/aufnahmen/H5_007.opus"

        faelle.append(("HALLO", *anfrage("GET", "/api/v1/hallo")))
        faelle.append(("STATUS_NEU", *anfrage("GET", a)))
        faelle.append(("TEIL_ANGEHAENGT", *anfrage("PUT", a, inhalt, X_Offset="0")))
        faelle.append(("STATUS_TEILSTAND", *anfrage("GET", a)))
        faelle.append(("VERSATZ_409", *anfrage("PUT", a, inhalt, X_Offset="0")))
        faelle.append(("ABSCHLUSS_FERTIG", *anfrage("PUT", a, b"", X_Offset="10", X_Gesamtgroesse="10", X_SHA256=sha)))
        anfrage("PUT", a, inhalt, X_Offset="0")
        faelle.append(("ABSCHLUSS_DOPPELT", *anfrage("PUT", a, b"", X_Offset="10", X_Gesamtgroesse="10", X_SHA256=sha)))
        anfrage("PUT", a, inhalt, X_Offset="0")
        faelle.append(
            ("ABSCHLUSS_GROESSE_422", *anfrage("PUT", a, b"", X_Offset="10", X_Gesamtgroesse="11", X_SHA256=sha))
        )
        anfrage("PUT", a, inhalt, X_Offset="0")
        faelle.append(
            (
                "ABSCHLUSS_PRUEFSUMME_422",
                *anfrage("PUT", a, b"", X_Offset="10", X_Gesamtgroesse="10", X_SHA256="0" * 64),
            )
        )
        faelle.append(("NAME_400", *anfrage("GET", "/api/v1/aufnahmen/H5%20007.flac")))
        faelle.append(("KOPF_400", *anfrage("PUT", a, inhalt, X_Offset="abc")))
        faelle.append(("PFAD_404", *anfrage("GET", "/api/v1/unbekannt")))
        v = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        v.request("GET", "/api/v1/hallo", headers={"Authorization": "Bearer falsch"})
        r = v.getresponse()
        faelle.append(("TOKEN_401", r.status, r.read()))
        v.close()
        faelle.append(
            (
                "CHUNKED_411",
                *roh(
                    f"PUT {a} HTTP/1.1\r\nHost: x\r\nAuthorization: Bearer {TOKEN}\r\nX-Offset: 0\r\n"
                    "Transfer-Encoding: chunked\r\n\r\n0\r\n\r\n".encode()
                ),
            )
        )
        faelle.append(
            (
                "ZU_GROSS_413",
                *roh(
                    f"PUT {a} HTTP/1.1\r\nHost: x\r\nAuthorization: Bearer {TOKEN}\r\nX-Offset: 0\r\n"
                    f"Content-Length: {g.TEIL_MAX_BYTES + 1}\r\n\r\n".encode()
                ),
            )
        )
        empfang.stoppen()

        # Ohne HTTP, ueber dieselben Funktionen wie im Dienst
        voll = g.Ablage(Path(tmp) / "voll", freier_platz=lambda _pfad: 0)
        antwort = voll.anhaengen("Vertrag", "H5_008.opus", 0, 10, lambda n: b"x" * n)
        faelle.append(("PLATTE_VOLL_507", antwort.status, antwort.als_bytes()))
        abbruch = g.Ablage(Path(tmp) / "abbruch")
        antwort = abbruch.anhaengen("Vertrag", "H5_009.opus", 0, 10, lambda _n: b"")
        faelle.append(("STUECK_UNVOLLSTAENDIG_400", antwort.status, antwort.als_bytes()))
        antwort = g._fehler(503, "Zu viele gleichzeitige Verbindungen.")  # so antwortet _Anfrage._vorpruefung
        faelle.append(("UEBERLAST_503", antwort.status, antwort.als_bytes()))

    print("/* Erzeugt von antworten_erzeugen.py aus dem echten Empfang der Protokoll-Software")
    print(" * (protokoll_assistent/services/geraete_empfang_service.py). Nicht von Hand aendern. */")
    print("#pragma once")
    print()
    for name, status, body in faelle:
        print(f"#define SW_{name}_STATUS {status}")
        print(f"#define SW_{name} {c_text(body)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
