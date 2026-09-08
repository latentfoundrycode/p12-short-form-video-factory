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


def test_store_file_has_a_format_version_header(tmp_path):
    # A 1-byte version header lets the KDF params be strengthened later without breaking
    # existing stores (the reader dispatches params by version).
    path = tmp_path / "secrets.enc"
    SecretStore(path, passphrase="pw").set("K", "v")
    assert path.read_bytes()[0] == 1
    # round-trips through the versioned format
    assert SecretStore(path, passphrase="pw").get("K") == "v"


def test_current_kdf_cost_meets_2026_floor():
    # The current format version's scrypt cost must meet a 2026-appropriate floor so offline
    # guessing of a copied store is expensive. (n=2**16 minimum; brief specifies 2**17.)
    from app.core.secrets import _CURRENT_KDF_N

    assert _CURRENT_KDF_N >= 2**16


def test_empty_passphrase_is_rejected(tmp_path):
    # An empty passphrase would encrypt the store with a trivially-guessable key — reject it.
    with pytest.raises(ValueError):
        SecretStore(tmp_path / "secrets.enc", passphrase="")


def test_cli_empty_passphrase_returns_nonzero(tmp_path, monkeypatch):
    monkeypatch.setenv("SFVF_SECRETS_PASSPHRASE", "")
    monkeypatch.setenv("SFVF_SECRETS_PATH", str(tmp_path / "secrets.enc"))
    assert main(["list"]) != 0


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


# --- rekey: re-encrypt the whole store under a new passphrase (no delete-and-recreate) ---


def test_rekey_re_encrypts_and_preserves_all_secrets(tmp_path):
    path = tmp_path / "secrets.enc"
    store = SecretStore(path, passphrase="old-pass")
    store.set("OPENROUTER_API_KEY", "sk-openrouter")
    store.set("HIGGSFIELD_API_KEY", "hf-id:hf-secret")

    SecretStore(path, passphrase="old-pass").rekey("new-pass")

    # The new passphrase opens the store and every secret survived unchanged.
    reopened = SecretStore(path, passphrase="new-pass")
    assert reopened.names() == ["HIGGSFIELD_API_KEY", "OPENROUTER_API_KEY"]
    assert reopened.get("OPENROUTER_API_KEY") == "sk-openrouter"
    assert reopened.get("HIGGSFIELD_API_KEY") == "hf-id:hf-secret"
    # The OLD passphrase no longer works.
    with pytest.raises(SecretsError):
        SecretStore(path, passphrase="old-pass").get("OPENROUTER_API_KEY")


def test_rekey_wrong_current_passphrase_fails_and_leaves_store_intact(tmp_path):
    path = tmp_path / "secrets.enc"
    SecretStore(path, passphrase="right").set("K", "v")
    # Rekey attempted with the wrong CURRENT passphrase must fail before writing anything.
    with pytest.raises(SecretsError):
        SecretStore(path, passphrase="wrong").rekey("new-pass")
    # The original passphrase still opens the untouched store; the (never-used) new one does not.
    assert SecretStore(path, passphrase="right").get("K") == "v"
    with pytest.raises(SecretsError):
        SecretStore(path, passphrase="new-pass").get("K")


def test_rekey_on_absent_store_raises(tmp_path):
    # Rekey must not silently create an empty store under a new passphrase for a store that isn't
    # there (that would "succeed" without ever validating the current passphrase).
    with pytest.raises(SecretsError):
        SecretStore(tmp_path / "absent.enc", passphrase="whatever").rekey("new-pass")


def test_rekey_empty_new_passphrase_rejected_and_store_intact(tmp_path):
    path = tmp_path / "secrets.enc"
    SecretStore(path, passphrase="pw").set("K", "v")
    with pytest.raises(ValueError):
        SecretStore(path, passphrase="pw").rekey("")
    # The store is unchanged: still opens under the original passphrase.
    assert SecretStore(path, passphrase="pw").get("K") == "v"


def test_cli_rekey_re_encrypts_under_new_passphrase(tmp_path, monkeypatch):
    path = tmp_path / "secrets.enc"
    SecretStore(path, passphrase="old-pass").set("OPENROUTER_API_KEY", "sk-value")
    # The current passphrase comes from the env; the NEW one (and its confirmation) via getpass.
    monkeypatch.setenv("SFVF_SECRETS_PASSPHRASE", "old-pass")
    monkeypatch.setenv("SFVF_SECRETS_PATH", str(path))
    monkeypatch.setattr("app.core.secrets.getpass.getpass", lambda *a, **k: "new-pass")

    assert main(["rekey"]) == 0
    assert SecretStore(path, passphrase="new-pass").get("OPENROUTER_API_KEY") == "sk-value"


def test_cli_rekey_mismatched_confirmation_returns_nonzero_and_store_intact(tmp_path, monkeypatch):
    path = tmp_path / "secrets.enc"
    SecretStore(path, passphrase="old-pass").set("K", "v")
    monkeypatch.setenv("SFVF_SECRETS_PASSPHRASE", "old-pass")
    monkeypatch.setenv("SFVF_SECRETS_PATH", str(path))
    # New passphrase and its confirmation differ → refuse without touching the store.
    entries = iter(["new-pass", "typo-different"])
    monkeypatch.setattr("app.core.secrets.getpass.getpass", lambda *a, **k: next(entries))

    assert main(["rekey"]) != 0
    # Store untouched: original passphrase still works; neither typed new value opens it.
    assert SecretStore(path, passphrase="old-pass").get("K") == "v"
    for candidate in ("new-pass", "typo-different"):
        with pytest.raises(SecretsError):
            SecretStore(path, passphrase=candidate).get("K")


def test_rekey_restores_passphrase_on_save_failure(tmp_path, monkeypatch):
    # If the atomic re-save fails after a successful decrypt, the on-disk store is left keyed to the
    # OLD passphrase (unchanged) — so the in-memory object must NOT keep the new passphrase, or a
    # later operation on the same reusable instance would raise a misleading SecretsError.
    path = tmp_path / "secrets.enc"
    store = SecretStore(path, passphrase="old-pass")
    store.set("K", "v")

    def _boom(*_a, **_k):
        raise OSError("simulated write failure")

    monkeypatch.setattr(store, "_save", _boom)
    with pytest.raises(OSError):
        store.rekey("new-pass")
    # The same object still reads the untouched store — i.e. it kept the OLD passphrase.
    assert store.get("K") == "v"
