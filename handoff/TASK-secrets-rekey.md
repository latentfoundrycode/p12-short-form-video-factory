# TASK — `rekey`: re-encrypt the secret store under a new passphrase

## Goal (one sentence)
Add a `SecretStore.rekey(new_passphrase)` method and a `rekey` CLI subcommand so an operator can
change the master passphrase in place — instead of the delete-the-store-and-re-enter-every-key dance.

## The frozen contract (already committed — do not edit the test)
`tests/core/test_secrets.py` (the new `..._rekey...` tests) must pass. In summary:
- `SecretStore.rekey(new)` re-encrypts the store under `new`, preserving every secret; afterward the
  new passphrase opens it and the old one does not.
- Wrong CURRENT passphrase → `SecretsError`, store left intact (nothing written).
- Absent/empty store → `SecretsError` (never silently create an empty store under `new`).
- Empty `new` → `ValueError`, store intact.
- CLI `rekey` prompts for a new passphrase and a confirmation; on mismatch it returns non-zero and
  does not touch the store; on match it re-encrypts (exit 0).

## Change `app/core/secrets.py` only

### `SecretStore.rekey(self, new_passphrase: str) -> None`
Add this method (place it near `set`/`delete`):
- Reject an empty `new_passphrase` with `ValueError` (mirror the `__init__` check).
- If the store file is absent or empty (`not self._path.is_file() or self._path.stat().st_size == 0`)
  raise `SecretsError("no secret store to rekey at <path>")` — do NOT proceed (otherwise it would
  "succeed" without ever validating the current passphrase and would create an empty store).
- `secrets = self._load()` — this decrypts with the CURRENT passphrase, so a wrong current passphrase
  raises `SecretsError` here, before any write.
- Set `self._passphrase = new_passphrase` and call `self._save(secrets)`. `_save` is atomic (tempfile
  + `os.replace`) and picks a fresh salt, so a failure leaves the old store intact and the rewrite is
  keyed to the new passphrase.

### CLI `rekey` subcommand (in `main`)
- Register it: `sub.add_parser("rekey", help="re-encrypt the store under a new passphrase")`.
- The existing `store = SecretStore(_store_path(), _passphrase())` already supplies the CURRENT
  passphrase (env `SFVF_SECRETS_PASSPHRASE` or the interactive `Passphrase:` prompt). Inside the same
  `try` block, add an `elif args.command == "rekey":` branch that:
  - reads `new = getpass.getpass("New passphrase: ")` and a confirmation
    `getpass.getpass("Confirm new passphrase: ")`;
  - if they differ, `print("passphrases did not match", file=sys.stderr)` and `return 1` (before
    calling rekey — do not touch the store);
  - otherwise call `store.rekey(new)`.
- The existing `except (SecretsError, ValueError)` already maps a wrong current passphrase, an absent
  store, or an empty new passphrase to a clean non-zero exit — no new except needed.

## Constraints / do-nots
- Change ONLY `app/core/secrets.py`. Do NOT edit any test. Do NOT change the on-disk format, the KDF
  params, `_load`/`_save` internals, or any other command.
- The passphrase must never be printed or logged (getpass only; no echo).
- Keep `ruff` and `mypy` clean; match the surrounding style.

## Verify (from the worktree, `./.venv/Scripts/python.exe`)
- `-m pytest tests/core/test_secrets.py -q` → all pass (the 6 new rekey tests go green; the existing
  secrets tests stay green).
- `-m ruff check app` and `-m mypy sdk app` → clean.
