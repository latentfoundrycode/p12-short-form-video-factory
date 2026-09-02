from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ._runtime import current_context


@dataclass
class Source:
    title: str
    url: str
    snippet: str


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
    if schema is not None:
        return {"text": f"[dry-run llm] {agent}/{model}: {prompt}"}
    return f"[dry-run llm] {agent}/{model}: {prompt}"


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
