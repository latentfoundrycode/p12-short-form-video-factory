# TASK — agents.vision: send image attachments as OpenRouter multimodal content

A frozen RED contract fails: `tests/integration/test_agents_openrouter_llm.py::test_llm_attaches_images_as_openrouter_multimodal_content`. In `agents.llm`, the real (non-dry-run) path raises `NotImplementedError` when `attach` is provided. Implement it: build OpenRouter (OpenAI-compatible) multimodal message content — a text part plus one `image_url` data-URI part per attached image.

## The fix — `sdk/sfvf/agents.py`

1. Add `import base64` (next to `import json`, keeping import order/grouping so ruff is happy).

2. Add a module-level constant (near the other module constants):
   ```python
   _IMAGE_MIME = {
       ".png": "image/png",
       ".jpg": "image/jpeg",
       ".jpeg": "image/jpeg",
       ".webp": "image/webp",
       ".gif": "image/gif",
   }
   ```

3. In `llm`, REPLACE the block
   ```python
       if attach:
           raise NotImplementedError(
               "agents.llm vision attachments are not yet supported by the OpenRouter adapter"
           )
       body: dict[str, Any] = {
           "model": model,
           "messages": [{"role": "user", "content": prompt}],
       }
   ```
   with:
   ```python
       if attach:
           parts: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
           for path in attach:
               mime = _IMAGE_MIME.get(path.suffix.lower(), "image/png")
               encoded = base64.b64encode(path.read_bytes()).decode()
               parts.append(
                   {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{encoded}"}}
               )
           messages: list[dict[str, Any]] = [{"role": "user", "content": parts}]
       else:
           messages = [{"role": "user", "content": prompt}]
       body: dict[str, Any] = {"model": model, "messages": messages}
   ```

The dry-run branch (which accepts and ignores `attach`) is unchanged. The `response_format`/schema handling, `_post_chat_completion`, cost, and return-parsing that follow are unchanged.

## Scope (ONLY this file)
- `sdk/sfvf/agents.py`
Do NOT touch any test, other file, docs/, handoff/, requirements, or CI.

## Constraints
- No new dependency (`base64` is stdlib). Minimal change.
- `ruff check`, `ruff format --check`, and `mypy` clean on the file.

## Acceptance criteria
1. `python -m pytest tests/integration/test_agents_openrouter_llm.py` — all pass (the new multimodal test plus the existing dry-run/real/context tests).
2. `python -m pytest tests/integration/test_agents_openrouter_research.py tests/integration/test_agents_instructions.py` — still pass (no regression to the other agents paths).
3. `ruff check` + `ruff format --check` + `mypy` clean on `sdk/sfvf/agents.py`.
4. git diff shows exactly that one file changed.
