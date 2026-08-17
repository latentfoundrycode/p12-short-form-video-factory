import pytest
from pydantic import ValidationError

from app.registry.schema import parse_manifest_toml

SDK_EXAMPLE = """
[workflow]
id          = "news-explainer"
name        = "News Explainer"
version     = "1.3.0"
description = "Researches a topic and produces a 45-second explainer."
thumbnail   = "thumbnail.png"
entrypoint  = "main:run"
prepare     = "main:prepare"
python      = "3.12"
sdk         = "1"

video_semantics = "variants"
max_videos      = 10
atomic          = false
safety_factor   = 1.25

requires_binaries = ["ffmpeg", "ffprobe"]
requires_capabilities = ["agents.vision"]

[[requires_keys]]
name  = "OPENROUTER_API_KEY"
label = "OpenRouter"

[[requires_connections]]
name  = "higgsfield"
label = "Higgsfield"
kind  = "mcp_oauth"

[output]
aspect    = "9:16"
fps       = 30
safe_zone = "tiktok"

[library]
namespace = "news-explainer"

[[library.facets]]
key    = "subject"
values = "open"

[[library.facets]]
key    = "view"
values = ["turnaround-8pt", "expression-sheet", "closeup", "prop-only"]

[[limits]]
step    = "generate-shot"
seconds = 900

[[params]]
key      = "topic"
type     = "text"
label    = "Topic"
required = false
help     = "Leave empty to let the research agent choose one."

[[params]]
key          = "video_model"
type         = "select"
label        = "Video model"
affects_cost = true
options_from = "higgsfield.video_models"

[[params]]
key          = "voice"
type         = "select"
label        = "Narrator voice"
options_from = "elevenlabs.voices"

[[params]]
key          = "duration_s"
type         = "number"
label        = "Target duration (seconds)"
default      = 45
min          = 20
max          = 90
affects_cost = true

[[recovery]]
step   = "generate-shot"
label  = "Switch to the standard video model and retry"
action = "set_param"
param  = "video_model"
value  = "standard"

[[quality_factors]]
key      = "hook"
question = "Did the first two seconds make you want to keep watching? Why?"

[[quality_factors]]
key      = "coherence"
question = "Did the visuals stay consistent across shots? Where did they drift?"
"""

MINIMAL = """
[workflow]
id = "news-explainer"
name = "News Explainer"
version = "1.0.0"
entrypoint = "main:run"
sdk = "1"
"""


def test_sdk_section_2_example_parses_clean() -> None:
    manifest = parse_manifest_toml(SDK_EXAMPLE)
    assert manifest.workflow.id == "news-explainer"
    assert manifest.workflow.name == "News Explainer"
    assert manifest.workflow.version == "1.3.0"
    assert manifest.workflow.entrypoint == "main:run"
    assert manifest.workflow.prepare == "main:prepare"
    assert manifest.workflow.sdk == "1"
    assert manifest.workflow.video_semantics == "variants"
    assert manifest.workflow.max_videos == 10
    assert manifest.output.aspect == "9:16"
    assert manifest.library.namespace == "news-explainer"
    assert manifest.library.facets[0].values == "open"
    assert manifest.library.facets[1].values == [
        "turnaround-8pt",
        "expression-sheet",
        "closeup",
        "prop-only",
    ]
    assert len(manifest.params) == 4
    assert manifest.params[0].type == "text"
    assert manifest.recovery[0].action == "set_param"
    assert manifest.recovery[0].param == "video_model"
    assert manifest.recovery[0].value == "standard"
    assert len(manifest.quality_factors) == 2


def test_invalid_output_aspect_is_rejected() -> None:
    toml = MINIMAL + '\n[output]\naspect = "4:3"\n'
    with pytest.raises(ValidationError):
        parse_manifest_toml(toml)


def test_invalid_param_type_is_rejected() -> None:
    toml = (
        MINIMAL
        + """
[[params]]
key = "topic"
type = "dropdown"
label = "Topic"
"""
    )
    with pytest.raises(ValidationError):
        parse_manifest_toml(toml)


def test_omitted_sections_receive_spec_defaults() -> None:
    manifest = parse_manifest_toml(MINIMAL)
    assert manifest.output.aspect == "9:16"
    assert manifest.output.fps == 30
    assert manifest.output.safe_zone == "tiktok"
    assert manifest.workflow.video_semantics == "variants"
    assert manifest.workflow.python == "3.12"
    assert manifest.library.namespace == "news-explainer"


def test_sdk_integer_normalises_to_major_version_string() -> None:
    toml = """
[workflow]
id = "news-explainer"
name = "News Explainer"
version = "1.0.0"
entrypoint = "main:run"
sdk = 1
"""
    manifest = parse_manifest_toml(toml)
    assert manifest.workflow.sdk == "1"


def test_set_param_recovery_requires_param_and_value() -> None:
    toml = (
        MINIMAL
        + """
[[recovery]]
step = "generate-shot"
label = "Retry"
action = "set_param"
"""
    )
    with pytest.raises(ValidationError):
        parse_manifest_toml(toml)


def test_unknown_recovery_action_is_accepted() -> None:
    toml = (
        MINIMAL
        + """
[[recovery]]
step = "generate-shot"
label = "Skip this family"
action = "skip_family"
"""
    )
    manifest = parse_manifest_toml(toml)
    assert manifest.recovery[0].action == "skip_family"
    assert manifest.recovery[0].param is None
    assert manifest.recovery[0].value is None
