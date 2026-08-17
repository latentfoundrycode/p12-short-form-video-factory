import tomllib
from typing import Annotated, Any, Literal, Self

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, model_validator

type VideoSemantics = Literal["variants", "sequence"]
type AspectRatio = Literal["9:16", "16:9", "1:1"]
type SafeZone = Literal["tiktok", "none"]
type ParamType = Literal["text", "textarea", "number", "bool", "select", "multiselect", "file"]
type FacetValues = Literal["open"] | list[str]


def _sdk_major(value: object) -> str:
    if isinstance(value, bool) or not isinstance(value, int | str):
        raise TypeError("sdk must be an integer or string")
    return str(value)


SdkMajor = Annotated[str, BeforeValidator(_sdk_major)]


class _ManifestModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RequiresKey(_ManifestModel):
    name: str
    label: str


class RequiresConnection(_ManifestModel):
    name: str
    label: str
    kind: str


class OutputSection(_ManifestModel):
    aspect: AspectRatio = "9:16"
    fps: int = 30
    safe_zone: SafeZone = "tiktok"


class LibraryFacet(_ManifestModel):
    key: str
    values: FacetValues


class LibrarySection(_ManifestModel):
    namespace: str = ""
    facets: list[LibraryFacet] = Field(default_factory=list)


class Limit(_ManifestModel):
    step: str
    seconds: int


class Param(_ManifestModel):
    key: str
    type: ParamType
    label: str
    required: bool = False
    default: Any = None
    help: str | None = None
    affects_cost: bool = False
    min: float | None = None
    max: float | None = None
    step: float | None = None
    options: list[Any] | None = None
    options_from: str | None = None
    placeholder: str | None = None
    accept: str | None = None
    unit: str | None = None


class Recovery(_ManifestModel):
    step: str
    label: str
    action: str
    param: str | None = None
    value: Any = None

    @model_validator(mode="after")
    def set_param_requires_param_and_value(self) -> Self:
        if self.action == "set_param" and (not self.param or self.value is None):
            raise ValueError("action set_param requires param and value")
        return self


class QualityFactor(_ManifestModel):
    key: str
    question: str


class WorkflowSection(_ManifestModel):
    id: str
    name: str
    version: str
    description: str | None = None
    thumbnail: str | None = None
    entrypoint: str
    prepare: str | None = None
    python: str = "3.12"
    sdk: SdkMajor
    video_semantics: VideoSemantics = "variants"
    max_videos: int | None = None
    atomic: bool = False
    safety_factor: float | None = None
    requires_binaries: list[str] = Field(default_factory=list)
    requires_capabilities: list[str] = Field(default_factory=list)


class Manifest(_ManifestModel):
    workflow: WorkflowSection
    output: OutputSection = Field(default_factory=OutputSection)
    library: LibrarySection = Field(default_factory=LibrarySection)
    requires_keys: list[RequiresKey] = Field(default_factory=list)
    requires_connections: list[RequiresConnection] = Field(default_factory=list)
    limits: list[Limit] = Field(default_factory=list)
    params: list[Param] = Field(default_factory=list)
    recovery: list[Recovery] = Field(default_factory=list)
    quality_factors: list[QualityFactor] = Field(default_factory=list)

    @model_validator(mode="after")
    def default_library_namespace(self) -> Self:
        if self.library.namespace:
            return self
        return self.model_copy(
            update={"library": self.library.model_copy(update={"namespace": self.workflow.id})}
        )


def parse_manifest_toml(text: str) -> Manifest:
    return Manifest.model_validate(tomllib.loads(text))
