from __future__ import annotations

import argparse
import base64
import getpass
import json
import os
import sys
import tempfile
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

from app.paths import APP_ROOT

SALT_SIZE = 16
_SCRYPT_N = 2**14
_SCRYPT_R = 8
_SCRYPT_P = 1
_KEY_LENGTH = 32
_DEFAULT_STORE = APP_ROOT / "secrets.enc"
_DECRYPT_FAILED = "wrong passphrase or corrupt secret store"


class SecretsError(Exception):
    """Raised when the store cannot be decrypted (wrong passphrase or corruption)."""


class SecretStore:
    def __init__(self, path: Path, passphrase: str) -> None:
        self._path = path
        self._passphrase = passphrase

    def names(self) -> list[str]:
        return sorted(self._load())

    def get(self, name: str) -> str:
        secrets = self._load()
        if name not in secrets:
            raise KeyError(name)
        return secrets[name]

    def all(self) -> dict[str, str]:
        return dict(self._load())

    def set(self, name: str, value: str) -> None:
        secrets = self._load()
        secrets[name] = value
        self._save(secrets)

    def delete(self, name: str) -> None:
        secrets = self._load()
        if name not in secrets:
            raise KeyError(name)
        del secrets[name]
        self._save(secrets)

    def _fernet(self, salt: bytes) -> Fernet:
        kdf = Scrypt(
            salt=salt,
            length=_KEY_LENGTH,
            n=_SCRYPT_N,
            r=_SCRYPT_R,
            p=_SCRYPT_P,
        )
        key = kdf.derive(self._passphrase.encode("utf-8"))
        return Fernet(base64.urlsafe_b64encode(key))

    def _load(self) -> dict[str, str]:
        path = self._path
        if not path.is_file() or path.stat().st_size == 0:
            return {}
        raw = path.read_bytes()
        if len(raw) <= SALT_SIZE:
            raise SecretsError(_DECRYPT_FAILED)
        salt, token = raw[:SALT_SIZE], raw[SALT_SIZE:]
        try:
            plaintext = self._fernet(salt).decrypt(token)
        except InvalidToken as exc:
            raise SecretsError(_DECRYPT_FAILED) from exc
        try:
            payload: object = json.loads(plaintext)
        except json.JSONDecodeError as exc:
            raise SecretsError(_DECRYPT_FAILED) from exc
        if not isinstance(payload, dict):
            raise SecretsError(_DECRYPT_FAILED)
        secrets: dict[str, str] = {}
        for key, value in payload.items():
            if not isinstance(key, str) or not isinstance(value, str):
                raise SecretsError(_DECRYPT_FAILED)
            secrets[key] = value
        return secrets

    def _save(self, secrets: dict[str, str]) -> None:
        salt = os.urandom(SALT_SIZE)
        token = self._fernet(salt).encrypt(json.dumps(secrets).encode("utf-8"))
        payload = salt + token
        path = self._path
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
        tmp_path = Path(tmp_name)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_path, path)  # noqa: PTH105  # os.replace is atomic on Windows
        except Exception:
            tmp_path.unlink(missing_ok=True)
            raise


def _passphrase() -> str:
    env = os.environ.get("SFVF_SECRETS_PASSPHRASE")
    if env is not None:
        return env
    return getpass.getpass("Passphrase: ")


def _store_path() -> Path:
    env = os.environ.get("SFVF_SECRETS_PATH")
    if env:
        return Path(env)
    return _DEFAULT_STORE


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="app.core.secrets")
    sub = parser.add_subparsers(dest="command", required=True)
    set_p = sub.add_parser("set", help="store a secret (value is prompted, never echoed)")
    set_p.add_argument("name")
    sub.add_parser("list", help="print secret names")
    del_p = sub.add_parser("delete", help="remove a secret")
    del_p.add_argument("name")
    args = parser.parse_args(argv)
    try:
        store = SecretStore(_store_path(), _passphrase())
        if args.command == "set":
            value = getpass.getpass("Value: ")
            store.set(args.name, value)
        elif args.command == "list":
            for name in store.names():
                print(name)
        elif args.command == "delete":
            store.delete(args.name)
    except SecretsError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except KeyError as exc:
        print(f"unknown secret: {exc.args[0]}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
