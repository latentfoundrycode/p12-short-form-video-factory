"""S1 contract: the §5.6 encrypted secret store + CLI.

Keys/tokens are held in an encrypted file (`cryptography` Fernet, key derived from a passphrase
via scrypt). The passphrase is never stored; a wrong one fails loudly. Values never appear in
plaintext on disk, and the `list` CLI shows names only. The `set` CLI is how a human places a
real key (e.g. OPENROUTER_API_KEY / HIGGSFIELD_API_KEY) — the value is read without echoing.

All fake values here are test-only and live only under tmp_path; nothing real, nothing shipped.
"""

import pytest

from app.core.secrets import SecretsError, SecretStore, main


def test_set_get_round_trips_across_reopen(tmp_path):
    path = tmp_path / "secrets.enc"
    SecretStore(path, passphrase="correct horse battery").set("OPENROUTER_API_KEY", "sk-value")
    # A fresh store with the same passphrase reads the persisted, encrypted value back.
    reopened = SecretStore(path, passphrase="correct horse battery")
    assert reopened.get("OPENROUTER_API_KEY") == "sk-value"


def test_wrong_passphrase_fails_loudly(tmp_path):
    path = tmp_path / "secrets.enc"
    SecretStore(path, passphrase="right").set("K", "v")
    bad = SecretStore(path, passphrase="wrong")
    with pytest.raises(SecretsError):
        bad.get("K")


def test_value_never_appears_in_plaintext_on_disk(tmp_path):
    path = tmp_path / "secrets.enc"
    SecretStore(path, passphrase="pw").set("K", "super-secret-value-xyz")
    raw = path.read_bytes()
    assert b"super-secret-value-xyz" not in raw


def test_names_sorted_and_delete(tmp_path):
    path = tmp_path / "secrets.enc"
    store = SecretStore(path, passphrase="pw")
    store.set("B_KEY", "2")
    store.set("A_KEY", "1")
    assert store.names() == ["A_KEY", "B_KEY"]
    store.delete("A_KEY")
    assert store.names() == ["B_KEY"]
    with pytest.raises(KeyError):
        store.get("A_KEY")


def test_missing_file_is_empty(tmp_path):
    store = SecretStore(tmp_path / "absent.enc", passphrase="pw")
    assert store.names() == []
    with pytest.raises(KeyError):
        store.get("X")


def test_cli_set_then_list_hides_value(tmp_path, monkeypatch, capsys):
    path = tmp_path / "secrets.enc"
    monkeypatch.setenv("SFVF_SECRETS_PASSPHRASE", "pw")
    monkeypatch.setenv("SFVF_SECRETS_PATH", str(path))
    # `set` reads the value without echoing (getpass); no value on the command line.
    monkeypatch.setattr("app.core.secrets.getpass.getpass", lambda *a, **k: "sk-from-cli")

    assert main(["set", "OPENROUTER_API_KEY"]) == 0
    capsys.readouterr()

    assert main(["list"]) == 0
    out = capsys.readouterr().out
    assert "OPENROUTER_API_KEY" in out  # names are shown
    assert "sk-from-cli" not in out  # values are never shown

    # The value is retrievable programmatically with the same passphrase.
    assert SecretStore(path, passphrase="pw").get("OPENROUTER_API_KEY") == "sk-from-cli"


def test_cli_wrong_passphrase_returns_nonzero(tmp_path, monkeypatch, capsys):
    path = tmp_path / "secrets.enc"
    SecretStore(path, passphrase="right").set("K", "v")
    monkeypatch.setenv("SFVF_SECRETS_PASSPHRASE", "wrong")
    monkeypatch.setenv("SFVF_SECRETS_PATH", str(path))
    # `list` with the wrong passphrase fails cleanly (non-zero exit), not a traceback dump.
    assert main(["list"]) != 0
