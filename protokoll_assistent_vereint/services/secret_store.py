"""Dauerhafte, verschluesselte Ablage von API-Schluesseln.

Weder die Cloud- noch die lokale Anwendung speichern bislang irgendein
Geheimnis auf der Platte (siehe CLAUDE.md, Regel 3: nie in eine Datei, nur
Umgebungsvariable oder Sitzungsspeicher). Die vereinte Anwendung erlaubt dem
Anwender ausdruecklich, einen Schluessel dauerhaft zu merken - dafuer wird
hier NICHT einfach eine JSON-Datei beschrieben, sondern die Windows-
Anmeldeinformationsverwaltung ueber das Paket 'keyring' benutzt. Der
Schluessel steht damit nie im Klartext auf der Platte.

Dies ist der EINZIGE Ort im Projekt, der 'keyring' importiert - aufrufender
Code (GUI, Services) ruft ausschliesslich die drei Funktionen hier, nie
'keyring' direkt. Das macht die Speicherung austauschbar und testbar (Tests
ersetzen diese drei Funktionen, nie den echten Anmeldeinformationsspeicher).

'keyring' wird bewusst erst innerhalb der Funktionen importiert, nicht am
Modulanfang: Startet die vereinte Anwendung im lokalen Modus in der von
'lokale_windows_app/bootstrap.py' selbst verwalteten Laufzeitumgebung
('runtime\\venv'), enthaelt diese heute nur die dort gelistete
'requirements-laufzeit.txt' - ohne 'keyring'. Ein Import am Modulanfang
wuerde dort den kompletten Start der Anwendung verhindern, obwohl das
Merken von Schluesseln nur eine optionale Zusatzfunktion ist.
"""

from __future__ import annotations

SERVICE_NAME = "ProtokollAssistentVereint"


class SecretStoreUnavailableError(RuntimeError):
    """Das Paket 'keyring' fehlt oder es steht kein nutzbarer
    Anmeldeinformationsspeicher zur Verfuegung."""


def _keyring():
    try:
        import keyring
    except ImportError as error:
        raise SecretStoreUnavailableError(
            "Fuer das dauerhafte Merken eines API-Schluessels wird das Paket "
            "'keyring' benoetigt, das in dieser Laufzeitumgebung nicht "
            "installiert ist."
        ) from error
    return keyring


def save_api_key(key_name: str, value: str) -> None:
    """Speichert den Schluessel verschluesselt (Windows-
    Anmeldeinformationsverwaltung). 'key_name' ist z. B. 'transkription'
    oder 'nachbearbeitung' - kein Geheimnis selbst, nur ein Bezeichner."""
    keyring = _keyring()
    try:
        keyring.set_password(SERVICE_NAME, key_name, value)
    except Exception as error:  # keyring.errors.* je nach Backend
        raise SecretStoreUnavailableError(
            f"Der Schluessel '{key_name}' konnte nicht gespeichert werden: {error}"
        ) from error


def load_api_key(key_name: str) -> str | None:
    """Liest einen zuvor gespeicherten Schluessel. Liefert 'None', wenn
    noch keiner hinterlegt wurde - das ist kein Fehler."""
    keyring = _keyring()
    try:
        return keyring.get_password(SERVICE_NAME, key_name)
    except Exception as error:
        raise SecretStoreUnavailableError(
            f"Der Schluessel '{key_name}' konnte nicht gelesen werden: {error}"
        ) from error


def delete_api_key(key_name: str) -> None:
    """Entfernt einen gespeicherten Schluessel. Kein Fehler, wenn keiner
    hinterlegt war."""
    keyring = _keyring()
    try:
        keyring.delete_password(SERVICE_NAME, key_name)
    except Exception:  # noqa: S110 - "war eh nicht gespeichert" ist kein Fehlerfall
        pass
