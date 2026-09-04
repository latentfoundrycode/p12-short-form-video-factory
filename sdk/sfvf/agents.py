from __future__ import annotations

import json
import math
from pathlib import Path
from typing import TYPE_CHECKING, Any, TypedDict

from ._ratelimit import LIMITER as _LIMITER
from ._runtime import current_context

if TYPE_CHECKING:
    import httpx2

_LIMITER.configure("openrouter", max_concurrency=2, min_interval_s=0.0)

_HTTP_TIMEOUT_S = 60.0
_RETRY_AFTER_DEFAULT_S = 1.0
_MAX_ATTEMPTS = 3


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


def _http_client() -> httpx2.Client:
    try:
        import httpx2
    except ImportError as exc:
        raise RuntimeError(
            "agents.llm requires the 'httpx2' package. Install the SDK "
            "'openrouter' extra: pip install 'sfvf[openrouter]'."
        ) from exc
    return httpx2.Client(
        base_url="https://openrouter.ai/api/v1",
        timeout=_HTTP_TIMEOUT_S,
    )


def _retry_after_s(header: str | None) -> float:
    if header is None:
        return _RETRY_AFTER_DEFAULT_S
    try:
        value = float(header)
    except (TypeError, ValueError):
        return _RETRY_AFTER_DEFAULT_S
    if not math.isfinite(value) or value < 0:
        return _RETRY_AFTER_DEFAULT_S
    return value


def llm(
    prompt: str,
    *,
    agent: str,
    model: str,
    schema: dict[str, Any] | None = None,
    attach: list[Path] | None = None,
) -> str | dict[str, Any]:
    ctx = current_context()
    if ctx.dry_run:
        # attach is accepted and ignored; real vision attachment is Stage B.
        _ = attach
        stub = _llm_stub(prompt, agent=agent, model=model)
        if schema is not None:
            return _dict_for_schema(schema, stub)
        return stub

    if attach:
        raise NotImplementedError(
            "agents.llm vision attachments are not yet supported by the OpenRouter adapter"
        )
    key = ctx.secret("OPENROUTER_API_KEY")
    body: dict[str, Any] = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
    }
    if schema is not None:
        body["response_format"] = {
            "type": "json_schema",
            "json_schema": {
                "name": "result",
                "strict": True,
                "schema": schema,
            },
        }

    with _http_client() as client:
        for _attempt in range(_MAX_ATTEMPTS):
            with _LIMITER.slot("openrouter"):
                resp = client.post(
                    "/chat/completions",
                    headers={"Authorization": f"Bearer {key}"},
                    json=body,
                )
            if resp.status_code == 200:
                break
            if resp.status_code == 429:
                _LIMITER.penalize("openrouter", _retry_after_s(resp.headers.get("Retry-After")))
                continue
            if resp.status_code == 402:
                raise RuntimeError("OpenRouter: insufficient credits (402)")
            raise RuntimeError(f"OpenRouter error {resp.status_code}: {resp.text}")
        else:
            raise RuntimeError("OpenRouter: rate limited after retries (429)")

        data = resp.json()

    content = data["choices"][0]["message"]["content"]
    cost = data.get("usage", {}).get("cost")
    ctx.log(f"OpenRouter llm agent={agent} model={model} cost={cost}")
    if schema is not None:
        parsed: dict[str, Any] = json.loads(content)
        return parsed
    if not isinstance(content, str):
        raise RuntimeError("OpenRouter: expected string message content")
    return content


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
