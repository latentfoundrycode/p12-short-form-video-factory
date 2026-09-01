from __future__ import annotations

from pathlib import Path
from types import TracebackType
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .cache import StepCache, step_key
from .emit import emit, heartbeat, log, stage

_SHORT_KEY_LEN = 12


class _ContextModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ContextPaths(_ContextModel):
    """Paths the workflow is allowed to use for this video."""

    video: Path = Field(description="This video's working directory.")
    artifacts: Path = Field(description="Where the workflow writes intermediate artifacts.")
    steps: Path = Field(description="The .steps directory for saved step results.")
    shared: Path = Field(description="Shared directory for this generation request.")
    cache: Path | None = Field(
        default=None,
        description="The content-addressed cache root.",
    )


class ContextFile(_ContextModel):
    """The context.json file the runner reads.

    The JSON-file boundary is stable. SDK-stage fields extend the content so the
    context carries everything the workflow needs to begin (Architecture §3.2).
    """

    workflow_version: str = Field(
        default="0",
        description="Workflow version used to key cached step results.",
    )
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


def _video_files(value: object, video: Path) -> dict[str, Path]:
    """Collect video-relative file paths named by strings in `value`."""
    found: dict[str, Path] = {}

    def walk(item: object) -> None:
        if isinstance(item, dict):
            for nested in item.values():
                walk(nested)
            return
        if isinstance(item, list):
            for nested in item:
                walk(nested)
            return
        if isinstance(item, str):
            candidate = video / item
            if candidate.is_file():
                found[item] = candidate

    walk(value)
    return found


class _Step:
    """Handle yielded by `Context.step`; cache lookup on enter, store on exit."""

    def __init__(
        self,
        ctx: Context,
        family: str,
        inputs: dict[str, Any],
        label: str | None,
    ) -> None:
        self._ctx = ctx
        self._family = family
        self._inputs = inputs
        self._label = family if label is None else label
        self._key = ""
        self.cached = False
        self.value: Any = None
        self._set_called = False

    def set(self, value: Any) -> Any:
        self.value = value
        self._set_called = True
        return value

    def __enter__(self) -> _Step:
        cache_root = self._ctx.paths.cache
        if cache_root is None:
            raise RuntimeError("ctx.step requires paths.cache, the content-addressed cache root")
        self._key = step_key(self._ctx.workflow_version, self._family, self._inputs)
        found = StepCache(cache_root).get(self._key, restore_into=self._ctx.paths.video)
        if found is not None:
            self.cached = True
            self.value = found
        else:
            self.cached = False
            self.value = None
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if exc_type is not None:
            return
        if self.cached:
            self._emit("cached")
            return
        if not self._set_called:
            return
        cache_root = self._ctx.paths.cache
        if cache_root is None:
            raise RuntimeError("ctx.step requires paths.cache, the content-addressed cache root")
        files = _video_files(self.value, self._ctx.paths.video)
        StepCache(cache_root).put(self._key, self.value, files=files)
        self._emit("ok")

    def _emit(self, status: str) -> None:
        self._ctx.emit(
            {
                "t": "step",
                "name": self._family,
                "key": self._key[:_SHORT_KEY_LEN],
                "label": self._label,
                "status": status,
            }
        )


class Context:
    """Minimal runtime context passed to the workflow entrypoint as `func(ctx)`."""

    def __init__(self, file: ContextFile) -> None:
        self.settings = file.settings
        self.paths = file.paths
        self.instructions = file.instructions
        self.previous = file.previous
        self.shared = file.shared
        self.workflow_version = file.workflow_version
        self.artifacts = file.paths.artifacts

    def emit(self, event: dict[str, Any]) -> None:
        emit(event)

    def log(self, msg: str, *, level: str = "info") -> None:
        log(msg, level=level)

    def stage(self, index: int, total: int, label: str) -> None:
        stage(index, total, label)

    def heartbeat(self, name: str, *, waiting_on: str, key: str | None = None) -> None:
        heartbeat(name, waiting_on=waiting_on, key=key)

    def step(
        self,
        family: str,
        *,
        inputs: dict[str, Any],
        label: str | None = None,
    ) -> _Step:
        return _Step(self, family, inputs, label)
