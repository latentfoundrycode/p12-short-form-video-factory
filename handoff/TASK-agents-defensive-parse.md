# TASK — defensive parsing of the OpenRouter 200 body (H11)

## Why
`agents.llm` and `agents.research` (`sdk/sfvf/agents.py`) trust the 200-response shape:
- `llm` (line ~257): `content = data["choices"][0]["message"]["content"]` raises an opaque
  `KeyError`/`IndexError`/`AttributeError`/`TypeError` on a malformed/unexpected body (no choices,
  empty choices, choice without `message`, message without `content`).
- `research` (line ~293): `message = data["choices"][0]["message"]` — same; and the annotation loop
  `c = ann["url_citation"]` / `c["url"]` raises `KeyError` if a `url_citation`-typed annotation lacks
  its inner object or its `url`.
OpenRouter today returns a well-formed object, but a proxy / aggregator / future API change could
send a malformed 200; the adapter should raise a CLEAR error (or skip) rather than an opaque one.
(`_usage_cost` is already defensive — do not touch it.)

Frozen RED tests (committed, do not modify):
`tests/sdk/test_agents.py::test_llm_raises_a_clear_error_on_a_malformed_body` (parametrized),
`::test_research_raises_a_clear_error_on_a_malformed_body`,
`::test_research_skips_malformed_url_citation_annotations`.

## Changes — only `sdk/sfvf/agents.py`

### 1. A helper to extract the first message, or raise a clear error
Add near `_usage_cost`:
```python
def _first_message(data: dict[str, Any]) -> dict[str, Any]:
    """Return choices[0].message, or raise a clear RuntimeError on an unexpected 200 body shape."""
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        raise RuntimeError("OpenRouter: response has no choices")
    message = choices[0].get("message")
    if not isinstance(message, dict):
        raise RuntimeError("OpenRouter: response choice has no message")
    return message
```

### 2. `llm` — use the helper and validate content is a string up front
Replace:
```python
    content = data["choices"][0]["message"]["content"]
    cost = _usage_cost(data)
    ctx.log(f"OpenRouter llm agent={agent} model={model} cost={cost}")
    if schema is not None:
        parsed: dict[str, Any] = json.loads(content)
        return parsed
    if not isinstance(content, str):
        raise RuntimeError("OpenRouter: expected string message content")
    return content
```
with:
```python
    content = _first_message(data).get("content")
    if not isinstance(content, str):
        raise RuntimeError("OpenRouter: expected string message content")
    cost = _usage_cost(data)
    ctx.log(f"OpenRouter llm agent={agent} model={model} cost={cost}")
    if schema is not None:
        parsed: dict[str, Any] = json.loads(content)
        return parsed
    return content
```
(Validating `content` is a `str` up front covers both the schema and non-schema paths — `json.loads`
no longer risks a non-str/None input.)

### 3. `research` — use the helper and skip malformed url_citations
Replace:
```python
    message = data["choices"][0]["message"]
    sources: list[Source] = []
    for ann in message.get("annotations", []) or []:
        if ann.get("type") == "url_citation":
            c = ann["url_citation"]
            sources.append(
                Source(title=c.get("title", ""), url=c["url"], snippet=c.get("content", ""))
            )
    return sources
```
with:
```python
    message = _first_message(data)
    sources: list[Source] = []
    for ann in message.get("annotations", []) or []:
        if not isinstance(ann, dict) or ann.get("type") != "url_citation":
            continue
        c = ann.get("url_citation")
        if not isinstance(c, dict) or not isinstance(c.get("url"), str):
            continue  # skip a malformed url_citation rather than raising mid-parse
        sources.append(
            Source(title=c.get("title", ""), url=c["url"], snippet=c.get("content", ""))
        )
    return sources
```

## Scope / do NOT
- Only `sdk/sfvf/agents.py`. Do NOT change `_usage_cost`, `_post_chat_completion`, the dry-run stubs,
  any test, or any stub. No new dependencies.

## Acceptance
- `PYTHONPATH=sdk python -m pytest tests/sdk/test_agents.py tests/integration/test_agents_openrouter_llm.py tests/integration/test_agents_openrouter_research.py -q`
  → all pass (the new H11 tests plus the existing dry-run + mocked-HTTP adapter tests — a well-formed
  body must still parse exactly as before).
- `ruff check sdk tests` and `ruff format --check sdk tests` clean; `.\.venv\Scripts\python.exe -m mypy` clean.
