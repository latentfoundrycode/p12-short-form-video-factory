# Review B — cross-family verification (SDK-2: ctx.step, the cached step boundary)

You are an independent, READ-ONLY reviewer (GPT-5.6 Sol, OpenAI family). Do NOT modify any file. Read
the diff embedded below and answer.

## Context
New `ctx.step` in `sdk/sfvf/context.py` (SDK-only; uses the merged `sfvf.cache`). Workflow SDK §4.5,
§5.1-§5.5. A step: on enter computes `step_key(workflow_version, family, inputs)` and does
`StepCache(paths.cache).get(key, restore_into=paths.artifacts)` → hit sets `cached=True`/`value` (body
skipped) / miss `cached=False`; `set(value)` records the result; on exit — if the body raised, store
NOTHING; if hit, emit `step` event status="cached"; if miss+set, derive artifact-relative files named
in `value`, `put(key, value, files=...)`, emit status="ok". `label` is display-only (not in key).
Two new OPTIONAL context fields (`ContextPaths.cache`, `ContextFile.workflow_version`, both defaulted so
existing `context.json` still validates). The reviewer test is `tests/sdk/test_step.py` (6 tests).

Process note for your gate-integrity check: the reviewer test had two lint nits (authored by the
supervisor); they were reflowed (import grouping + a combined `with`) with ALL ASSERTIONS UNCHANGED.
Confirm from the test in the tree that no assertion was weakened, deleted, or skipped.

## Implementation diff under review:

```diff
diff --git a/sdk/sfvf/context.py b/sdk/sfvf/context.py
index 18c5d0f..c285d79 100644
--- a/sdk/sfvf/context.py
+++ b/sdk/sfvf/context.py
@@ -1,10 +1,16 @@
+from __future__ import annotations
+
 from pathlib import Path
+from types import TracebackType
 from typing import Any
 
 from pydantic import BaseModel, ConfigDict, Field
 
+from .cache import StepCache, step_key
 from .emit import emit, heartbeat, log, stage
 
+_SHORT_KEY_LEN = 12
+
 
 class _ContextModel(BaseModel):
     model_config = ConfigDict(extra="forbid")
@@ -17,14 +23,23 @@ class ContextPaths(_ContextModel):
     artifacts: Path = Field(description="Where the workflow writes intermediate artifacts.")
     steps: Path = Field(description="The .steps directory for saved step results.")
     shared: Path = Field(description="Shared directory for this generation request.")
+    cache: Path | None = Field(
+        default=None,
+        description="The content-addressed cache root.",
+    )
 
 
 class ContextFile(_ContextModel):
     """The context.json file the runner reads.
 
-    This is a fixed boundary contract; Stage 3 extends behaviour, not this shape.
+    The JSON-file boundary is stable. SDK-stage fields extend the content so the
+    context carries everything the workflow needs to begin (Architecture §3.2).
     """
 
+    workflow_version: str = Field(
+        default="0",
+        description="Workflow version used to key cached step results.",
+    )
     settings: dict[str, Any] = Field(description="Locked, validated parameters for this run.")
     paths: ContextPaths = Field(description="Directories the workflow should read and write.")
     instructions: list[Path] = Field(
@@ -45,6 +60,98 @@ class ContextFile(_ContextModel):
     )
 
 
+def _artifact_files(value: object, artifacts: Path) -> dict[str, Path]:
+    """Collect artifact-relative file paths named by strings in `value`."""
+    found: dict[str, Path] = {}
+
+    def walk(item: object) -> None:
+        if isinstance(item, dict):
+            for nested in item.values():
+                walk(nested)
+            return
+        if isinstance(item, list):
+            for nested in item:
+                walk(nested)
+            return
+        if isinstance(item, str):
+            candidate = artifacts / item
+            if candidate.is_file():
+                found[item] = candidate
+
+    walk(value)
+    return found
+
+
+class _Step:
+    """Handle yielded by `Context.step`; cache lookup on enter, store on exit."""
+
+    def __init__(
+        self,
+        ctx: Context,
+        family: str,
+        inputs: dict[str, Any],
+        label: str | None,
+    ) -> None:
+        self._ctx = ctx
+        self._family = family
+        self._inputs = inputs
+        self._label = family if label is None else label
+        self._key = ""
+        self.cached = False
+        self.value: Any = None
+        self._set_called = False
+
+    def set(self, value: Any) -> Any:
+        self.value = value
+        self._set_called = True
+        return value
+
+    def __enter__(self) -> _Step:
+        cache_root = self._ctx.paths.cache
+        if cache_root is None:
+            raise RuntimeError("ctx.step requires paths.cache, the content-addressed cache root")
+        self._key = step_key(self._ctx.workflow_version, self._family, self._inputs)
+        found = StepCache(cache_root).get(self._key, restore_into=self._ctx.paths.artifacts)
+        if found is not None:
+            self.cached = True
+            self.value = found
+        else:
+            self.cached = False
+            self.value = None
+        return self
+
+    def __exit__(
+        self,
+        exc_type: type[BaseException] | None,
+        exc: BaseException | None,
+        tb: TracebackType | None,
+    ) -> None:
+        if exc_type is not None:
+            return
+        if self.cached:
+            self._emit("cached")
+            return
+        if not self._set_called:
+            return
+        cache_root = self._ctx.paths.cache
+        if cache_root is None:
+            raise RuntimeError("ctx.step requires paths.cache, the content-addressed cache root")
+        files = _artifact_files(self.value, self._ctx.paths.artifacts)
+        StepCache(cache_root).put(self._key, self.value, files=files)
+        self._emit("ok")
+
+    def _emit(self, status: str) -> None:
+        self._ctx.emit(
+            {
+                "t": "step",
+                "name": self._family,
+                "key": self._key[:_SHORT_KEY_LEN],
+                "label": self._label,
+                "status": status,
+            }
+        )
+
+
 class Context:
     """Minimal runtime context passed to the workflow entrypoint as `func(ctx)`."""
 
@@ -54,6 +161,8 @@ class Context:
         self.instructions = file.instructions
         self.previous = file.previous
         self.shared = file.shared
+        self.workflow_version = file.workflow_version
+        self.artifacts = file.paths.artifacts
 
     def emit(self, event: dict[str, Any]) -> None:
         emit(event)
@@ -66,3 +175,12 @@ class Context:
 
     def heartbeat(self, name: str, *, waiting_on: str, key: str | None = None) -> None:
         heartbeat(name, waiting_on=waiting_on, key=key)
+
+    def step(
+        self,
+        family: str,
+        *,
+        inputs: dict[str, Any],
+        label: str | None = None,
+    ) -> _Step:
+        return _Step(self, family, inputs, label)
```

## Answer concisely
1. Correctness: hit returns the cached value without running the body; miss runs the body and stores the result; `label` is NOT in the key (a differently-labelled call with identical inputs still hits); a version bump invalidates; files named in the returned value are stored/restored by content; a body that RAISES stores nothing.
2. Any correctness bug or regression (e.g. exception handling in `__exit__`, file derivation walking, cache=None handling, step-event shape `{t,name,key,label,status}`).
3. Scope confined to `sdk/sfvf/context.py`; the new context fields are optional (existing context.json still validates); nothing weakened. (Read `tests/sdk/test_step.py` in the tree to confirm assertions are intact.)

First, in one sentence, confirm you can see the diff (name the private handle class `ctx.step` returns).

End with a single final line, exactly one of:
VERDICT: APPROVE
VERDICT: REJECT — <reason>
VERDICT: ESCALATE-INTENT — <one plain-language intent question>
