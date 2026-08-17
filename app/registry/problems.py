from dataclasses import dataclass
from enum import StrEnum
from typing import Literal


class ProblemCode(StrEnum):
    MANIFEST_UNREADABLE = "manifest_unreadable"
    SCHEMA_INVALID = "schema_invalid"
    ID_FOLDER_MISMATCH = "id_folder_mismatch"
    ENTRYPOINT_BAD_FORMAT = "entrypoint_bad_format"
    ENTRYPOINT_MISSING_FILE = "entrypoint_missing_file"
    PREPARE_BAD_FORMAT = "prepare_bad_format"
    PREPARE_MISSING_FILE = "prepare_missing_file"
    REQUIREMENTS_MISSING = "requirements_missing"
    PARAM_INVALID = "param_invalid"
    PARAM_DUPLICATE_KEY = "param_duplicate_key"
    PARAM_OPTIONS_CONFLICT = "param_options_conflict"
    PARAM_RESERVED_KEY = "param_reserved_key"
    PARAM_AFFECTS_COST_ON_TEXT = "param_affects_cost_on_text"
    SDK_VERSION_MISMATCH = "sdk_version_mismatch"
    OUTPUT_INVALID = "output_invalid"
    VIDEO_SEMANTICS_INVALID = "video_semantics_invalid"
    LIMIT_INVALID = "limit_invalid"
    RECOVERY_INVALID = "recovery_invalid"
    QUALITY_FACTOR_INVALID = "quality_factor_invalid"
    REQUIRES_INVALID = "requires_invalid"
    CAPABILITY_UNKNOWN = "capability_unknown"
    FACET_INVALID = "facet_invalid"
    THUMBNAIL_MISSING = "thumbnail_missing"


type ProblemSeverity = Literal["error", "warning"]


@dataclass(frozen=True)
class Problem:
    code: ProblemCode
    message: str
    severity: ProblemSeverity
