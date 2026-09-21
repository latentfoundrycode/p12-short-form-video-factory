# TASK — web-sourcing inc3a-r3: no HTTP decompression bomb before the byte cap

## Context
`sdk/sfvf/media/web.py::_download_guarded` streams an untrusted HTTPS response and enforces a
25 MiB byte cap. But the cap runs over `resp.iter_bytes(...)`, and `httpx2.iter_bytes()` applies
`Content-Encoding` decoders **before** yielding — so a malicious origin returning
`Content-Encoding: gzip, gzip` (a ~272-byte wire body decoding to 64 MiB) expands in memory
before the cap check. The byte cap is a real deliverable, so this must be fixed. A frozen RED
contract is already committed in `tests/integration/test_media_web_fetch.py` (do not edit it).

## Scope
- **Edit ONLY** `sdk/sfvf/media/web.py` (`_download_guarded`).
- Do NOT edit any test file. Do NOT create any notes/markdown files.
- No new dependencies.

## Required behaviour (make the frozen contract pass)
In `_download_guarded`:
1. **Request identity encoding** — add `"Accept-Encoding": "identity"` to the request headers
   passed to `client.stream("GET", pinned, headers={...}, ...)` (alongside the existing `Host`
   header). This stops httpx2 from negotiating gzip/deflate, so no decoder runs.
   Contract: the recorded request's `accept-encoding` header must equal `"identity"`.
2. **Reject a non-identity response encoding** — after confirming `status_code == 200` and
   before reading the body, inspect `resp.headers.get("content-encoding")`. If it is present and
   is anything other than `identity` (compare case-insensitively and stripped; treat a comma list
   such as `"gzip, gzip"` as non-identity — reject unless every token is `identity`), raise
   `ValueError` (e.g. `"fetch: unexpected content-encoding <value>"`). This runs before the body
   is read, so the bomb never decodes.
   Contract: a `200` response carrying `Content-Encoding: gzip` raises `ValueError` and writes no
   file (the request is still sent — the reject is on the response).
3. **Cap over raw wire bytes** — change the download loop from `resp.iter_bytes(_DL_CHUNK)` to
   `resp.iter_raw(_DL_CHUNK)` so the 25 MiB cap bounds wire bytes (with identity requested and
   non-identity rejected, wire bytes == the image bytes). Keep the `_MAX_DOWNLOAD_BYTES` check and
   the `bytes(buf)` return unchanged otherwise.

Do not change any other guarantee: https-only, `_validated_pin_ip` + IP-pin + `Host`/`sni_hostname`,
redirect re-validation loop bounded by `_MAX_REDIRECTS`, the non-200 raise, the byte-cap value.

## Acceptance
- `PYTHONPATH=sdk python -m pytest tests/integration/test_media_web_fetch.py -q` → **all pass**
  (the 2 currently-RED content-encoding cases plus the existing 31 stay green).
- `python -m ruff format --check sdk/sfvf/media/web.py` and `python -m ruff check sdk/sfvf/media/web.py` → clean.
- `git diff --name-only` shows **only** `sdk/sfvf/media/web.py`.
