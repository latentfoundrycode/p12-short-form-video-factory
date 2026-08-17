from dataclasses import dataclass
from pathlib import Path

from pydantic import ValidationError

from app.paths import safe_join
from app.registry.problems import Problem, ProblemCode
from app.registry.schema import (
    LibraryFacet,
    Manifest,
    Param,
    QualityFactor,
    parse_manifest_toml,
)

CHASSIS_SDK_MAJOR = "1"

KNOWN_CAPABILITIES = frozenset(
    {
        "image.generate",
        "image.edit",
        "video.generate",
        "video.refs",
        "video.first_frame",
        "agents.vision",
        "agents.structured",
    }
)

RESERVED_PARAM_KEYS = frozenset(
    {
        "videos",
        "n_videos",
        "video_count",
        "budget",
        "max_retries",
        "retries",
        "concurrency",
        "video_concurrency",
        "step_concurrency",
        "dry_run",
    }
)


@dataclass(frozen=True)
class WorkflowEntry:
    folder_name: str
    path: Path
    manifest: Manifest | None
    problems: tuple[Problem, ...]


def validate(folder: Path) -> WorkflowEntry:
    try:
        return _validate(folder)
    except Exception as exc:
        return _entry(
            folder,
            None,
            (_problem(ProblemCode.MANIFEST_UNREADABLE, f"{type(exc).__name__}: {exc}"),),
        )


def _validate(folder: Path) -> WorkflowEntry:
    toml_path = folder / "workflow.toml"
    try:
        text = toml_path.read_text(encoding="utf-8-sig")
    except OSError as exc:
        return _entry(folder, None, (_problem(ProblemCode.MANIFEST_UNREADABLE, str(exc)),))

    try:
        manifest = parse_manifest_toml(text)
    except ValidationError as exc:
        return _entry(folder, None, (_schema_problem(exc),))
    except Exception as exc:
        return _entry(
            folder,
            None,
            (_problem(ProblemCode.MANIFEST_UNREADABLE, f"{type(exc).__name__}: {exc}"),),
        )

    return _entry(folder, manifest, tuple(_semantic_problems(folder, manifest)))


def _semantic_problems(folder: Path, manifest: Manifest) -> list[Problem]:
    problems: list[Problem] = []
    workflow = manifest.workflow

    if workflow.id != folder.name:
        problems.append(
            _problem(
                ProblemCode.ID_FOLDER_MISMATCH,
                f"workflow.id {workflow.id!r} does not match folder name {folder.name!r}",
            )
        )

    problems.extend(_entrypoint_problems(folder, workflow.entrypoint, kind="entrypoint"))
    if workflow.prepare is not None:
        problems.extend(_entrypoint_problems(folder, workflow.prepare, kind="prepare"))

    if not (folder / "requirements.txt").is_file():
        problems.append(
            _problem(
                ProblemCode.REQUIREMENTS_MISSING, "requirements.txt is required and was not found"
            )
        )

    if manifest.output.fps <= 0:
        problems.append(_problem(ProblemCode.OUTPUT_INVALID, "output.fps must be greater than 0"))

    if workflow.max_videos is not None and workflow.max_videos <= 0:
        problems.append(
            _problem(
                ProblemCode.VIDEO_SEMANTICS_INVALID, "max_videos must be greater than 0 when set"
            )
        )

    for limit in manifest.limits:
        if not limit.step or limit.seconds <= 0:
            problems.append(
                _problem(
                    ProblemCode.LIMIT_INVALID,
                    f"limit for {limit.step!r} must have a non-empty step and seconds > 0",
                )
            )

    problems.extend(_param_problems(manifest.params))
    problems.extend(_capability_problems(workflow.requires_capabilities))
    problems.extend(_facet_problems(manifest.library.facets))
    problems.extend(_quality_factor_problems(manifest.quality_factors))
    problems.extend(_requires_problems(manifest))

    if workflow.thumbnail:
        thumb = safe_join(folder, workflow.thumbnail)
        if thumb is None or not thumb.is_file():
            problems.append(
                _problem(
                    ProblemCode.THUMBNAIL_MISSING,
                    f"declared thumbnail {workflow.thumbnail!r} was not found",
                )
            )

    if _major(workflow.sdk) != CHASSIS_SDK_MAJOR:
        problems.append(
            Problem(
                code=ProblemCode.SDK_VERSION_MISMATCH,
                message=(
                    f"workflow sdk major {_major(workflow.sdk)!r} does not match "
                    f"chassis major {CHASSIS_SDK_MAJOR!r}"
                ),
                severity="warning",
            )
        )

    return problems


def _entrypoint_problems(folder: Path, spec: str, *, kind: str) -> list[Problem]:
    bad_format = (
        ProblemCode.ENTRYPOINT_BAD_FORMAT
        if kind == "entrypoint"
        else ProblemCode.PREPARE_BAD_FORMAT
    )
    missing_file = (
        ProblemCode.ENTRYPOINT_MISSING_FILE
        if kind == "entrypoint"
        else ProblemCode.PREPARE_MISSING_FILE
    )
    parsed = _parse_file_function(spec)
    if parsed is None:
        return [_problem(bad_format, f"{kind} must be file:function, got {spec!r}")]
    file_part, _function = parsed
    path = safe_join(folder, file_part if file_part.endswith(".py") else f"{file_part}.py")
    if path is None or not path.is_file():
        return [_problem(missing_file, f"{kind} file {file_part!r} was not found")]
    return []


def _parse_file_function(spec: str) -> tuple[str, str] | None:
    if spec.count(":") != 1:
        return None
    file_part, function = spec.split(":")
    if not file_part or not function:
        return None
    rel = Path(file_part)
    if rel.is_absolute() or ".." in rel.parts:
        return None
    return file_part, function


def _param_problems(params: list[Param]) -> list[Problem]:
    problems: list[Problem] = []
    seen: set[str] = set()
    for param in params:
        if not param.key.strip() or not param.label.strip():
            problems.append(
                _problem(
                    ProblemCode.PARAM_INVALID,
                    f"param {param.key!r} needs a non-empty key and label",
                )
            )
        if param.key in seen:
            problems.append(
                _problem(ProblemCode.PARAM_DUPLICATE_KEY, f"duplicate param key {param.key!r}")
            )
        seen.add(param.key)
        if param.key in RESERVED_PARAM_KEYS:
            problems.append(
                _problem(
                    ProblemCode.PARAM_RESERVED_KEY,
                    f"param key {param.key!r} is reserved by the chassis",
                )
            )
        if param.affects_cost and param.type in {"text", "textarea"}:
            problems.append(
                _problem(
                    ProblemCode.PARAM_AFFECTS_COST_ON_TEXT,
                    f"param {param.key!r} is free text and must not set affects_cost",
                )
            )
        if param.type in {"select", "multiselect"}:
            has_options = param.options is not None
            has_from = param.options_from is not None
            if has_options == has_from:
                problems.append(
                    _problem(
                        ProblemCode.PARAM_OPTIONS_CONFLICT,
                        f"param {param.key!r} must declare exactly one of options or options_from",
                    )
                )
        if (
            param.type == "number"
            and param.min is not None
            and param.max is not None
            and param.min > param.max
        ):
            problems.append(
                _problem(ProblemCode.PARAM_INVALID, f"param {param.key!r} has min greater than max")
            )
    return problems


def _capability_problems(names: list[str]) -> list[Problem]:
    problems: list[Problem] = []
    for name in names:
        if name not in KNOWN_CAPABILITIES:
            problems.append(
                _problem(
                    ProblemCode.CAPABILITY_UNKNOWN,
                    f"requires_capabilities entry {name!r} is not in the chassis vocabulary",
                )
            )
    return problems


def _facet_problems(facets: list[LibraryFacet]) -> list[Problem]:
    problems: list[Problem] = []
    seen: set[str] = set()
    for facet in facets:
        if not facet.key.strip() or facet.key in seen:
            problems.append(
                _problem(
                    ProblemCode.FACET_INVALID,
                    f"library facet key {facet.key!r} must be unique and non-empty",
                )
            )
        seen.add(facet.key)
        if facet.values != "open" and (
            not facet.values or len(facet.values) != len(set(facet.values))
        ):
            problems.append(
                _problem(
                    ProblemCode.FACET_INVALID,
                    f"library facet {facet.key!r} needs unique non-empty values",
                )
            )
    return problems


def _quality_factor_problems(factors: list[QualityFactor]) -> list[Problem]:
    problems: list[Problem] = []
    seen: set[str] = set()
    for factor in factors:
        if not factor.key.strip() or not factor.question.strip() or factor.key in seen:
            problems.append(
                _problem(
                    ProblemCode.QUALITY_FACTOR_INVALID,
                    f"quality factor {factor.key!r} needs a unique key and a question",
                )
            )
        seen.add(factor.key)
    return problems


def _requires_problems(manifest: Manifest) -> list[Problem]:
    problems: list[Problem] = []
    for key in manifest.requires_keys:
        if not key.name.strip() or not key.label.strip():
            problems.append(
                _problem(
                    ProblemCode.REQUIRES_INVALID,
                    "requires_keys entries need a non-empty name and label",
                )
            )
    for connection in manifest.requires_connections:
        if (
            not connection.name.strip()
            or not connection.label.strip()
            or not connection.kind.strip()
        ):
            problems.append(
                _problem(
                    ProblemCode.REQUIRES_INVALID,
                    "requires_connections entries need a non-empty name, label, and kind",
                )
            )
    return problems


def _major(sdk: str) -> str:
    return sdk.split(".", maxsplit=1)[0]


def _schema_problem(exc: ValidationError) -> Problem:
    parts: list[str] = []
    for error in exc.errors():
        loc = ".".join(str(part) for part in error["loc"])
        parts.append(f"{loc}: {error['msg']}" if loc else error["msg"])
    message = parts[0] if len(parts) == 1 else "; ".join(parts)
    if not message:
        message = "manifest does not match the schema"
    return _problem(ProblemCode.SCHEMA_INVALID, message)


def _problem(code: ProblemCode, message: str) -> Problem:
    return Problem(code=code, message=message, severity="error")


def _entry(folder: Path, manifest: Manifest | None, problems: tuple[Problem, ...]) -> WorkflowEntry:
    return WorkflowEntry(folder_name=folder.name, path=folder, manifest=manifest, problems=problems)
