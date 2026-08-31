from pathlib import Path

from app.registry.problems import ProblemCode
from app.registry.validate import validate
from tests.registry.fixtures import minimal_toml, problem_codes, write_plugin
from tests.registry.test_schema import SDK_EXAMPLE


def test_validate_never_raises_on_missing_folder(tmp_path: Path) -> None:
    entry = validate(tmp_path / "does-not-exist")
    assert ProblemCode.MANIFEST_UNREADABLE.value in problem_codes(entry)
    assert entry.manifest is None


def test_invalid_toml_is_manifest_unreadable(tmp_path: Path) -> None:
    folder = write_plugin(tmp_path, "news-explainer", "[[[not toml")
    entry = validate(folder)
    assert entry.manifest is None
    assert problem_codes(entry) == {ProblemCode.MANIFEST_UNREADABLE.value}


def test_pydantic_failure_is_single_schema_invalid_naming_the_field(tmp_path: Path) -> None:
    toml = minimal_toml() + '\n[output]\naspect = "4:3"\n'
    folder = write_plugin(tmp_path, "news-explainer", toml)
    entry = validate(folder)
    assert entry.manifest is None
    assert problem_codes(entry) == {ProblemCode.SCHEMA_INVALID.value}
    assert len(entry.problems) == 1
    assert "aspect" in entry.problems[0].message


def test_sdk_example_validates_clean_in_matching_folder(tmp_path: Path) -> None:
    folder = write_plugin(
        tmp_path,
        "news-explainer",
        SDK_EXAMPLE,
        extra_files={"thumbnail.png": "png"},
    )
    entry = validate(folder)
    assert entry.manifest is not None
    assert entry.problems == ()
    assert entry.folder_name == "news-explainer"


def test_id_must_equal_folder_name(tmp_path: Path) -> None:
    folder = write_plugin(tmp_path, "other-id", minimal_toml("news-explainer"))
    entry = validate(folder)
    assert ProblemCode.ID_FOLDER_MISMATCH.value in problem_codes(entry)


def test_entrypoint_file_missing(tmp_path: Path) -> None:
    folder = write_plugin(tmp_path, "news-explainer", minimal_toml(), main_py=False)
    entry = validate(folder)
    assert ProblemCode.ENTRYPOINT_MISSING_FILE.value in problem_codes(entry)


def test_entrypoint_bad_format(tmp_path: Path) -> None:
    toml = minimal_toml().replace('entrypoint = "main:run"', 'entrypoint = "main"')
    folder = write_plugin(tmp_path, "news-explainer", toml)
    entry = validate(folder)
    assert ProblemCode.ENTRYPOINT_BAD_FORMAT.value in problem_codes(entry)


def test_prepare_file_missing_when_declared(tmp_path: Path) -> None:
    toml = minimal_toml(extra='prepare = "prep:go"')
    folder = write_plugin(tmp_path, "news-explainer", toml)
    entry = validate(folder)
    assert ProblemCode.PREPARE_MISSING_FILE.value in problem_codes(entry)


def test_requirements_txt_missing(tmp_path: Path) -> None:
    folder = write_plugin(tmp_path, "news-explainer", minimal_toml(), requirements=False)
    entry = validate(folder)
    assert ProblemCode.REQUIREMENTS_MISSING.value in problem_codes(entry)


def test_reserved_param_key(tmp_path: Path) -> None:
    toml = (
        minimal_toml()
        + """
[[params]]
key = "dry_run"
type = "bool"
label = "Dry run"
"""
    )
    folder = write_plugin(tmp_path, "news-explainer", toml)
    entry = validate(folder)
    assert ProblemCode.PARAM_RESERVED_KEY.value in problem_codes(entry)


def test_affects_cost_on_text_param(tmp_path: Path) -> None:
    toml = (
        minimal_toml()
        + """
[[params]]
key = "topic"
type = "text"
label = "Topic"
affects_cost = true
"""
    )
    folder = write_plugin(tmp_path, "news-explainer", toml)
    entry = validate(folder)
    assert ProblemCode.PARAM_AFFECTS_COST_ON_TEXT.value in problem_codes(entry)


def test_select_with_both_options_and_options_from(tmp_path: Path) -> None:
    toml = (
        minimal_toml()
        + """
[[params]]
key = "voice"
type = "select"
label = "Voice"
options = ["a"]
options_from = "elevenlabs.voices"
"""
    )
    folder = write_plugin(tmp_path, "news-explainer", toml)
    entry = validate(folder)
    assert ProblemCode.PARAM_OPTIONS_CONFLICT.value in problem_codes(entry)


def test_sdk_major_mismatch_is_a_warning_not_an_error(tmp_path: Path) -> None:
    toml = minimal_toml().replace('sdk = "1"', 'sdk = "2"')
    folder = write_plugin(tmp_path, "news-explainer", toml)
    entry = validate(folder)
    mismatch = [p for p in entry.problems if p.code == ProblemCode.SDK_VERSION_MISMATCH]
    assert len(mismatch) == 1
    assert mismatch[0].severity == "warning"
    assert entry.manifest is not None
    assert not any(p.severity == "error" for p in entry.problems)


def test_unknown_capability_name(tmp_path: Path) -> None:
    toml = minimal_toml(extra='requires_capabilities = ["telepathy"]')
    folder = write_plugin(tmp_path, "news-explainer", toml)
    entry = validate(folder)
    assert ProblemCode.CAPABILITY_UNKNOWN.value in problem_codes(entry)


def test_closed_facet_list_empty_is_invalid(tmp_path: Path) -> None:
    toml = (
        minimal_toml()
        + """
[[library.facets]]
key = "view"
values = []
"""
    )
    folder = write_plugin(tmp_path, "news-explainer", toml)
    entry = validate(folder)
    assert ProblemCode.FACET_INVALID.value in problem_codes(entry)


def test_unknown_recovery_action_is_not_a_validate_problem(tmp_path: Path) -> None:
    toml = (
        minimal_toml()
        + """
[[recovery]]
step = "generate-shot"
label = "Skip this family"
action = "skip_family"
"""
    )
    folder = write_plugin(tmp_path, "news-explainer", toml)
    entry = validate(folder)
    assert entry.manifest is not None
    assert ProblemCode.RECOVERY_INVALID.value not in problem_codes(entry)
    assert entry.problems == ()


def test_fps_zero_is_output_invalid(tmp_path: Path) -> None:
    toml = minimal_toml() + "\n[output]\nfps = 0\n"
    folder = write_plugin(tmp_path, "news-explainer", toml)
    entry = validate(folder)
    assert ProblemCode.OUTPUT_INVALID.value in problem_codes(entry)


def test_limit_seconds_zero_is_limit_invalid(tmp_path: Path) -> None:
    toml = (
        minimal_toml()
        + """
[[limits]]
step = "generate-shot"
seconds = 0
"""
    )
    folder = write_plugin(tmp_path, "news-explainer", toml)
    entry = validate(folder)
    assert ProblemCode.LIMIT_INVALID.value in problem_codes(entry)


def test_max_videos_zero_is_rejected(tmp_path: Path) -> None:
    toml = minimal_toml(extra="max_videos = 0")
    folder = write_plugin(tmp_path, "news-explainer", toml)
    entry = validate(folder)
    assert ProblemCode.VIDEO_SEMANTICS_INVALID.value in problem_codes(entry)


def test_duplicate_param_keys(tmp_path: Path) -> None:
    toml = (
        minimal_toml()
        + """
[[params]]
key = "topic"
type = "text"
label = "Topic"

[[params]]
key = "topic"
type = "text"
label = "Topic again"
"""
    )
    folder = write_plugin(tmp_path, "news-explainer", toml)
    entry = validate(folder)
    assert ProblemCode.PARAM_DUPLICATE_KEY.value in problem_codes(entry)


def test_declared_thumbnail_missing(tmp_path: Path) -> None:
    toml = minimal_toml(extra='thumbnail = "thumbnail.png"')
    folder = write_plugin(tmp_path, "news-explainer", toml)
    entry = validate(folder)
    assert ProblemCode.THUMBNAIL_MISSING.value in problem_codes(entry)


def test_duplicate_quality_factor_keys(tmp_path: Path) -> None:
    toml = (
        minimal_toml()
        + """
[[quality_factors]]
key = "hook"
question = "Did it hook?"

[[quality_factors]]
key = "hook"
question = "Did it hook, really?"
"""
    )
    folder = write_plugin(tmp_path, "news-explainer", toml)
    entry = validate(folder)
    assert ProblemCode.QUALITY_FACTOR_INVALID.value in problem_codes(entry)


def test_empty_requires_key_name(tmp_path: Path) -> None:
    toml = (
        minimal_toml()
        + """
[[requires_keys]]
name = ""
label = "OpenRouter"
"""
    )
    folder = write_plugin(tmp_path, "news-explainer", toml)
    entry = validate(folder)
    assert ProblemCode.REQUIRES_INVALID.value in problem_codes(entry)


def test_python_patch_version_is_schema_invalid(tmp_path: Path) -> None:
    toml = minimal_toml(extra='python = "3.12.4"')
    folder = write_plugin(tmp_path, "news-explainer", toml)
    entry = validate(folder)
    assert entry.manifest is None
    assert problem_codes(entry) == {ProblemCode.SCHEMA_INVALID.value}
    assert len(entry.problems) == 1
    assert "python" in entry.problems[0].message


def test_python_toml_float_is_schema_invalid(tmp_path: Path) -> None:
    toml = minimal_toml(extra="python = 3.10")
    folder = write_plugin(tmp_path, "news-explainer", toml)
    entry = validate(folder)
    assert entry.manifest is None
    assert problem_codes(entry) == {ProblemCode.SCHEMA_INVALID.value}
    assert len(entry.problems) == 1
    assert "python" in entry.problems[0].message


def test_python_major_and_major_minor_validate_clean(tmp_path: Path) -> None:
    for name, extra in (("major", 'python = "3"'), ("minor", 'python = "3.12"')):
        folder = write_plugin(tmp_path / name, "news-explainer", minimal_toml(extra=extra))
        entry = validate(folder)
        assert entry.manifest is not None
        assert entry.problems == ()
        assert entry.manifest.workflow.python in {"3", "3.12"}
