"""TASK-SSN-C1 contract: the Sensational Science News workflow is a valid, discoverable plugin.

The scaffold (repurposed from `explainer`) must validate clean: 9:16 / 30 fps vertical output,
`video_semantics = "variants"` (a real enum value; inert -- distinctness comes from prepare per
rev-5), and it declares exactly the keys the workflow's providers need -- OPENROUTER_API_KEY (LLM:
research/script/subject-picker/image-relevance), GOOGLE_SA_JSON (Gemini AI stills), and
BYTEPLUS_ARK_API_KEY (Seedance clips). SerpApi paid web images are a deferred off-by-default
enhancement, so no SerpApi key is required. The run settings (approval mode / video count /
per-video budget / voice) are LAUNCH settings on the run, not workflow params, so are NOT declared.

Supervisor-authored frozen contract (RED-first); the builder creates the workflow folder.
"""

from __future__ import annotations

import importlib.util
import tomllib
from pathlib import Path

from app.registry.validate import validate

_WF = Path(__file__).resolve().parents[2] / "workflows" / "sensational-science-news"


def _load_main():
    spec = importlib.util.spec_from_file_location("ssn_main_undertest", _WF / "main.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_workflow_validates_clean() -> None:
    entry = validate(_WF)
    assert entry.manifest is not None, f"did not validate: {[p.message for p in entry.problems]}"
    errors = [p for p in entry.problems if getattr(p, "severity", "error") == "error"]
    assert errors == [], [p.message for p in errors]


def test_workflow_manifest_fields() -> None:
    data = tomllib.loads((_WF / "workflow.toml").read_text(encoding="utf-8"))
    assert data["workflow"]["id"] == "sensational-science-news"
    assert data["workflow"]["video_semantics"] == "variants"
    assert data["output"]["aspect"] == "9:16"
    assert int(data["output"]["fps"]) == 30
    keys = {k["name"] for k in data.get("requires_keys", [])}
    assert {"OPENROUTER_API_KEY", "GOOGLE_SA_JSON", "BYTEPLUS_ARK_API_KEY"} <= keys
    assert "SERPAPI_API_KEY" not in keys  # paid web deferred/off -> not a hard requirement


def test_workflow_has_its_own_requirements() -> None:
    # Issue 3: a workflow's venv is built from its own requirements.txt; it must exist and pin the
    # heavy provider stack the workflow imports (speech + openrouter, at least).
    reqs = (_WF / "requirements.txt").read_text(encoding="utf-8")
    assert "chatterbox" in reqs and "torch" in reqs


def test_narration_cleaning_strips_quotes_and_stage_directions() -> None:
    # The narration handed to media.speech must be spoken words only: straight AND curly quotes,
    # bracketed stage directions, markdown, and speaker labels all removed. (An ASCII-conversion of
    # the copied helper once broke curly-quote stripping; this pins it. Curly quotes are written as
    # \u escapes to keep the test source ASCII.)
    main = _load_main()
    raw = 'Narrator: "wow" and “amazing” [cut to lab] **bold** _em_'
    out = main._narration_text(raw)
    for ch in ('"', "“", "”", "[", "]", "*", "_"):
        assert ch not in out, f"{ch!r} leaked into narration: {out!r}"
    assert "wow" in out and "amazing" in out
    assert "Narrator" not in out
