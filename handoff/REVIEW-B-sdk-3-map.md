# Review B — cross-family verification (SDK-3: ctx.map + thread-safe emit)

You are an independent, READ-ONLY reviewer (GPT-5.6 Sol, OpenAI family). Do NOT modify any file. Read
the diffs embedded below and answer.

## Context
SDK-3 adds `ctx.map` (Workflow SDK §4.7) — run many items of one step family concurrently, each a full
`ctx.step` (so caching/file-handling/`step` event are inherited), results in INPUT order,
`on_error="raise"` returns `list[value]` and propagates the first failure, `on_error="collect"` returns
`list[Outcome]` (`value`/`error`/`ok`). Concurrency via `ThreadPoolExecutor`. Because concurrent steps
emit `step` events from multiple threads, `emit()` now serializes write+flush under a module lock so
lines cannot interleave. Cancellation-between-items is intentionally DEFERRED (ties to the stop
sentinel). Contract test: `tests/sdk/test_map.py` (6 tests).

## Diffs under review:

### sdk/sfvf/emit.py
```diff
diff --git a/sdk/sfvf/emit.py b/sdk/sfvf/emit.py
index 6f3c0ef..2fe5c6a 100644
--- a/sdk/sfvf/emit.py
+++ b/sdk/sfvf/emit.py
@@ -1,12 +1,17 @@
 import json
 import sys
+import threading
 from typing import Any
 
+_lock = threading.Lock()
+
 
 def emit(event: dict[str, Any]) -> None:
     """Write one compact JSON object to stdout and flush so a reader sees it immediately."""
-    sys.stdout.write(json.dumps(event, separators=(",", ":"), ensure_ascii=False) + "\n")
-    sys.stdout.flush()
+    line = json.dumps(event, separators=(",", ":"), ensure_ascii=False) + "\n"
+    with _lock:
+        sys.stdout.write(line)
+        sys.stdout.flush()
 
 
 def log(msg: str, *, level: str = "info") -> None:
```

### sdk/sfvf/context.py
```diff
diff --git a/sdk/sfvf/context.py b/sdk/sfvf/context.py
index 14a6c1a..ad0dc4e 100644
--- a/sdk/sfvf/context.py
+++ b/sdk/sfvf/context.py
@@ -1,17 +1,35 @@
 from __future__ import annotations
 
+from collections.abc import Callable, Iterable
+from concurrent.futures import ThreadPoolExecutor
+from dataclasses import dataclass
 from pathlib import Path
 from types import TracebackType
-from typing import Any
+from typing import Any, Literal, TypeVar, cast, overload
 
 from pydantic import BaseModel, ConfigDict, Field
 
 from .cache import StepCache, step_key
 from .emit import emit, heartbeat, log, stage
 
+_T = TypeVar("_T")
+_R = TypeVar("_R")
+
 _SHORT_KEY_LEN = 12
 
 
+@dataclass
+class Outcome:
+    """Result of one `ctx.map` item when `on_error="collect"`."""
+
+    value: Any
+    error: BaseException | None
+
+    @property
+    def ok(self) -> bool:
+        return self.error is None
+
+
 class _ContextModel(BaseModel):
     model_config = ConfigDict(extra="forbid")
 
@@ -184,3 +202,62 @@ class Context:
         label: str | None = None,
     ) -> _Step:
         return _Step(self, family, inputs, label)
+
+    @overload
+    def map(
+        self,
+        family: str,
+        items: Iterable[_T],
+        *,
+        inputs: Callable[[_T], dict[str, Any]],
+        fn: Callable[[_T], _R],
+        label: Callable[[_T], str] | None = None,
+        concurrency: int = 1,
+        on_error: Literal["raise"] = "raise",
+    ) -> list[_R]: ...
+
+    @overload
+    def map(
+        self,
+        family: str,
+        items: Iterable[_T],
+        *,
+        inputs: Callable[[_T], dict[str, Any]],
+        fn: Callable[[_T], _R],
+        label: Callable[[_T], str] | None = None,
+        concurrency: int = 1,
+        on_error: Literal["collect"],
+    ) -> list[Outcome]: ...
+
+    def map(
+        self,
+        family: str,
+        items: Iterable[_T],
+        *,
+        inputs: Callable[[_T], dict[str, Any]],
+        fn: Callable[[_T], _R],
+        label: Callable[[_T], str] | None = None,
+        concurrency: int = 1,
+        on_error: Literal["raise", "collect"] = "raise",
+    ) -> list[_R] | list[Outcome]:
+        ordered = list(items)
+
+        def run_item(item: _T) -> _R:
+            step_label = family if label is None else label(item)
+            with self.step(family, inputs=inputs(item), label=step_label) as step:
+                if not step.cached:
+                    step.set(fn(item))
+                return cast(_R, step.value)
+
+        def run_collect(item: _T) -> Outcome:
+            try:
+                return Outcome(value=run_item(item), error=None)
+            except BaseException as exc:
+                return Outcome(value=None, error=exc)
+
+        with ThreadPoolExecutor(max_workers=max(1, concurrency)) as pool:
+            if on_error == "collect":
+                collected = [pool.submit(run_collect, item) for item in ordered]
+                return [future.result() for future in collected]
+            submitted = [pool.submit(run_item, item) for item in ordered]
+            return [future.result() for future in submitted]
```

## Answer concisely
1. Correctness: are results returned in INPUT order regardless of completion order; is each item a full cached `ctx.step` (cache hit skips fn); does `on_error="raise"` propagate a failure and `on_error="collect"` return an `Outcome` per item; is `emit()` now safe against interleaved concurrent writes (line built before the lock, write+flush inside)?
2. Any correctness/concurrency bug (deadlock, lost results, races on the cache or on stdout, exception handling that swallows too much/little).
3. Scope confined to `sdk/sfvf/context.py` + `sdk/sfvf/emit.py`; reviewer test assertions intact; nothing weakened. (The deferral of cancellation-between-items is intended, not a gap.)

First, in one sentence, confirm you can see the diffs (name the executor class used and the emit lock).

End with a single final line, exactly one of:
VERDICT: APPROVE
VERDICT: REJECT — <reason>
VERDICT: ESCALATE-INTENT — <one plain-language intent question>
