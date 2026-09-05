from __future__ import annotations

from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType
from typing import Any, Literal, TypeVar, cast, overload

from pydantic import BaseModel, ConfigDict, Field

from ._budget import BudgetError, BudgetGuard, Ceilings
from .cache import StepCache, step_key
from .emit import decision, emit, heartbeat, log, stage

_T = TypeVar("_T")
_R = TypeVar("_R")

_SHORT_KEY_LEN = 12


@dataclass
class Outcome:
    """Result of one `ctx.map` item when `on_error="collect"`."""

    value: Any
    error: Exception | None

    @property
    def ok(self) -> bool:
        return self.error is None


class _ContextModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class BudgetConfig(_ContextModel):
    """Budget-guard configuration carried into the run (T2b). Absent → the gate is inert.

    Ceilings and per-meter reserve estimates are keyed by meter (a provider id, e.g. "openrouter").
    The supervisor populates this from app config (T2b-2); the SDK enforces it before each call.
    """

    ledger_path: Path = Field(description="JSONL spend ledger shared across this machine's runs.")
    kill_switch_path: Path | None = Field(
        default=None, description="If this file exists, all paid calls are refused."
    )
    per_run: dict[str, float] = Field(
        default_factory=dict, description="Per-meter ceiling for one run; meter absent = unlimited."
    )
    per_day: dict[str, float] = Field(
        default_factory=dict, description="Per-meter ceiling per UTC day; meter absent = unlimited."
    )
    estimates: dict[str, float] = Field(
        default_factory=dict,
        description="Per-meter conservative amount reserved before a call (must be > 0 to gate).",
    )


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
    workflow: Path | None = Field(
        default=None,
        description="The workflow's own folder (read-only).",
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
    workflow_id: str = Field(default="", description="The workflow's id.")
    run_id: str = Field(default="", description="The run folder name.")
    video_index: int = Field(default=0, description="1-based index of this video; 0 for prepare.")
    video_count: int = Field(default=0, description="How many videos this request produces.")
    dry_run: bool = Field(default=False, description="True when running with fake assets.")
    step_concurrency: int = Field(
        default=1,
        description="User's parallel-steps setting for ctx.map.",
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
    budget: BudgetConfig | None = Field(
        default=None,
        description="Budget-guard config; when set, paid calls are gated before spending.",
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
        self._file = file
        self.settings = file.settings
        self.params = file.settings
        self.paths = file.paths
        self.instructions = file.instructions
        self.previous = file.previous
        self.shared = file.shared
        self.workflow_version = file.workflow_version
        self.workflow_id = file.workflow_id
        self.run_id = file.run_id
        self.video_index = file.video_index
        self.video_count = file.video_count
        self.dry_run = file.dry_run
        self.step_concurrency = file.step_concurrency
        self.video_dir = file.paths.video
        self.shared_dir = file.paths.shared
        self.workflow_dir = file.paths.workflow
        self.artifacts = file.paths.artifacts

    def secret(self, name: str) -> str:
        """Return a permitted secret from the ambient context.

        The value is never logged. The encrypted store is out of scope.
        """
        return str(self._file.secrets[name])

    def _budget_reserve(self, meter: str, unit: str) -> str | None:
        """Reserve the configured estimate for `meter` before a paid call (T2b-1).

        No budget config → return None (gate inert). Otherwise reserve via a BudgetGuard built from
        the config; a refusal (ceiling/kill-switch) or a missing/non-positive estimate raises so the
        caller must not proceed. Returns the reservation token to pass to `_budget_reconcile`.
        """
        cfg = self._file.budget
        if cfg is None:
            return None
        estimate = cfg.estimates.get(meter)
        if estimate is None or not (estimate > 0):
            # Configured budget but no positive estimate for this meter → fail closed
            # (never reserve 0 as "unknown"): reserving nothing would let the call through ungated.
            raise BudgetError(f"no positive budget estimate configured for meter {meter!r}")
        guard = self._budget_guard(cfg)
        return guard.reserve(run_id=self.run_id, meter=meter, unit=unit, estimate=estimate)

    def _budget_reconcile(self, token: str | None, *, actual: float) -> None:
        """Reconcile a reservation with the real amount. No-op when token is None."""
        cfg = self._file.budget
        if token is None or cfg is None:
            return
        self._budget_guard(cfg).reconcile(token, actual=actual)

    def _budget_guard(self, cfg: BudgetConfig) -> BudgetGuard:
        return BudgetGuard(
            cfg.ledger_path,
            ceilings=Ceilings(per_run=cfg.per_run, per_day=cfg.per_day),
            kill_switch_path=cfg.kill_switch_path,
        )

    def emit(self, event: dict[str, Any]) -> None:
        emit(event)

    def log(self, msg: str, *, level: str = "info") -> None:
        log(msg, level=level)

    def stage(self, index: int, total: int, label: str) -> None:
        stage(index, total, label)

    def heartbeat(self, name: str, *, waiting_on: str, key: str | None = None) -> None:
        heartbeat(name, waiting_on=waiting_on, key=key)

    def decision(
        self,
        *,
        kind: str,
        chosen: str,
        alternatives: list[str] | None = None,
        reason: str | None = None,
    ) -> None:
        decision(kind, chosen, alternatives=alternatives, reason=reason)

    def step(
        self,
        family: str,
        *,
        inputs: dict[str, Any],
        label: str | None = None,
    ) -> _Step:
        return _Step(self, family, inputs, label)

    @overload
    def map(
        self,
        family: str,
        items: Iterable[_T],
        *,
        inputs: Callable[[_T], dict[str, Any]],
        fn: Callable[[_T], _R],
        label: Callable[[_T], str] | None = None,
        concurrency: int = 1,
        on_error: Literal["raise"] = "raise",
    ) -> list[_R]: ...

    @overload
    def map(
        self,
        family: str,
        items: Iterable[_T],
        *,
        inputs: Callable[[_T], dict[str, Any]],
        fn: Callable[[_T], _R],
        label: Callable[[_T], str] | None = None,
        concurrency: int = 1,
        on_error: Literal["collect"],
    ) -> list[Outcome]: ...

    def map(
        self,
        family: str,
        items: Iterable[_T],
        *,
        inputs: Callable[[_T], dict[str, Any]],
        fn: Callable[[_T], _R],
        label: Callable[[_T], str] | None = None,
        concurrency: int = 1,
        on_error: Literal["raise", "collect"] = "raise",
    ) -> list[_R] | list[Outcome]:
        ordered = list(items)

        def run_item(item: _T) -> _R:
            step_label = family if label is None else label(item)
            with self.step(family, inputs=inputs(item), label=step_label) as step:
                if not step.cached:
                    step.set(fn(item))
                return cast(_R, step.value)

        def run_collect(item: _T) -> Outcome:
            try:
                return Outcome(value=run_item(item), error=None)
            except Exception as exc:
                return Outcome(value=None, error=exc)

        with ThreadPoolExecutor(max_workers=max(1, concurrency)) as pool:
            if on_error == "collect":
                collected = [pool.submit(copy_context().run, run_collect, item) for item in ordered]
                return [future.result() for future in collected]
            submitted = [pool.submit(copy_context().run, run_item, item) for item in ordered]
            return [future.result() for future in submitted]
