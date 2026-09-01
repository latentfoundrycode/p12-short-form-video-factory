# Review B — cross-family verification (SDK-2 ctx.step, REVISED: video-relative file paths)

You are an independent, READ-ONLY reviewer (GPT-5.6 Sol, OpenAI family). Do NOT modify any file. Read
the diff embedded below and answer.

## Context — re-review
You previously raised (ESCALATE-INTENT) that returned file paths were treated as artifacts-relative,
while SDK §5.5 says they are relative to the VIDEO folder. The spec settles it (video-relative), so it
was corrected: `ctx.step` now derives files-to-store by walking `value` for paths relative to
`self.paths.video` that exist, and restores with `StepCache.get(key, restore_into=self.paths.video)`.
The reviewer test now writes `video/artifacts/final.mp4`, returns `"artifacts/final.mp4"`, and asserts
the cache hit restores it under the video folder. All other `ctx.step` behavior (cache hit/miss, label
not in key, version invalidation, raise-safety, step event, optional context fields) was already
confirmed correct by both reviewers and is unchanged.

## Full final implementation under review:

```diff
diff --git a/sdk/sfvf/context.py b/sdk/sfvf/context.py
index 18c5d0f..14a6c1a 100644
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
 
 
+def _video_files(value: object, video: Path) -> dict[str, Path]:
+    """Collect video-relative file paths named by strings in `value`."""
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
+            candidate = video / item
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
+        found = StepCache(cache_root).get(self._key, restore_into=self._ctx.paths.video)
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
+        files = _video_files(self.value, self._ctx.paths.video)
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
1. Are returned file paths now correctly VIDEO-relative per §5.5 (derived relative to `paths.video`; restored into `paths.video`), and do all previously-confirmed behaviors still hold?
2. Any remaining correctness bug or regression?
3. Scope confined to `sdk/sfvf/context.py`; the reviewer test (`tests/sdk/test_step.py` in the tree) has intact assertions; nothing weakened.

First, in one sentence, confirm you can see the diff (name the helper function that collects files to store).

End with a single final line, exactly one of:
VERDICT: APPROVE
VERDICT: REJECT — <reason>
VERDICT: ESCALATE-INTENT — <one plain-language intent question>
