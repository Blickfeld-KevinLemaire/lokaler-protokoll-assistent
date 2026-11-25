"""Erkennung der Grafikkarte: ``grafikkarte-erkennen.sh`` (Rechner) und ``karten_des_rechners`` (Container).

Das Skript laeuft gegen ein nachgebautes ``/sys`` und ``/dev`` (GRAFIKKARTE_SYS/DEV), ohne echte Karte. Es braucht
eine Bash mit den ueblichen Werkzeugen (unter Windows Git Bash, in der CI vorhanden); die Bash des Windows-
Subsystems fuer Linux (System32) sieht die Pfade dieses Rechners nicht und wird uebersprungen."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from protokoll_assistent.services import grafikkarte_service

SKRIPT = Path(__file__).resolve().parents[2] / "grafikkarte-erkennen.sh"


def _bash() -> str | None:
    gefunden = shutil.which("bash")
    if gefunden is None or "system32" in gefunden.lower() or "windowsapps" in gefunden.lower():
        return None
    return gefunden


BASH = _bash()
nur_mit_bash = pytest.mark.skipif(BASH is None, reason="keine Bash (Git Bash) vorhanden")


def _karte(sys_ordner: Path, name: str, hersteller: str, *, pci: bool = True, drm: bool = True) -> None:
    if pci:
        geraet = sys_ordner / "bus" / "pci" / "devices" / f"0000_{name}"  # kein ":" -- unter Windows kein gueltiger Ordnername
        geraet.mkdir(parents=True)
        (geraet / "class").write_text("0x030000\n", encoding="ascii")
        (geraet / "vendor").write_text(f"{hersteller}\n", encoding="ascii")
    if drm:
        karte = sys_ordner / "class" / "drm" / name / "device"
        karte.mkdir(parents=True)
        (karte / "vendor").write_text(f"{hersteller}\n", encoding="ascii")
        # Anschluesse ("card0-HDMI-A-1") zaehlen nicht als Karte.
        (sys_ordner / "class" / "drm" / f"{name}-HDMI-A-1").mkdir()


def _geraete(dev: Path, *namen: str) -> None:
    for name in namen:
        pfad = dev / name
        pfad.parent.mkdir(parents=True, exist_ok=True)
        pfad.write_text("", encoding="ascii")


def _ausfuehren(
    tmp_path: Path,
    *argumente: str,
    arch: str = "x86_64",
    system: str = "Linux",
    programme_suchen: bool = False,
    pfad: str | None = None,
):
    assert BASH is not None
    umgebung = dict(os.environ)
    umgebung.update(
        GRAFIKKARTE_SYS=(tmp_path / "sys").as_posix(),
        GRAFIKKARTE_DEV=(tmp_path / "dev").as_posix(),
        GRAFIKKARTE_ARCH=arch,
        GRAFIKKARTE_OS=system,
        GRAFIKKARTE_ENV=(tmp_path / "test.env").as_posix(),
        GRAFIKKARTE_GRUPPEN=(tmp_path / "group").as_posix(),
        # nvidia-smi und nvidia-ctk dieses Rechners sollen das Ergebnis nicht beeinflussen.
        GRAFIKKARTE_OHNE_PROGRAMME="0" if programme_suchen else "1",
    )
    if pfad is not None:
        umgebung["PATH"] = pfad
    return subprocess.run(
        [BASH, SKRIPT.as_posix(), *argumente],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=umgebung,
        timeout=60,
        check=False,
    )


def _env(tmp_path: Path) -> dict[str, str]:
    zeilen = (tmp_path / "test.env").read_text(encoding="utf-8").splitlines()
    return dict(z.split("=", 1) for z in zeilen if "=" in z and not z.startswith("#"))


@nur_mit_bash
def test_ohne_karte_bleibt_es_beim_prozessor(tmp_path):
    (tmp_path / "sys").mkdir()
    lauf = _ausfuehren(tmp_path)
    assert lauf.returncode == 0, lauf.stderr
    assert _env(tmp_path)["COMPOSE_FILE"] == "docker-compose.yml"
    assert _env(tmp_path)["COMPOSE_PATH_SEPARATOR"] == ":"


@nur_mit_bash
@pytest.mark.parametrize(("arch", "erwartet"), [
    ("x86_64", "docker-compose.yml:docker-compose.gpu.yml"),
    ("aarch64", "docker-compose.yml:docker-compose.gpu.yml:docker-compose.gpu-arm.yml"),
])
def test_nvidia_hat_vorrang_und_arm_bekommt_die_arm_datei(tmp_path, arch, erwartet):
    # Typischer Fall: Intel-Prozessorgrafik neben einer NVIDIA-Karte ohne DRM-Eintrag (kein nvidia_drm).
    _karte(tmp_path / "sys", "card0", "0x8086")
    _karte(tmp_path / "sys", "card1", "0x10DE", drm=False)
    _geraete(tmp_path / "dev", "dri/renderD128")
    lauf = _ausfuehren(tmp_path, arch=arch)
    assert lauf.returncode == 0, lauf.stderr
    assert "NVIDIA" in lauf.stdout and "Intel" in lauf.stdout
    assert _env(tmp_path)["COMPOSE_FILE"] == erwartet


@nur_mit_bash
def test_amd_traegt_zwei_verschiedene_gruppen_ein(tmp_path):
    """Unter Fedora gehoeren /dev/kfd und renderD128 beide 'render'. Zweimal dieselbe Nummer in 'group_add'
    lehnt Compose ab ("items at 0 and 1 are equal") -- der Dienst startete gar nicht (25.11.2026). Hier gehoeren
    alle nachgebauten Geraete derselben Gruppe; die zweite kommt dann aus /etc/group ('video')."""
    _karte(tmp_path / "sys", "card0", "0x1002")
    _geraete(tmp_path / "dev", "kfd", "dri/renderD128")
    (tmp_path / "group").write_text("root:x:0:\nvideo:x:424242:\nrender:x:105:\n", encoding="ascii")
    lauf = _ausfuehren(tmp_path)
    assert lauf.returncode == 0, lauf.stderr
    env = _env(tmp_path)
    assert env["COMPOSE_FILE"] == "docker-compose.yml:docker-compose.amd.yml"
    assert env["RENDER_GID"].isdigit() and env["VIDEO_GID"] == "424242"
    assert env["VIDEO_GID"] != env["RENDER_GID"]


@nur_mit_bash
def test_amd_ohne_zweite_gruppe_ist_ein_fehler(tmp_path):
    _karte(tmp_path / "sys", "card0", "0x1002")
    _geraete(tmp_path / "dev", "kfd", "dri/renderD128")
    (tmp_path / "group").write_text("root:x:0:\n", encoding="ascii")
    lauf = _ausfuehren(tmp_path)
    assert lauf.returncode == 1 and "VIDEO_GID" in lauf.stderr
    assert not (tmp_path / "test.env").exists()


@nur_mit_bash
def test_amd_ohne_kfd_ist_ein_fehler_und_schreibt_nichts(tmp_path):
    _karte(tmp_path / "sys", "card0", "0x1002")
    _geraete(tmp_path / "dev", "dri/renderD128")
    lauf = _ausfuehren(tmp_path)
    assert lauf.returncode == 1 and "kfd" in lauf.stderr
    assert not (tmp_path / "test.env").exists()


@nur_mit_bash
def test_intel(tmp_path):
    _karte(tmp_path / "sys", "card0", "0x8086")
    _geraete(tmp_path / "dev", "dri/renderD128")
    lauf = _ausfuehren(tmp_path)
    assert lauf.returncode == 0, lauf.stderr
    assert _env(tmp_path)["COMPOSE_FILE"] == "docker-compose.yml:docker-compose.intel.yml"
    assert "Prozessor" in lauf.stdout


@nur_mit_bash
def test_vorhandene_env_wird_ergaenzt_nicht_ersetzt(tmp_path):
    (tmp_path / "sys").mkdir()
    (tmp_path / "test.env").write_text("HF_TOKEN=geheim\nCOMPOSE_FILE=alt.yml\n", encoding="utf-8")
    lauf = _ausfuehren(tmp_path, "--karte", "keine")
    assert lauf.returncode == 0, lauf.stderr
    env = _env(tmp_path)
    assert env["HF_TOKEN"] == "geheim" and env["COMPOSE_FILE"] == "docker-compose.yml"
    assert (tmp_path / "test.env").read_text(encoding="utf-8").count("COMPOSE_FILE=") == 1


@nur_mit_bash
def test_anzeigen_schreibt_nichts_und_falsche_angaben_fallen_auf(tmp_path):
    _karte(tmp_path / "sys", "card0", "0x8086")
    _geraete(tmp_path / "dev", "dri/renderD128")
    lauf = _ausfuehren(tmp_path, "--anzeigen")
    assert lauf.returncode == 0 and "docker-compose.intel.yml" in lauf.stdout
    assert not (tmp_path / "test.env").exists()
    assert _ausfuehren(tmp_path, "--karte", "tpu").returncode == 2
    assert _ausfuehren(tmp_path, "--quatsch").returncode == 2
    assert "Wahl vorgeben" in _ausfuehren(tmp_path, "--help").stdout


@nur_mit_bash
def test_nvidia_unter_linux_ohne_toolkit_ist_ein_fehler(tmp_path):
    _karte(tmp_path / "sys", "card0", "0x10de")
    # Diesmal werden Programme wirklich gesucht -- im Suchpfad stehen nur die Grundwerkzeuge.
    werkzeuge = sorted({Path(shutil.which(w) or "").parent for w in ("sed", "cat", "sort", "tr", "uname")})
    if any((ordner / "nvidia-ctk").exists() for ordner in werkzeuge):
        pytest.skip("Auf diesem Rechner liegt nvidia-ctk neben den Grundwerkzeugen.")
    lauf = _ausfuehren(tmp_path, programme_suchen=True, pfad=os.pathsep.join(str(o) for o in werkzeuge))
    assert lauf.returncode == 1 and "Container Toolkit" in lauf.stderr
    assert not (tmp_path / "test.env").exists()


# --------------------------------------------------------------------------
# Im Container: Karte des Rechners trotz Prozessor-Image bemerken
# --------------------------------------------------------------------------
def test_karten_des_rechners(tmp_path):
    assert grafikkarte_service.karten_des_rechners(tmp_path / "fehlt") == []
    _karte(tmp_path, "card0", "0x1002", pci=False)
    _karte(tmp_path, "card1", "0x10DE", drm=False)
    # Ein PCI-Geraet, das keine Anzeige ist (Netzwerkkarte von Intel), zaehlt nicht.
    netz = tmp_path / "bus" / "pci" / "devices" / "0000_netz"
    netz.mkdir(parents=True)
    (netz / "class").write_text("0x020000", encoding="ascii")
    (netz / "vendor").write_text("0x8086", encoding="ascii")
    assert grafikkarte_service.karten_des_rechners(tmp_path) == ["NVIDIA", "AMD"]


def test_prozessor_image_warnt_vor_ungenutzter_karte(monkeypatch):
    monkeypatch.setattr(grafikkarte_service, "karten_des_rechners", lambda: ["NVIDIA"])
    zeilen: list[str] = []
    assert grafikkarte_service.pruefen_und_melden(None, streng=False, ausgabe=zeilen.append, umgebung={}) is True
    assert "WARNUNG" in zeilen[-1] and "grafikkarte-erkennen.sh" in zeilen[-1]
