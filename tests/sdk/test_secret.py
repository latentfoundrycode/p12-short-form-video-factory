"""B-4a contract: `ctx.secret(name)` reads a permitted secret from the ambient context.

The SDK spec shows `ctx.secret("OPENROUTER_API_KEY")` (§4 example). Secrets are supplied to a
workflow through `context.json`'s `secrets` dict (§5.6); `ctx.secret` is the SDK-side accessor
the provider adapters pull their credentials through. The full encrypted secret store + the
passphrase prompt (how a real key first *reaches* `context.json`) is app-layer and OUT OF
SCOPE here — this increment is only the read accessor. The value must never be logged or
written to records (redaction is §5.6's job); this contract pins the read behaviour and that a
missing-secret error does not leak other secrets' values.

The fake key here lives ONLY in the in-memory `ContextFile` the test constructs — it is never
written to disk and is never a real key.
"""

from pathlib import Path

import pytest
from sfvf.context import Context, ContextFile, ContextPaths


def _ctx(tmp: Path, *, secrets: dict[str, object]) -> Context:
    return Context(
        ContextFile(
            settings={},
            secrets=secrets,
            paths=ContextPaths(
                video=tmp,
                artifacts=tmp / "artifacts",
                steps=tmp / ".steps",
                shared=tmp,
            ),
        )
    )


def test_secret_returns_permitted_value(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path, secrets={"OPENROUTER_API_KEY": "sk-fake-inmemory-not-real"})
    assert ctx.secret("OPENROUTER_API_KEY") == "sk-fake-inmemory-not-real"


def test_secret_missing_raises_keyerror(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path, secrets={})
    with pytest.raises(KeyError):
        ctx.secret("OPENROUTER_API_KEY")


def test_secret_error_does_not_leak_other_values(tmp_path: Path) -> None:
    # A missing-secret error must name the requested key, never dump other secrets' values.
    ctx = _ctx(tmp_path, secrets={"OTHER_TOKEN": "sk-should-not-appear-anywhere"})
    with pytest.raises(KeyError) as exc:
        ctx.secret("OPENROUTER_API_KEY")
    assert "sk-should-not-appear-anywhere" not in str(exc.value)
