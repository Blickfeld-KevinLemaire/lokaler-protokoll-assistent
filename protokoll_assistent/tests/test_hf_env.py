"""HF_TOKEN aus der Umgebung oder aus der .env im Projektordner."""

from protokoll_assistent.utils import hf_env


def _env(tmp_path, monkeypatch, inhalt: str):
    datei = tmp_path / ".env"
    datei.write_text(inhalt, encoding="utf-8")
    monkeypatch.setattr(hf_env, "_env_datei", lambda: datei)
    return datei


def test_ohne_umgebung_und_ohne_env_datei_kein_token():
    # Die Fixture '_keine_echten_tokens' blendet Umgebung und echte .env aus.
    assert not hf_env.has_hf_token()
    assert hf_env.get_hf_token_for_download() is None


def test_token_aus_env_datei(tmp_path, monkeypatch):
    _env(tmp_path, monkeypatch, "# Kommentar\nUID=1000\nHF_TOKEN=hf_aus_der_datei\nPROTOKOLL_SPRACHE=de\n")
    assert hf_env.has_hf_token()
    assert hf_env.get_hf_token_for_download() == "hf_aus_der_datei"


def test_umgebung_hat_vorrang_vor_der_env_datei(tmp_path, monkeypatch):
    _env(tmp_path, monkeypatch, "HF_TOKEN=hf_aus_der_datei\n")
    monkeypatch.setenv("HF_TOKEN", "hf_aus_der_umgebung")
    assert hf_env.get_hf_token_for_download() == "hf_aus_der_umgebung"


def test_env_datei_schreibweisen(tmp_path):
    datei = tmp_path / ".env"
    for zeile, erwartet in (
        ('HF_TOKEN="hf_mit_anfuehrung"', "hf_mit_anfuehrung"),
        ("export HF_TOKEN='hf_export'", "hf_export"),
        ("  HF_TOKEN = hf_leerzeichen  ", "hf_leerzeichen"),
        ("HF_TOKEN=", ""),
        ("# HF_TOKEN=hf_auskommentiert", ""),
        ("HF_TOKEN_ALT=hf_anderer_name", ""),
    ):
        datei.write_text(zeile + "\n", encoding="utf-8")
        assert hf_env._token_aus_env_datei(datei) == erwartet, zeile
    assert hf_env._token_aus_env_datei(tmp_path / "fehlt.env") == ""


def test_nur_hf_token_wird_gelesen_sonst_nichts(tmp_path, monkeypatch):
    _env(tmp_path, monkeypatch, "PROTOKOLL_SPRACHE=en\nHF_TOKEN=hf_x\n")
    monkeypatch.delenv("PROTOKOLL_SPRACHE", raising=False)
    hf_env.get_hf_token_for_download()
    import os

    assert "PROTOKOLL_SPRACHE" not in os.environ  # .env wird nicht in die Umgebung geladen
