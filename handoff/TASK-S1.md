# TASK S1 — §5.6 encrypted secret store + CLI

**Builder:** Cursor. **Product code only.** Create `app/core/secrets.py` (new). `requirements.txt` already has
`cryptography==50.0.1` (supervisor-added). Do NOT touch `tests/`, `docs/`, `handoff/`. The reviewer contract
`tests/core/test_secrets.py` is FROZEN.

Build the encrypted secret store that holds provider keys (§5.6). **No real key is handled here** — this is the
mechanism; a human places real keys later via the CLI. Keys are encrypted at rest; the passphrase is never
stored; a wrong passphrase fails loudly; values never appear in plaintext on disk or in `list` output.

## Implement `app/core/secrets.py`

```python
class SecretsError(Exception): ...   # raised on wrong passphrase / corrupt store

class SecretStore:
    def __init__(self, path: Path, passphrase: str) -> None: ...
    def names(self) -> list[str]: ...          # sorted secret names (never values)
    def get(self, name: str) -> str: ...        # raises KeyError if absent
    def all(self) -> dict[str, str]: ...        # the decrypted mapping
    def set(self, name: str, value: str) -> None: ...
    def delete(self, name: str) -> None: ...    # raises KeyError if absent
```

Crypto & file format:
- Derive a 32-byte key from `passphrase` with **scrypt** (`cryptography.hazmat.primitives.kdf.scrypt.Scrypt`,
  sensible params, e.g. n=2**14, r=8, p=1) over a random 16-byte salt. Encrypt the JSON-serialized secret dict
  with **Fernet** (`base64.urlsafe_b64encode(key)` → `Fernet`).
- On-disk file = the salt followed by the Fernet token (e.g. `salt(16 bytes) + token`), written with
  `write_json_atomic`-style safety is NOT required, but write via a temp file + `os.replace` so a crash can't
  truncate it. The **whole** dict (names and values) is encrypted — no plaintext name or value on disk.
- **Load:** if the file is missing/empty → an empty dict. Read salt, derive key, `Fernet.decrypt` the token;
  on `cryptography.fernet.InvalidToken` (wrong passphrase or corruption) raise `SecretsError` with a clear
  message that does **not** include any secret value.
- `set`/`delete` load-modify-save (each op decrypts, mutates, re-encrypts). `get` raises `KeyError` for an
  absent name; `SecretsError` if the store can't be decrypted. Never log/print/`repr` a secret value anywhere.

## CLI — how a human places keys

A `main(argv: list[str] | None = None) -> int` entry (and `if __name__ == "__main__": raise SystemExit(main())`)
supporting:
- `set <NAME>` — read the value with **`getpass.getpass`** (no echo, never on the command line), store it.
- `list` — print the secret **names only**, one per line (never values).
- `delete <NAME>` — remove it.

Passphrase from `SFVF_SECRETS_PASSPHRASE` (env); if unset, prompt with `getpass.getpass`. Store path from
`SFVF_SECRETS_PATH` (env) with a sensible default. `import getpass` at module top (the test monkeypatches
`app.core.secrets.getpass.getpass`). On a wrong passphrase / `SecretsError`, print a short error to stderr and
**return a non-zero exit code** (no traceback dump). Success returns 0.

mypy-strict clean. Touch only `app/core/secrets.py`.

## Acceptance

`tests/core/test_secrets.py` passes (7 tests): round-trip across reopen; wrong passphrase → `SecretsError`;
value never in plaintext on disk; names sorted + delete + `KeyError`; missing file empty; CLI `set` then `list`
shows the name but not the value and the value is retrievable; CLI wrong passphrase → non-zero exit. Nothing
else regresses.

## Full local gate (from the worktree venv)

```
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe -m mypy
npm --prefix frontend run lint
npm --prefix frontend run typecheck
.\.venv\Scripts\python.exe -m pytest -q tests/core/test_secrets.py
```
(The full `pytest` run also shows 3 pre-existing `finalize`/`example_workflow` failures — ONLY the HyperFrames
toolchain missing in this worktree; CI installs it and runs them green. Ignore them.)
