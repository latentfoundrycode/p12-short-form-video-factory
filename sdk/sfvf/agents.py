from __future__ import annotations

from pathlib import Path
from typing import Any, TypedDict

from ._runtime import current_context


class Source(TypedDict):
    title: str
    url: str
    snippet: str


def _llm_stub(prompt: str, *, agent: str, model: str) -> str:
    return f"[dry-run llm] {agent}/{model}: {prompt}"


def _dict_for_schema(schema: dict[str, Any], stub: str) -> dict[str, Any]:
    properties = schema.get("properties")
    if not isinstance(properties, dict) or not properties:
        return {"text": stub}
    out: dict[str, Any] = {}
    for name, spec in properties.items():
        kind = spec.get("type") if isinstance(spec, dict) else None
        if kind == "string":
            out[name] = stub
        elif kind in ("integer", "number"):
            out[name] = 0
        elif kind == "array":
            out[name] = []
        elif kind == "object":
            out[name] = {}
        elif kind == "boolean":
            out[name] = False
        else:
            out[name] = stub
    return out


def llm(
    prompt: str,
    *,
    agent: str,
    model: str,
    schema: dict[str, Any] | None = None,
    attach: list[Path] | None = None,
) -> str | dict[str, Any]:
    ctx = current_context()
    if not ctx.dry_run:
        raise NotImplementedError(
            "agents.llm: the OpenRouter adapter arrives in Stage B; run with dry_run=True"
        )
    # attach is accepted and ignored; real vision attachment is Stage B.
    _ = attach
    stub = _llm_stub(prompt, agent=agent, model=model)
    if schema is not None:
        return _dict_for_schema(schema, stub)
    return stub


def research(query: str) -> list[Source]:
    ctx = current_context()
    if not ctx.dry_run:
        raise NotImplementedError(
            "agents.research: the OpenRouter adapter arrives in Stage B; run with dry_run=True"
        )
    return [
        Source(
            title=f"Overview of {query}",
            url="https://example.invalid/overview",
            snippet=f"A canned dry-run summary of {query}.",
        ),
        Source(
            title=f"Further reading on {query}",
            url="https://example.invalid/further",
            snippet=f"A second canned source mentioning {query}.",
        ),
    ]
