from __future__ import annotations

import contextvars
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .context import Context

_active: contextvars.ContextVar[Context | None] = contextvars.ContextVar(
    "sfvf_active_context", default=None
)


def set_active(ctx: Context) -> contextvars.Token[Context | None]:
    return _active.set(ctx)


def reset_active(token: contextvars.Token[Context | None]) -> None:
    _active.reset(token)


def current_context() -> Context:
    ctx = _active.get()
    if ctx is None:
        raise RuntimeError(
            "no active sfvf Context; provided functions may only be called"
            " inside a running workflow"
        )
    return ctx
