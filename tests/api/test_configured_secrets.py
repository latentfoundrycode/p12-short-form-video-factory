"""Frozen contract — web-image-sourcing increment 6: a BLANK stored secret is not "configured".

`provider_configured`/`capabilities_offered` gate on secret-NAME presence, so a stored secret whose
VALUE is empty/whitespace would offer its capability (e.g. `web.images.web`) at scan time, then fail
at runtime where the adapter refuses an empty key (`if not key: raise`). The app must therefore
treat only secrets with a non-blank value as configured when it computes offered capabilities.
"""

from __future__ import annotations

from app.api.workflows import configured_secret_names


def test_a_nonblank_secret_is_configured() -> None:
    assert configured_secret_names({"SERPAPI_API_KEY": "sk-real-value"}) == {"SERPAPI_API_KEY"}


def test_a_blank_or_whitespace_secret_is_not_configured() -> None:
    assert configured_secret_names({"SERPAPI_API_KEY": ""}) == set()
    assert configured_secret_names({"SERPAPI_API_KEY": "   "}) == set()


def test_only_nonblank_secrets_survive() -> None:
    assert configured_secret_names({"A": "x", "B": "", "C": "  ", "D": "y"}) == {"A", "D"}


def test_empty_mapping() -> None:
    assert configured_secret_names({}) == set()
