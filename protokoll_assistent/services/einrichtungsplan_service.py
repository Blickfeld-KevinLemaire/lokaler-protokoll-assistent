"""Was ist auf diesem Computer moeglich, und was kostet es?

Baut auf ``rechner_analyse_service`` auf (welche Modelle hier laufen) und
uebersetzt das fuer die Ersteinrichtung in die Sprache der Anwender:

* ``schaetze``      -- je Arbeitsschritt: geht gut / langsam / nicht, und wie
                       lange eine Stunde Aufnahme ungefaehr dauert; dazu eine
                       Empfehlung (alles lokal, gemischt, online).
* ``bausteine_fuer`` -- was fuer die gewaehlte Arbeitsweise geladen werden muss,
                       mit Download- und Platzbedarf.

Gemessen sind nur die Werte auf einem Laptop mit NVIDIA RTX PRO 500 (6 GB)
am 04.10.2026, 66 Minuten Material (research/e2e-testbericht-2026-10.md).
Alles andere ist daraus abgeleitet oder geschaetzt -- die Oberflaeche sagt
deshalb immer "etwa".
"""

from __future__ import annotations

from dataclasses import dataclass, field

from protokoll_assistent.services import model_service, ollama_service, rechner_analyse_service
from protokoll_assistent.services.rechner_analyse_service import GUT, MAESSIG, NICHT, Analyse

SCHRITT_MITSCHRIFT = "Mitschrift"
SCHRITT_SPRECHER = "Sprechererkennung"
SCHRITT_PROTOKOLL = "Protokoll"
SCHRITT_CHAT = "Frag mein Meeting"

EMPFEHLUNG_LOKAL = "lokal"
EMPFEHLUNG_GEMISCHT = "gemischt"
EMPFEHLUNG_API = "api"

# Gemessen (66 min Material -> Minuten je Stunde Aufnahme).
MITSCHRIFT_GPU_MIN_JE_STUNDE = (3, 5)  # 2:53 min
SPRECHER_GPU_MIN_JE_STUNDE = (5, 8)  # 5:04 min
SPRECHER_CPU_MIN_JE_STUNDE = 23  # 25 min, 16 Kerne
PROTOKOLL_GPU_MIN_JE_STUNDE = (20, 30)  # 21 bzw. 31 min
# NICHT gemessen: wie viel langsamer das Protokoll auf dem Prozessor entsteht.
PROTOKOLL_CPU_FAKTOR = (3, 6)
CHAT_GPU_SEKUNDEN = (10, 30)  # gemessen 11-21 s je Frage (passende Ausschnitte)
CHAT_CPU_SEKUNDEN = (30, 120)  # geschaetzt

# Download- und Platzbedarf, soweit nicht in den Modelllisten (GB).
OLLAMA_DOWNLOAD_GB = 1.6  # OllamaSetup.exe 0.35.1: 1,58 GB
OLLAMA_PLATZ_GB = 2.9  # installiert gemessen 2,8 GB
LAUFZEIT_GPU_DOWNLOAD_GB = 3.0  # geschaetzt (PyTorch mit CUDA)
LAUFZEIT_GPU_PLATZ_GB = 5.6  # gemessen: runtime\venv
LAUFZEIT_CPU_DOWNLOAD_GB = 0.8  # geschaetzt
LAUFZEIT_CPU_PLATZ_GB = 1.5  # geschaetzt
FFMPEG_GB = 0.2
WHISPER_SMALL_GB = 0.5


@dataclass(frozen=True)
class Schritteinschaetzung:
    schritt: str
    stufe: str
    text: str


@dataclass
class Moeglichkeiten:
    schritte: list[Schritteinschaetzung] = field(default_factory=list)
    # EMPFEHLUNG_* oder None: beides moeglich, der Anwender entscheidet.
    empfehlung: str | None = None
    begruendung: str = ""


@dataclass(frozen=True)
class Baustein:
    kennung: str
    name: str
    download_gb: float
    platz_gb: float
    hinweis: str = ""
    vorhanden: bool = False


def formatiere_dauer(von: float, bis: float) -> str:
    """'etwa 3–5 Minuten', 'etwa 1–3 Stunden'. Ab anderthalb Stunden in Stunden
    (die obere Grenze rundet dann immer auf mindestens zwei)."""
    if bis >= 90:
        von_h, bis_h = max(1, round(von / 60)), round(bis / 60)
        return f"etwa {bis_h} Stunden" if von_h == bis_h else f"etwa {von_h}–{bis_h} Stunden"
    von_m, bis_m = max(1, round(von)), max(1, round(bis))
    if von_m == bis_m:
        return "etwa 1 Minute" if von_m == 1 else f"etwa {von_m} Minuten"
    return f"etwa {von_m}–{bis_m} Minuten"


def _stufe_von(analyse: Analyse, bereich: str) -> str:
    modell = analyse.empfehlung.get(bereich)
    if modell is None:
        return NICHT
    return next((b.stufe for b in analyse.bewertungen if b.bereich == bereich and b.modell_id == modell), NICHT)


def _mitschrift(analyse: Analyse) -> Schritteinschaetzung:
    stufe = _stufe_von(analyse, rechner_analyse_service.BEREICH_TRANSKRIPTION)
    if stufe == NICHT:
        return Schritteinschaetzung(SCHRITT_MITSCHRIFT, NICHT, "Auf diesem Computer nicht sinnvoll – besser online.")
    profil = analyse.profil
    von: float
    bis: float
    if profil.cuda_gpu:
        von, bis = MITSCHRIFT_GPU_MIN_JE_STUNDE
        ort = "auf der Grafikkarte"
    else:
        modell = analyse.empfehlung[rechner_analyse_service.BEREICH_TRANSKRIPTION] or ""
        echtzeit = rechner_analyse_service.CPU_ECHTZEIT_FAKTOR.get(modell, 1.0) * rechner_analyse_service._cpu_faktor(profil)
        von, bis = 60 / echtzeit, 60 / echtzeit * 1.5
        ort = "auf dem Prozessor"
    return Schritteinschaetzung(SCHRITT_MITSCHRIFT, stufe, f"{formatiere_dauer(von, bis)} je Stunde Aufnahme ({ort})")


def _sprecher(analyse: Analyse, mitschrift: Schritteinschaetzung) -> Schritteinschaetzung:
    if mitschrift.stufe == NICHT:
        return Schritteinschaetzung(SCHRITT_SPRECHER, NICHT, "Nur zusammen mit der Mitschrift auf diesem Computer.")
    if analyse.profil.cuda_gpu:
        von, bis = SPRECHER_GPU_MIN_JE_STUNDE
        return Schritteinschaetzung(SCHRITT_SPRECHER, GUT, f"{formatiere_dauer(von, bis)} je Stunde (Grafikkarte)")
    minuten = SPRECHER_CPU_MIN_JE_STUNDE / rechner_analyse_service._cpu_faktor(analyse.profil)
    return Schritteinschaetzung(
        SCHRITT_SPRECHER, MAESSIG, f"{formatiere_dauer(minuten, minuten * 1.5)} je Stunde (Prozessor) – optional"
    )


def _protokoll(analyse: Analyse) -> Schritteinschaetzung:
    stufe = _stufe_von(analyse, rechner_analyse_service.BEREICH_NACHBEARBEITUNG)
    if stufe == NICHT:
        return Schritteinschaetzung(SCHRITT_PROTOKOLL, NICHT, "Auf diesem Computer nicht sinnvoll – besser online.")
    von, bis = PROTOKOLL_GPU_MIN_JE_STUNDE
    if analyse.profil.cuda_gpu and stufe == GUT:
        return Schritteinschaetzung(SCHRITT_PROTOKOLL, GUT, f"{formatiere_dauer(von, bis)} je Stunde Aufnahme")
    faktor_von, faktor_bis = PROTOKOLL_CPU_FAKTOR
    return Schritteinschaetzung(
        SCHRITT_PROTOKOLL, MAESSIG, f"{formatiere_dauer(von * faktor_von, bis * faktor_bis)} je Stunde Aufnahme"
    )


def _chat(analyse: Analyse, protokoll: Schritteinschaetzung) -> Schritteinschaetzung:
    suche = _stufe_von(analyse, rechner_analyse_service.BEREICH_SUCHE)
    if protokoll.stufe == NICHT or suche == NICHT:
        return Schritteinschaetzung(SCHRITT_CHAT, NICHT, "Auf diesem Computer nicht sinnvoll – besser online.")
    von, bis = CHAT_GPU_SEKUNDEN if protokoll.stufe == GUT else CHAT_CPU_SEKUNDEN
    dauer = f"etwa {von}–{bis} Sekunden" if bis < 90 else f"etwa {max(1, round(von / 60))}–{round(bis / 60)} Minuten"
    return Schritteinschaetzung(SCHRITT_CHAT, protokoll.stufe, f"{dauer} je Frage")


def schaetze(analyse: Analyse) -> Moeglichkeiten:
    mitschrift = _mitschrift(analyse)
    protokoll = _protokoll(analyse)
    schritte = [mitschrift, _sprecher(analyse, mitschrift), protokoll, _chat(analyse, protokoll)]
    if mitschrift.stufe == NICHT:
        empfehlung: str | None = EMPFEHLUNG_API
        begruendung = (
            "Für die Mitschrift ist dieser Computer zu schwach ausgestattet. Empfehlung: ein Online-Dienst."
        )
    elif protokoll.stufe == NICHT:
        empfehlung = EMPFEHLUNG_GEMISCHT
        begruendung = (
            "Die Mitschrift klappt auf diesem Computer, für das Protokoll reicht er aber nicht. "
            "Empfehlung: Mitschrift hier, Protokoll über einen Online-Dienst."
        )
    elif protokoll.stufe == GUT and mitschrift.stufe == GUT:
        empfehlung = EMPFEHLUNG_LOKAL
        begruendung = "Dieser Computer schafft alles selbst. Empfehlung: alles auf diesem Computer – nichts verlässt ihn."
    else:
        empfehlung = None
        begruendung = (
            "Alles geht auch auf diesem Computer, braucht aber Geduld. Ein Online-Dienst ist schneller, "
            "dafür gehen Ihre Daten an den Anbieter. Sie entscheiden."
        )
    return Moeglichkeiten(schritte=schritte, empfehlung=empfehlung, begruendung=begruendung)


def bausteine_fuer(
    *,
    transkription_lokal: bool,
    nachbearbeitung_lokal: bool,
    chat_lokal: bool,
    cuda_gpu: bool,
    whisper_modell: str,
    sprachmodell: str,
    einbettungsmodell: str,
    vorhanden: dict[str, bool] | None = None,
) -> list[Baustein]:
    """Was fuer die gewaehlte Arbeitsweise geladen werden muss."""
    da = vorhanden or {}

    def baustein(kennung: str, name: str, download: float, platz: float, hinweis: str = "") -> Baustein:
        return Baustein(kennung, name, download, platz, hinweis, da.get(kennung, False))

    teile = [baustein("ffmpeg", "FFmpeg (liest Audio- und Videodateien)", FFMPEG_GB, FFMPEG_GB)]
    if nachbearbeitung_lokal or chat_lokal:
        teile.append(
            baustein(
                "ollama",
                "Ollama (führt die Sprachmodelle aus)",
                OLLAMA_DOWNLOAD_GB,
                OLLAMA_PLATZ_GB,
                "Startet künftig mit Windows und läuft unauffällig im Hintergrund – nur auf diesem Computer erreichbar.",
            )
        )
        option = ollama_service.get_modell_option(sprachmodell)
        groesse = option.groesse_gb if option else 4.0
        teile.append(baustein("sprachmodell", f"Sprachmodell {sprachmodell} (schreibt Protokoll und Antworten)", groesse, groesse))
    if chat_lokal:
        option = ollama_service.get_modell_option(einbettungsmodell)
        groesse = option.groesse_gb if option else 1.2
        teile.append(baustein("einbettung", f"Suchmodell {einbettungsmodell} (für „Frag mein Meeting“)", groesse, groesse))
    if transkription_lokal:
        if cuda_gpu:
            laufzeit = baustein(
                "laufzeit", "Rechenumgebung für die Grafikkarte (PyTorch, CUDA)", LAUFZEIT_GPU_DOWNLOAD_GB,
                LAUFZEIT_GPU_PLATZ_GB, "Das Programm startet dafür einmal neu.",
            )
        else:
            laufzeit = baustein(
                "laufzeit", "Rechenumgebung (PyTorch)", LAUFZEIT_CPU_DOWNLOAD_GB, LAUFZEIT_CPU_PLATZ_GB,
                "Das Programm startet dafür einmal neu.",
            )
        whisper_gb = (
            rechner_analyse_service.GROESSE_WHISPER_TURBO_GB
            if whisper_modell == model_service.WHISPER_MODEL_NAME
            else WHISPER_SMALL_GB
        )
        teile += [
            laufzeit,
            baustein("whisper", f"Spracherkennung Whisper {whisper_modell}", whisper_gb, whisper_gb),
            baustein(
                "pyannote",
                "Sprechererkennung (pyannote)",
                rechner_analyse_service.GROESSE_PYANNOTE_GB,
                rechner_analyse_service.GROESSE_PYANNOTE_GB,
                "Braucht einen kostenlosen Zugang bei Hugging Face – dazu später mehr.",
            ),
        ]
    return teile


def summe(bausteine: list[Baustein]) -> tuple[float, float]:
    """(Download, Platz) in GB -- nur fuer das, was noch fehlt."""
    fehlend = [b for b in bausteine if not b.vorhanden]
    return sum(b.download_gb for b in fehlend), sum(b.platz_gb for b in fehlend)


def download_minuten(gb: float, mbit_je_sekunde: float = 50) -> float:
    return gb * 1024 * 8 / mbit_je_sekunde / 60
