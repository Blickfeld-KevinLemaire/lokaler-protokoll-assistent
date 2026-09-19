"""Eigenstaendiges Konsolen-Skript zum einmaligen Herunterladen aller
lokalen Modelle (Whisper-Modell, pyannote, Ollama).

Die eigentliche Download-Logik lebt in
``services/model_download_service.py`` und wird identisch auch vom
grafischen Einrichtungsassistenten der Anwendung verwendet (siehe
``gui/wizard.py``). Dieses Skript ist der Konsolen-/Automatisierungs-Weg,
z.B. fuer ``Einrichtung-Lokal.ps1``.

Der Hugging-Face-Token wird ENTWEDER aus der Umgebungsvariable HF_TOKEN
gelesen ODER -- falls nicht gesetzt -- einmalig verdeckt abgefragt
(``getpass``). Er wird in keinem Fall angezeigt, geloggt oder gespeichert.
"""

from __future__ import annotations

import argparse
import getpass
import sys

from services import model_download_service, model_service
from utils import setup_status
from utils.hf_env import disable_offline_mode


def _parse_args(argv: list[str]) -> argparse.Namespace:
    modell_ids = ", ".join(option.id for option in model_service.WHISPER_MODELLE)
    parser = argparse.ArgumentParser(description="Laedt alle lokalen Modelle herunter.")
    parser.add_argument(
        "--modell",
        default=None,
        help=(
            f"Whisper-Modell-ID (Standard: {model_service.WHISPER_MODEL_NAME}). "
            f"Kuratierte Auswahl: {modell_ids}. Andere gueltige faster-whisper-/"
            "CTranslate2-Modell-IDs sind ebenfalls erlaubt."
        ),
    )
    return parser.parse_args(argv)


def _prompt_for_token() -> str | None:
    print(
        "\nEs wurde noch kein HF_TOKEN in den Windows-Umgebungsvariablen gefunden.\n"
        "Der Token wird fuer diesen einmaligen Download benoetigt, aber NICHT gespeichert."
    )
    token = getpass.getpass("Hugging-Face-Token eingeben (Eingabe bleibt unsichtbar): ").strip()
    return token or None


def main() -> int:
    args = _parse_args(sys.argv[1:])
    print("=" * 72)
    print("PHASE 3: LOKALE MODELLE HERUNTERLADEN")
    print("=" * 72)
    if args.modell:
        print(f"Gewaehltes Whisper-Modell: {args.modell}")
    disable_offline_mode()  # fuer diesen einmaligen, bewussten Download

    results = model_download_service.download_all_models(
        print, get_token=_prompt_for_token, whisper_model=args.modell
    )
    ok = all(results.values())

    status = setup_status.load_status()
    setup_status.mark_phase(status, "modelle", ok, results)
    setup_status.save_status(status)

    print("\n" + "=" * 72)
    if ok:
        print("Alle benoetigten Modelle sind vollstaendig heruntergeladen.")
    else:
        print("Nicht alle Modelle konnten heruntergeladen werden. Bitte Fehler oben beheben und erneut ausfuehren.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
