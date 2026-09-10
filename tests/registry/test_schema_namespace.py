"""D-3c: the library namespace is validated as a safe path segment (it becomes library/<namespace>).

An unsafe namespace could redirect chassis writes outside the library (traversal), so the manifest
is rejected at parse. A safe namespace, and the default-to-workflow-id, are accepted.
"""

from __future__ import annotations

import pytest

from app.registry.schema import parse_manifest_toml

_BASE = """
[workflow]
id = "wf"
name = "WF"
version = "1.0.0"
entrypoint = "main:run"
sdk = "1"
"""


def _with_namespace(namespace: str) -> str:
    return _BASE + f'\n[library]\nnamespace = "{namespace}"\n'


@pytest.mark.parametrize("bad", ["../escape", "a/b", "..", "/abs", "."])
def test_unsafe_namespace_is_rejected(bad: str) -> None:
    with pytest.raises(ValueError):
        parse_manifest_toml(_with_namespace(bad))


def test_safe_namespace_is_accepted() -> None:
    manifest = parse_manifest_toml(_with_namespace("cast"))
    assert manifest.library.namespace == "cast"


def test_namespace_defaults_to_workflow_id_and_is_valid() -> None:
    manifest = parse_manifest_toml(_BASE)  # no [library] section
    assert manifest.library.namespace == "wf"
