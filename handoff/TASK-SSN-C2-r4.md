# TASK-SSN-C2-r4 — Close the remaining allowlist path bypass (;params + backslash)

The cross-family reviewer found the path filter is still bypassable, in one function only.

## The bug

`_url_on_allowlist` (workflows/sensational-science-news/main.py) uses `urlparse`, which strips a
`;params` tail off the LAST path segment into `.params`. So for
`https://www.bbc.com/news/science_and_environment/s;%2e%2e%2f%2e%2e%2f%2e%2e%2f%2e%2e%2fentertainment`,
`urlparse(url).path` is only `/news/science_and_environment/s` (KEPT), but the ORIGIN receives the
whole path (`;...` is part of the request path over HTTP) and it resolves to `/entertainment` — outside
the science-section prefix. Same shape escapes reuters `/science`, npr `/sections/science`, cbc
`/news/science`, bloomberg `/ai`. Additionally, an encoded backslash `%5c` can act as a path separator
on some origins and is currently not treated as one.

## Scope — edit ONLY this file, ONLY `_url_on_allowlist`

- `workflows/sensational-science-news/main.py`

## The fix

1. Use `urlsplit` instead of `urlparse` so the `;params` tail stays in the path (urlsplit does not
   split params). Update the import: change `from urllib.parse import unquote, urlparse` to
   `from urllib.parse import unquote, urlsplit` (urlparse is only used here). In `_url_on_allowlist`,
   `parsed = urlsplit(url)`. `urlsplit(...).hostname` works the same as before.
2. Normalize backslashes as separators before dot-segment removal, so an encoded (or literal)
   backslash cannot hide a traversal. Change the path decode line to:
   ```python
   raw_path = unquote(parsed.path or "").replace("\\", "/")
   ```
   Keep everything else the same: `path = posixpath.normpath(raw_path or "/")`, the `"." -> "/"`
   guard, and the boundary check `path == path_prefix or path.startswith(path_prefix + "/")`.

Do NOT change any other function, any test, the SDK, or dependencies.

## Done when (run from Workspace/ with the repo venv)

- `./.venv/Scripts/python.exe -m pytest tests/integration/test_ssn_prepare.py -q` — all pass,
  including `test_allowlist_filter_rejects_params_and_backslash_traversal` (the `;params` and `%5c`
  traversals are DROPPED, while a legitimate `;jsessionid` param URL is KEPT) and the existing
  `test_allowlist_filter_rejects_percent_encoded_traversal`.
- `./.venv/Scripts/python.exe -m ruff check workflows/sensational-science-news` and
  `./.venv/Scripts/python.exe -m ruff format --check .` — clean.
- `./.venv/Scripts/python.exe -m mypy` — no new errors from `main.py`.

Print the final `_url_on_allowlist` and one line on why `;params` and `%5c` can no longer escape the
prefix.
