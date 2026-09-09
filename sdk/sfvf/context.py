from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType
from typing import Any, Literal, TypeVar, cast, overload

from pydantic import BaseModel, ConfigDict, Field

from ._budget import BudgetError, BudgetGuard, Ceilings
from .cache import CHEAP, PAID, StepCache, step_key
from .emit import decision, emit, forecast, heartbeat, log, stage
from .library import Asset, FacetSpec

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
    """Budget-guard config carried into the run (T2b). Absent → a real paid call is refused (H21).

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
    library: Path | None = Field(
        default=None,
        description="The library namespace root (library/<namespace>); written in a real run.",
    )
    library_overlay: Path | None = Field(
        default=None,
        description="Dry-run overlay root: writes land here and are discarded at run end (§7.9).",
    )


class LibraryFacetDecl(_ContextModel):
    """A declared library facet carried in context.json: key + open (None) or a closed value set."""

    key: str
    values: list[str] | None = None


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
    library_facets: list[LibraryFacetDecl] = Field(
        default_factory=list,
        description="The workflow's declared library facet vocabulary (§7.4).",
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
        paid: bool = False,
    ) -> None:
        self._ctx = ctx
        self._family = family
        self._inputs = inputs
        self._label = family if label is None else label
        self._paid = paid
        self._key = ""
        self.cached = False
        self.value: Any = None
        self._set_called = False

    def set(self, value: Any) -> Any:
        self.value = value
        self._set_called = True
        return value

    def _step_cache(self) -> StepCache:
        cache_root = self._ctx.paths.cache
        if cache_root is None:
            raise RuntimeError("ctx.step requires paths.cache, the content-addressed cache root")
        return StepCache(cache_root, partition=(PAID if self._paid else CHEAP))

    def __enter__(self) -> _Step:
        self._key = step_key(self._ctx.workflow_version, self._family, self._inputs)
        found = self._step_cache().get(self._key, restore_into=self._ctx.paths.video)
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
        files = _video_files(self.value, self._ctx.paths.video)
        self._step_cache().put(self._key, self.value, files=files)
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


class Library:
    """The `ctx.library` facade: the durable asset store as a workflow sees it (SDK §7).

    Reads (find/get/value/describe) resolve against the real library. Writes (put/annotate) go to
    the real library in a real run, but in a DRY run go to a per-run overlay discarded at the end,
    so a rehearsal never leaves stubs behind and never mutates the real library (§7.9): reads see
    the overlay layered over the real library. `put` accepts a file Path or JSON data; a novel
    first-seen open facet value emits a `library` event.

    SKELETON — the public method signatures are frozen by tests/sdk/test_ctx_library.py; the builder
    fills the bodies (including the dry-run overlay read-through and copy-on-write).
    """

    def __init__(
        self,
        ctx: Context,
        real_root: Path,
        overlay_root: Path | None,
        facets: Sequence[FacetSpec],
    ) -> None:
        self._ctx = ctx
        self._facets = tuple(facets)
        self._real_root = real_root
        # An overlay is used only in a dry run; a real run writes straight to the real library.
        self._overlay_root = overlay_root if ctx.dry_run else None

    def find(
        self,
        *,
        tags: Sequence[str] = (),
        facets: Mapping[str, str] | None = None,
        status: str | None = "active",
    ) -> list[Asset]:
        """Return matching assets — overlay layered over the real library in a dry run (§7.5)."""
        raise NotImplementedError

    def get(self, name_or_id: str) -> Asset | None:
        """Resolve a name or id to its asset (overlay first in a dry run), else None."""
        raise NotImplementedError

    def value(self, name_or_id: str) -> Any | None:
        """Return a value asset's JSON (overlay first in a dry run), else None (§7.6)."""
        raise NotImplementedError

    def describe(self, assets: Sequence[Asset]) -> str:
        """Compact text describing the assets for an agent prompt — it does not choose (§7.5)."""
        raise NotImplementedError

    def put(
        self,
        name: str | None,
        source: Path | Any,
        *,
        kind: str | None = None,
        tags: Sequence[str] = (),
        facets: Mapping[str, str] | None = None,
        description: str = "",
        caveats: str = "",
        supersedes: str | None = None,
        provenance: Mapping[str, Any] | None = None,
    ) -> Asset:
        """Store a file (Path) or JSON data as an asset; emits a `library` event on a novel value.

        Writes to the dry-run overlay when the run is dry, else to the real library.
        """
        raise NotImplementedError

    def annotate(
        self,
        asset_id: str,
        *,
        caveats: str | None = None,
        facets: Mapping[str, str] | None = None,
    ) -> Asset:
        """Update an asset's caveats/facets (§7.5). In a dry run the change lands in the overlay
        (copy-on-write from the real asset), leaving the real library untouched."""
        raise NotImplementedError


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
        self.library = self._make_library()

    def _make_library(self) -> Library | None:
        root = self._file.paths.library
        if root is None:
            return None
        facets = tuple(
            FacetSpec(decl.key, tuple(decl.values) if decl.values is not None else None)
            for decl in self._file.library_facets
        )
        return Library(self, root, self._file.paths.library_overlay, facets)

    def secret(self, name: str) -> str:
        """Return a permitted secret from the ambient context.

        The value is never logged. The encrypted store is out of scope.
        """
        return str(self._file.secrets[name])

    def _budget_reserve(self, meter: str, unit: str) -> str:
        """Reserve the configured estimate for `meter` before a paid call (T2b-1).

        No budget config → raise BudgetError (fail-closed; refuse the paid call). Otherwise reserve
        via a BudgetGuard built from the config; a refusal (ceiling/kill-switch) or a
        missing/non-positive estimate raises so the caller must not proceed. Returns the reservation
        token to pass to `_budget_reconcile`.
        """
        cfg = self._file.budget
        if cfg is None:
            raise BudgetError(
                f"no budget configured; refusing paid call for meter {meter!r} "
                "— set SFVF_BUDGET_CONFIG"
            )
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

    def forecast(self, meter: str, unit: str, amount: float, note: str | None = None) -> None:
        forecast(meter, unit, amount, note=note)

    def step(
        self,
        family: str,
        *,
        inputs: dict[str, Any],
        label: str | None = None,
        paid: bool = False,
    ) -> _Step:
        return _Step(self, family, inputs, label, paid)

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
        paid: bool = False,
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
        paid: bool = False,
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
        paid: bool = False,
    ) -> list[_R] | list[Outcome]:
        ordered = list(items)

        def run_item(item: _T) -> _R:
            step_label = family if label is None else label(item)
            with self.step(family, inputs=inputs(item), label=step_label, paid=paid) as step:
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
