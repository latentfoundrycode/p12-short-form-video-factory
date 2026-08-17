from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .emit import emit, heartbeat, log, stage


class _ContextModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ContextPaths(_ContextModel):
    """Paths the workflow is allowed to use for this video."""

    video: Path = Field(description="This video's working directory.")
    artifacts: Path = Field(description="Where the workflow writes intermediate artifacts.")
    steps: Path = Field(description="The .steps directory for saved step results.")
    shared: Path = Field(description="Shared directory for this generation request.")


class ContextFile(_ContextModel):
    """The context.json file the runner reads.

    This is a fixed boundary contract; Stage 3 extends behaviour, not this shape.
    """

    settings: dict[str, Any] = Field(description="Locked, validated parameters for this run.")
    paths: ContextPaths = Field(description="Directories the workflow should read and write.")
    instructions: list[Path] = Field(
        default_factory=list,
        description="Locations of the frozen instruction files that apply; may be empty.",
    )
    secrets: dict[str, Any] = Field(
        default_factory=dict,
        description="Placeholder for permitted secrets. Empty until Stage 5.",
    )
    previous: dict[str, Any] | None = Field(
        default=None,
        description="Prior video's Result.extra under sequence; None otherwise.",
    )
    shared: dict[str, Any] | None = Field(
        default=None,
        description="Output of the shared preparation phase, if any.",
    )


class Context:
    """Minimal runtime context passed to the workflow entrypoint as `func(ctx)`."""

    def __init__(self, file: ContextFile) -> None:
        self.settings = file.settings
        self.paths = file.paths
        self.instructions = file.instructions
        self.previous = file.previous
        self.shared = file.shared

    def emit(self, event: dict[str, Any]) -> None:
        emit(event)

    def log(self, msg: str, *, level: str = "info") -> None:
        log(msg, level=level)

    def stage(self, index: int, total: int, label: str) -> None:
        stage(index, total, label)

    def heartbeat(self, name: str, *, waiting_on: str, key: str | None = None) -> None:
        heartbeat(name, waiting_on=waiting_on, key=key)
