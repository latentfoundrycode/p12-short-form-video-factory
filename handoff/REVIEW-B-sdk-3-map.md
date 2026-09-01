# Review B — cross-family verification (SDK-3 ctx.map, REVISED: collect catches Exception)

You are an independent, READ-ONLY reviewer (GPT-5.6 Sol, OpenAI family). Do NOT modify any file. Read
the diffs embedded below and answer.

## Context — re-review
You previously REJECTed because `on_error="collect"` caught `BaseException`, swallowing process-control
exceptions. Fixed: the collect path now catches `Exception` only (a `BaseException` propagates out of
`ctx.map`), and `Outcome.error` is typed `Exception | None`. New test
`test_map_collect_collects_exceptions_but_propagates_base_exceptions` covers it. Everything else about
`ctx.map` (input-order results, per-item cached `ctx.step`, on_error modes, thread-safe `emit`) was
confirmed correct by both reviewers and is unchanged. Cancellation-between-items remains intentionally
deferred.

## Diffs under review (final):

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
index 14a6c1a..a8e7b3f 100644
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
+    error: Exception | None
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
+            except Exception as exc:
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
1. Is the collect path now correct (catches `Exception`, so ordinary failures become Outcomes but a `BaseException` propagates), with `Outcome.error: Exception | None`?
2. Do all previously-confirmed behaviors still hold (input-order results, per-item caching, raise mode, thread-safe emit)? Any remaining correctness/concurrency bug?
3. Scope confined to `sdk/sfvf/context.py` + `sdk/sfvf/emit.py`; reviewer test assertions intact; nothing weakened.

First, in one sentence, confirm you can see the diffs (state which exception type the collect path now catches).

End with a single final line, exactly one of:
VERDICT: APPROVE
VERDICT: REJECT — <reason>
VERDICT: ESCALATE-INTENT — <one plain-language intent question>
