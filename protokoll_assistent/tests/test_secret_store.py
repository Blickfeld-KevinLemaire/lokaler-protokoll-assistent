"""Tests fuer 'services/secret_store.py'.

Nie den echten Windows-Anmeldeinformationsspeicher ansprechen: 'keyring'
wird komplett durch eine Attrappe ersetzt, indem 'sys.modules["keyring"]'
vor jedem Test gesetzt wird (der Import in 'secret_store._keyring()'
passiert erst innerhalb der Funktion, genau damit das moeglich ist)."""

from __future__ import annotations

import sys

import pytest

from protokoll_assistent.services import secret_store


class _KeyringAttrappe:
    def __init__(self):
        self.gespeichert: dict[tuple[str, str], str] = {}

    def set_password(self, service, key, value):
        self.gespeichert[(service, key)] = value

    def get_password(self, service, key):
        return self.gespeichert.get((service, key))

    def delete_password(self, service, key):
        if (service, key) not in self.gespeichert:
            raise KeyError("nicht gespeichert")
        del self.gespeichert[(service, key)]


@pytest.fixture
def keyring_attrappe(monkeypatch):
    attrappe = _KeyringAttrappe()
    monkeypatch.setitem(sys.modules, "keyring", attrappe)
    return attrappe


def test_speichern_und_lesen(keyring_attrappe):
    secret_store.save_api_key("transkription", "geheim-123")
    assert secret_store.load_api_key("transkription") == "geheim-123"


def test_lesen_ohne_vorherige_speicherung_liefert_none(keyring_attrappe):
    assert secret_store.load_api_key("nachbearbeitung") is None


def test_loeschen(keyring_attrappe):
    secret_store.save_api_key("transkription", "geheim-123")
    secret_store.delete_api_key("transkription")
    assert secret_store.load_api_key("transkription") is None


def test_loeschen_ohne_vorhandenen_schluessel_wirft_nicht(keyring_attrappe):
    secret_store.delete_api_key("transkription")  # darf nicht werfen


def test_schluessel_werden_unter_eigenem_dienstnamen_abgelegt(keyring_attrappe):
    secret_store.save_api_key("transkription", "geheim-123")
    assert (secret_store.SERVICE_NAME, "transkription") in keyring_attrappe.gespeichert


def test_fehlendes_keyring_paket_wird_klar_gemeldet(monkeypatch):
    monkeypatch.setitem(sys.modules, "keyring", None)
    monkeypatch.delitem(sys.modules, "keyring", raising=False)

    import builtins

    echter_import = builtins.__import__

    def import_ohne_keyring(name, *args, **kwargs):
        if name == "keyring":
            raise ImportError("kein Modul namens 'keyring'")
        return echter_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", import_ohne_keyring)

    with pytest.raises(secret_store.SecretStoreUnavailableError):
        secret_store.load_api_key("transkription")


def test_speicherfehler_wird_in_eigene_ausnahme_uebersetzt(keyring_attrappe):
    def werfen(*_a, **_k):
        raise RuntimeError("Anmeldeinformationsverwaltung nicht erreichbar")

    keyring_attrappe.set_password = werfen

    with pytest.raises(secret_store.SecretStoreUnavailableError):
        secret_store.save_api_key("transkription", "geheim-123")


def test_lesefehler_wird_in_eigene_ausnahme_uebersetzt(keyring_attrappe):
    def werfen(*_a, **_k):
        raise RuntimeError("Anmeldeinformationsverwaltung nicht erreichbar")

    keyring_attrappe.get_password = werfen

    with pytest.raises(secret_store.SecretStoreUnavailableError):
        secret_store.load_api_key("transkription")
