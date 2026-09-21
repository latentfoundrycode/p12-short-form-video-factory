from __future__ import annotations

import base64
import json
import math
from pathlib import Path
from typing import TYPE_CHECKING, Any, TypedDict

from ._ratelimit import LIMITER as _LIMITER
from ._runtime import current_context

if TYPE_CHECKING:
    import httpx2

    from .context import Context

_LIMITER.configure("openrouter", max_concurrency=2, min_interval_s=0.0)

_HTTP_TIMEOUT_S = 60.0
_RETRY_AFTER_DEFAULT_S = 1.0
_MAX_ATTEMPTS = 3
_RESEARCH_MODEL = "openai/gpt-4o-mini"
_IMAGE_MIME = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
}
_MAX_ATTACH_BYTES = 20 * 1024 * 1024  # 20 MiB per attachment
_MAX_ATTACH_COUNT = 8  # per llm() call


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


def _usage_cost(data: dict[str, Any]) -> float | None:
    """Return usage.cost when it is a finite non-negative number; otherwise None.

    A 200 may omit usage, set it to null, or put a non-number in cost. Treat those as
    unusable so a paid success is not followed by AttributeError/ValueError/OverflowError;
    the reservation then stands at the estimate.
    """
    usage = data.get("usage")
    if not isinstance(usage, dict):
        return None
    cost = usage.get("cost")
    if isinstance(cost, bool) or not isinstance(cost, int | float):
        return None
    try:
        amount = float(cost)
    except OverflowError:
        return None
    if not math.isfinite(amount) or amount < 0.0:
        return None
    return amount


def _instruction_text(ctx: Context) -> str:
    parts: list[str] = []
    for path in ctx.instructions:
        try:
            text = Path(path).read_text(encoding="utf-8").strip()
        except (OSError, UnicodeError):
            continue
        if text:
            parts.append(text)
    return "\n\n".join(parts)


def _post_chat_completion(ctx: Context, body: dict[str, Any]) -> dict[str, Any]:
    """POST /chat/completions with auth + rate limiting + retry; return the parsed 200 JSON.

    Reads the key via ctx.secret, builds the client via _http_client(), queues each attempt behind
    _LIMITER.slot("openrouter"); on 429 penalizes with the (validated) Retry-After and retries
    (bounded); 402 raises (insufficient credits); other non-2xx raises with status + body; returns
    resp.json() on 200. The bearer key is never logged or put in an error message.
    """
    instructions = _instruction_text(ctx)
    if instructions:
        body["messages"] = [
            {"role": "system", "content": instructions},
            *body["messages"],
        ]
    key = ctx.secret("OPENROUTER_API_KEY")
    token = ctx._budget_reserve("openrouter", "usd")
    unbilled = True  # nothing dispatched yet -> a failure before the first request releases
    try:
        with _http_client() as client:
            for _attempt in range(_MAX_ATTEMPTS):
                unbilled = True  # waiting on the limiter is not a dispatch
                with _LIMITER.slot("openrouter"):
                    unbilled = False  # about to dispatch; a transport error from here is AMBIGUOUS
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
                    unbilled = True
                    raise RuntimeError("OpenRouter: insufficient credits (402)")
                unbilled = True
                raise RuntimeError(f"OpenRouter error {resp.status_code}: {resp.text}")
            else:
                unbilled = True
                raise RuntimeError("OpenRouter: rate limited after retries (429)")

            # 200 (billed). Parse and reconcile the REAL cost INSIDE the client block, so it is
            # recorded BEFORE the client teardown. unbilled stays False (retain on any further
            # failure).
            try:
                data: dict[str, Any] = resp.json()
            except Exception as exc:
                raise RuntimeError("OpenRouter: unreadable 200 response body") from exc
            cost = _usage_cost(data)
            if cost is not None:
                ctx._budget_reconcile(token, actual=cost)
                ctx.emit(
                    {
                        "t": "cost",
                        "meter": "openrouter",
                        "unit": "usd",
                        "amount": cost,
                        "cached": False,
                    }
                )
            return data
    finally:
        if unbilled:
            ctx._budget_reconcile(token, actual=0.0, note="released")


def llm(
    prompt: str,
    *,
    agent: str,
    model: str,
    schema: dict[str, Any] | None = None,
    attach: list[Path | str] | None = None,
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
        items = tuple(attach)
        if len(items) > _MAX_ATTACH_COUNT:
            raise ValueError(f"too many attachments: {len(items)} (max {_MAX_ATTACH_COUNT})")
        parts: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
        base = ctx.paths.video.resolve()
        validated: list[tuple[Path, str]] = []
        for item in items:
            path = Path(item)
            if path.anchor:
                raise ValueError(f"attach must be a workspace-relative path: {item!r}")
            resolved = (ctx.paths.video / path).resolve()
            if not resolved.is_relative_to(base):
                raise ValueError(f"attach path escapes the workspace: {item!r}")
            if not resolved.is_file():
                raise ValueError(f"attach is not a regular file: {item!r}")
            mime = _IMAGE_MIME.get(resolved.suffix.lower())
            if mime is None:
                raise ValueError(f"attach is not an allowed image type: {item!r}")
            size = resolved.stat().st_size
            if size > _MAX_ATTACH_BYTES:
                raise ValueError(
                    f"attach exceeds size limit ({size} > {_MAX_ATTACH_BYTES}): {item!r}"
                )
            validated.append((resolved, mime))
        for resolved, mime in validated:
            encoded = base64.b64encode(resolved.read_bytes()).decode()
            parts.append(
                {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{encoded}"}}
            )
        messages: list[dict[str, Any]] = [{"role": "user", "content": parts}]
    else:
        messages = [{"role": "user", "content": prompt}]
    body: dict[str, Any] = {"model": model, "messages": messages}
    if schema is not None:
        body["response_format"] = {
            "type": "json_schema",
            "json_schema": {
                "name": "result",
                "strict": True,
                "schema": schema,
            },
        }

    data = _post_chat_completion(ctx, body)

    content = data["choices"][0]["message"]["content"]
    cost = _usage_cost(data)
    ctx.log(f"OpenRouter llm agent={agent} model={model} cost={cost}")
    if schema is not None:
        parsed: dict[str, Any] = json.loads(content)
        return parsed
    if not isinstance(content, str):
        raise RuntimeError("OpenRouter: expected string message content")
    return content


def research(query: str) -> list[Source]:
    ctx = current_context()
    if ctx.dry_run:
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

    body: dict[str, Any] = {
        "model": _RESEARCH_MODEL,
        "messages": [{"role": "user", "content": query}],
        "plugins": [{"id": "web"}],
    }
    data = _post_chat_completion(ctx, body)
    cost = _usage_cost(data)
    ctx.log(f"OpenRouter research model={_RESEARCH_MODEL} cost={cost}")

    message = data["choices"][0]["message"]
    sources: list[Source] = []
    for ann in message.get("annotations", []) or []:
        if ann.get("type") == "url_citation":
            c = ann["url_citation"]
            sources.append(
                Source(title=c.get("title", ""), url=c["url"], snippet=c.get("content", ""))
            )
    return sources
