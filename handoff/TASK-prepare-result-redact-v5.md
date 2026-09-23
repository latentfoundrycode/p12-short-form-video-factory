# TASK — block result.json download/listing (H18 exfil vector) — COMPLETION

## Why (round 5)
Cross-family review showed the byte-level value redaction cannot cover every encoding: a failing
`prepare()` can write `shared/result.json` in UTF-16 (or any encoding) carrying its injected secret;
the UTF-8/escaped-UTF-8 byte targets miss it, and the served file decodes back to the original
secret. Byte-substring redaction is fundamentally incomplete against a workflow that controls the
file's bytes AND encoding.

Complete fix (as the original H18 note offered): mirror `context.json` — do not serve `result.json`
at all and exclude it from the file listing. This closes the download exfil vector for EVERY encoding
and structure. The engine reads `result.json` from disk directly (`_run_prepare`), NOT via this
endpoint, so blocking the download does not affect it. The best-effort on-disk redaction added in the
prior commits stays as defence-in-depth for the on-disk copy.

Frozen RED tests (committed, do not modify):
- `tests/api/test_secret_exposure.py::test_result_json_is_not_downloadable` (GET result.json → 404;
  result.json absent from the listing; note.txt still 200/listed).
- `tests/core/test_secret_redaction.py::test_failed_prepare_result_secret_is_redacted_on_disk_and_download`
  (updated: the result.json download now asserts 404).

## Changes — only `app/api/runs.py`, mirroring the existing `context.json` handling

### 1. `get_run_file` — block result.json (same as context.json)
Find the existing guard:
```python
    if resolved.name == "context.json":
        raise HTTPException(status_code=404)
```
and extend it to both names:
```python
    if resolved.name in ("context.json", "result.json"):
        raise HTTPException(status_code=404)
```

### 2. `list_run_files` — exclude result.json from the listing (same as context.json)
Find the existing exclusion:
```python
        if (
            relative.name == "context.json"
            or resolved.name == "context.json"
            or any(part.startswith(".") for part in relative.parts)
        ):
            continue
```
and add result.json:
```python
        if (
            relative.name in ("context.json", "result.json")
            or resolved.name in ("context.json", "result.json")
            or any(part.startswith(".") for part in relative.parts)
        ):
            continue
```

## Scope / do NOT
- ONLY `app/api/runs.py` (the two spots above). Do NOT change `_scrub_result_secrets`, records.py,
  the finally call site, any other endpoint, any test, or any stub. No new dependencies.

## Acceptance
- `PYTHONPATH=sdk python -m pytest tests/api/test_secret_exposure.py tests/api/test_run_files.py -q`
  → all pass, including `test_result_json_is_not_downloadable` and the existing context.json/listing
  tests (find the run-files test module if the name differs; run the API run-files + secret-exposure
  suites). If unsure which file holds the run-files listing tests, also run:
  `PYTHONPATH=sdk python -m pytest tests/api -q -k "run_file or files or exposure or download"`.
- `ruff check app tests` and `ruff format --check app tests` clean; `.\.venv\Scripts\python.exe -m mypy` clean.
