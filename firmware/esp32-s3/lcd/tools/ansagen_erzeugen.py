"""Erzeugt die gesprochenen Saetze fuer VERMERK Raum (Waveshare ESP32-S3-Touch-LCD-1.85C).

Die Saetze werden am PC mit einer Windows-Stimme gesprochen (SAPI ueber PowerShell 7), auf gleichen Pegel
gebracht und als IMA-ADPCM (16 kHz, Mono, 4 Bit, untere Haelfte des Bytes zuerst, Start mit Vorhersage 0 und
Index 0) nach ``main/ansagen/<name>.adpcm`` geschrieben. Die Firmware bettet die Dateien in die App ein
(``EMBED_FILES`` in ``main/CMakeLists.txt``); zum Aufspielen reicht darum die App, die Einrichtung bleibt.

Aufruf (Windows, PowerShell 7 muss installiert sein):
    python tools/ansagen_erzeugen.py [--stimme "Microsoft Katja"]

Neue Saetze: hier in SAETZE eintragen, in CMakeLists.txt und in main.c (ansage_daten) ergaenzen.
"""

import argparse
import json
import struct
import subprocess
import tempfile
import wave
from pathlib import Path

HIER = Path(__file__).resolve().parent
ZIEL = HIER.parent / "main" / "ansagen"
RATE = 16000

# Name der Datei -> gesprochener Text. Die Reihenfolge entspricht ansage_t in main.c.
SAETZE = {
    "transkription_erfolgreich": "Transkription erfolgreich.",
    "frage_zusammenfassung": "Möchten Sie eine Zusammenfassung erstellen?",
    "protokoll_erfolgreich": "Protokoll erfolgreich.",
}


def sapi(jobs, stimme):
    """jobs: Liste (wav-Datei, Text); eine PowerShell fuer alle."""
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
        json.dump([{"f": a, "t": b} for a, b in jobs], f, ensure_ascii=False)
        liste = f.name
    ps = (
        "Add-Type -AssemblyName System.Speech;"
        "$s=New-Object System.Speech.Synthesis.SpeechSynthesizer;"
        f"$s.SelectVoice('{stimme}');"
        "$fmt=New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo 16000,"
        "([System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen),([System.Speech.AudioFormat.AudioChannel]::Mono);"
        f"$j=Get-Content -Raw -Encoding UTF8 '{liste}' | ConvertFrom-Json;"
        "foreach($x in $j){ $s.SetOutputToWaveFile($x.f,$fmt); $s.Speak($x.t) };"
        "$s.Dispose()"
    )
    try:
        # nur in PowerShell 7 (pwsh) sind die neueren Stimmen wie Katja sichtbar
        subprocess.run(["pwsh", "-NoProfile", "-Command", ps], check=True)
    finally:
        Path(liste).unlink()


def lesen(datei):
    """Stille vorn und hinten bis auf 40 ms kuerzen, Spitze auf ca. -1 dBFS."""
    with wave.open(datei, "rb") as w:
        if w.getframerate() != RATE or w.getsampwidth() != 2 or w.getnchannels() != 1:
            raise ValueError(f"{datei}: erwartet 16 kHz, 16 Bit, Mono")
        raw = w.readframes(w.getnframes())
    x = list(struct.unpack(f"<{len(raw) // 2}h", raw))
    schwelle = 300
    a = next((i for i, v in enumerate(x) if abs(v) > schwelle), 0)
    b = len(x) - next((i for i, v in enumerate(reversed(x)) if abs(v) > schwelle), 0)
    x = x[max(0, a - 640) : min(len(x), b + 640)]
    spitze = max(1, max(abs(v) for v in x))
    g = 29000 / spitze
    return [max(-32768, min(32767, int(v * g))) for v in x]


IDX = [-1, -1, -1, -1, 2, 4, 6, 8, -1, -1, -1, -1, 2, 4, 6, 8]
STEP = [
    7,
    8,
    9,
    10,
    11,
    12,
    13,
    14,
    16,
    17,
    19,
    21,
    23,
    25,
    28,
    31,
    34,
    37,
    41,
    45,
    50,
    55,
    60,
    66,
    73,
    80,
    88,
    97,
    107,
    118,
    130,
    143,
    157,
    173,
    190,
    209,
    230,
    253,
    279,
    307,
    337,
    371,
    408,
    449,
    494,
    544,
    598,
    658,
    724,
    796,
    876,
    963,
    1060,
    1166,
    1282,
    1411,
    1552,
    1707,
    1878,
    2066,
    2272,
    2499,
    2749,
    3024,
    3327,
    3660,
    4026,
    4428,
    4871,
    5358,
    5894,
    6484,
    7132,
    7845,
    8630,
    9493,
    10442,
    11487,
    12635,
    13899,
    15289,
    16818,
    18500,
    20350,
    22385,
    24623,
    27086,
    29794,
    32767,
]


def adpcm(x):
    """IMA-ADPCM passend zum Decoder in main.c (ansage_abspielen)."""
    pred, idx, out, halb = 0, 0, bytearray(), None
    for v in x:
        step = STEP[idx]
        d = v - pred
        code = 0
        if d < 0:
            code, d = 8, -d
        diff = step >> 3
        if d >= step:
            code |= 4
            d -= step
            diff += step
        if d >= step >> 1:
            code |= 2
            d -= step >> 1
            diff += step >> 1
        if d >= step >> 2:
            code |= 1
            diff += step >> 2
        pred = pred - diff if code & 8 else pred + diff
        pred = max(-32768, min(32767, pred))
        idx = max(0, min(88, idx + IDX[code]))
        if halb is None:
            halb = code
        else:
            out.append(halb | (code << 4))
            halb = None
    if halb is not None:
        out.append(halb)
    return bytes(out)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--stimme", default="Microsoft Katja")
    args = ap.parse_args()

    ZIEL.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix="vermerk_ansagen_"))
    jobs = [(str(tmp / f"{name}.wav"), text) for name, text in SAETZE.items()]
    sapi(jobs, args.stimme)

    for (datei, text), name in zip(jobs, SAETZE, strict=True):
        x = lesen(datei)
        daten = adpcm(x)
        (ZIEL / f"{name}.adpcm").write_bytes(daten)
        Path(datei).unlink()
        print(f"{name}: {len(x) / RATE:.1f} s, {len(daten)} Byte  ({text})")
    tmp.rmdir()


if __name__ == "__main__":
    main()
