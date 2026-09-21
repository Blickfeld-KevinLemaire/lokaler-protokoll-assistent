"""Mikrofonaufnahme (Voice Recording) fuer die Cloud-Variante.

Nimmt Ton ueber ein vom Betriebssystem erkanntes Audioeingabegeraet auf und
schreibt ihn als WAV-Datei nach 'eingabe/'. Die fertige Datei wird danach
genau wie eine von Hand ausgewaehlte oder per Drag & Drop abgelegte Aufnahme
weiterverarbeitet (siehe 'ProtokollGUI._setze_aufnahme' in
'protokoll_assistent_gui.py') - dieses Modul enthaelt keine eigene
Transkriptionslogik.

Die Auswahl des Aufnahmegeraets wird rechnerspezifisch in
'mikrofon_konfiguration.json' neben der Anwendung gespeichert (nicht
versioniert, siehe .gitignore) und beim naechsten Start automatisch wieder
vorausgewaehlt, sofern das Geraet noch angeschlossen ist.
"""

from __future__ import annotations

import array
import json
import queue
import threading
import wave
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import sounddevice as sd

from protokoll_assistent_v2 import APP_DIR

KONFIG_DATEI = APP_DIR / "mikrofon_konfiguration.json"

KANAELE = 1
SAMPLE_DTYPE = "int16"
SAMPLE_BREITE_BYTES = 2
BLOCKGROESSE = 1024
STANDARD_SAMPLERATE = 16000


@dataclass(frozen=True)
class Aufnahmegeraet:
    index: int
    name: str
    hostapi_name: str
    default_samplerate: float

    @property
    def anzeigename(self) -> str:
        return f"{self.name} ({self.hostapi_name})"


def liste_aufnahmegeraete(
    query_devices: Callable[..., Any] = sd.query_devices,
    query_hostapis: Callable[..., Any] = sd.query_hostapis,
) -> list[Aufnahmegeraet]:
    """Alle vom Betriebssystem erkannten Audioeingabegeraete."""
    hostapis = query_hostapis()
    geraete = []
    for eintrag in query_devices():
        if eintrag["max_input_channels"] < 1:
            continue
        hostapi_name = str(hostapis[eintrag["hostapi"]]["name"])
        geraete.append(
            Aufnahmegeraet(
                index=eintrag["index"],
                name=eintrag["name"],
                hostapi_name=hostapi_name,
                default_samplerate=eintrag["default_samplerate"],
            )
        )
    return geraete


def lade_gespeichertes_geraet() -> str | None:
    """Liefert den zuletzt gespeicherten Anzeigenamen oder None."""
    if not KONFIG_DATEI.is_file():
        return None
    try:
        daten = json.loads(KONFIG_DATEI.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    wert = daten.get("anzeigename")
    return str(wert) if wert else None


def speichere_geraet(anzeigename: str) -> None:
    KONFIG_DATEI.write_text(
        json.dumps({"anzeigename": anzeigename}, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def standard_eingabe_index() -> int | None:
    """Index des vom Betriebssystem als Standard markierten Eingabegeraets."""
    try:
        index = sd.default.device[0]
    except Exception:
        return None
    return index if index is not None and index >= 0 else None


def _standardgeraet(geraete: list[Aufnahmegeraet], standard_index: int | None) -> Aufnahmegeraet:
    if standard_index is not None and standard_index >= 0:
        for geraet in geraete:
            if geraet.index == standard_index:
                return geraet
    return geraete[0]


def waehle_startgeraet(
    geraete: list[Aufnahmegeraet],
    gespeichert: str | None,
    standard_index: int | None = None,
) -> tuple[Aufnahmegeraet | None, str | None]:
    """Bestimmt, welches Geraet beim Start vorausgewaehlt wird.

    Liefert (Geraet, Hinweistext). Der Hinweistext ist nur gesetzt, wenn ein
    gespeichertes Geraet nicht mehr verfuegbar war und auf ein anderes
    zurueckgefallen wurde.
    """
    if not geraete:
        return None, None
    if gespeichert:
        for geraet in geraete:
            if geraet.anzeigename == gespeichert:
                return geraet, None
        fallback = _standardgeraet(geraete, standard_index)
        return fallback, (
            f"Gespeichertes Geraet '{gespeichert}' nicht mehr verfuegbar - "
            f"'{fallback.anzeigename}' ausgewaehlt."
        )
    return _standardgeraet(geraete, standard_index), None


def erzeuge_dateiname() -> str:
    zeitstempel = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"Aufnahme_{zeitstempel}.wav"


class MikrofonAufnahme:
    """Nimmt von einem Aufnahmegeraet auf und schreibt eine WAV-Datei.

    Der Audio-Callback laeuft in einem von PortAudio verwalteten Thread und
    darf nicht blockieren - deshalb werden die Rohdaten nur in eine Queue
    gelegt; ein eigener Schreiber-Thread haengt sie an die WAV-Datei an.
    Waehrend einer Pause laeuft der Stream weiter (das Geraet bleibt
    reserviert), es werden aber keine Daten geschrieben - die Aufnahmedauer
    ergibt sich direkt aus den tatsaechlich geschriebenen Frames und muss
    deshalb nicht separat um Pausenzeiten bereinigt werden.
    """

    def __init__(
        self,
        geraet: Aufnahmegeraet,
        zielpfad: Path,
        stream_klasse: type = sd.RawInputStream,
    ) -> None:
        self.geraet = geraet
        self.zielpfad = zielpfad
        self._stream_klasse = stream_klasse
        self._samplerate = round(geraet.default_samplerate) or STANDARD_SAMPLERATE
        self._queue: queue.Queue[bytes | None] = queue.Queue()
        self._pausiert = threading.Event()
        self._geschrieben_frames = 0
        self._peak = 0.0
        self._lock = threading.Lock()
        self._stream: Any = None
        self._schreiber: threading.Thread | None = None
        self._wav: wave.Wave_write | None = None

    def start(self) -> None:
        self._wav = wave.open(str(self.zielpfad), "wb")
        self._wav.setnchannels(KANAELE)
        self._wav.setsampwidth(SAMPLE_BREITE_BYTES)
        self._wav.setframerate(self._samplerate)

        self._schreiber = threading.Thread(target=self._schreiben, daemon=True)
        self._schreiber.start()

        self._stream = self._stream_klasse(
            device=self.geraet.index,
            channels=KANAELE,
            samplerate=self._samplerate,
            dtype=SAMPLE_DTYPE,
            blocksize=BLOCKGROESSE,
            callback=self._callback,
        )
        self._stream.start()

    def _callback(self, indata: Any, frames: int, zeit: Any, status: Any) -> None:
        rohdaten = bytes(indata)
        self._aktualisiere_pegel(rohdaten)
        if not self._pausiert.is_set():
            self._queue.put(rohdaten)

    def _aktualisiere_pegel(self, rohdaten: bytes) -> None:
        werte = array.array("h")
        werte.frombytes(rohdaten)
        if not werte:
            return
        spitze = max(abs(min(werte)), abs(max(werte)))
        with self._lock:
            self._peak = min(1.0, spitze / 32768)

    def _schreiben(self) -> None:
        wav = self._wav
        if wav is None:
            return
        while True:
            rohdaten = self._queue.get()
            if rohdaten is None:
                break
            wav.writeframes(rohdaten)
            with self._lock:
                self._geschrieben_frames += len(rohdaten) // SAMPLE_BREITE_BYTES

    def pause(self) -> None:
        self._pausiert.set()

    def fortsetzen(self) -> None:
        self._pausiert.clear()

    @property
    def ist_pausiert(self) -> bool:
        return self._pausiert.is_set()

    @property
    def dauer_sekunden(self) -> float:
        with self._lock:
            return self._geschrieben_frames / self._samplerate

    @property
    def pegel(self) -> float:
        with self._lock:
            return self._peak

    def stop(self) -> Path:
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
        self._queue.put(None)
        if self._schreiber is not None:
            self._schreiber.join(timeout=5)
        if self._wav is not None:
            self._wav.close()
        return self.zielpfad
