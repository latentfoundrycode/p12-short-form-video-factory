# Review B — cross-family verification (SDK-1 cache, REVISED after your REJECT)

You are an independent, READ-ONLY reviewer (GPT-5.6 Sol, OpenAI family). Do NOT modify any file. Read
the diff embedded below and answer.

## Context — this is a RE-REVIEW
You previously REJECTed this `sdk/sfvf/cache.py` for three real defects (now covered by added tests
that failed on the first attempt and pass now). The implementer fixed them:
1. A content-hashed `Path` is now a marked dict `{"__sfvf_file_sha256__": "<hex>"}`, structurally
   distinct from a plain string of the same digest (no collision).
2. Dicts are canonicalized as a sorted list of `[canonical_key, canonical_value]` pairs, so a `Path`
   used as a dict KEY is content-hashed too (not converted to path text). Determinism preserved.
3. `put` and `get` call `_reject_escaping_name`, raising `ValueError` for a file name that is absolute,
   has a drive/root anchor, or contains `..` — so restore cannot escape `restore_into`.

Confirm these three fixes are correct and complete, and that nothing that already worked regressed.
Paid/cheap partition + LRU remain intentionally deferred (not a gap).

## Full final module under review:

```diff
diff --git a/sdk/sfvf/cache.py b/sdk/sfvf/cache.py
new file mode 100644
index 0000000..53e066d
--- /dev/null
+++ b/sdk/sfvf/cache.py
@@ -0,0 +1,140 @@
+"""Content-addressed step cache keyed on workflow version, family, and inputs."""
+
+from __future__ import annotations
+
+import hashlib
+import json
+import os
+import shutil
+import tempfile
+from collections.abc import Mapping
+from pathlib import Path
+from typing import Any
+
+_CHUNK = 1024 * 1024
+_FILE_SHA256_MARK = "__sfvf_file_sha256__"
+
+
+def _file_digest(path: Path) -> str:
+    hasher = hashlib.sha256()
+    with path.open("rb") as handle:
+        while True:
+            chunk = handle.read(_CHUNK)
+            if not chunk:
+                break
+            hasher.update(chunk)
+    return hasher.hexdigest()
+
+
+def _canonical_json(value: object) -> str:
+    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
+
+
+def _canonicalize(value: object) -> object:
+    if isinstance(value, Path):
+        return {_FILE_SHA256_MARK: _file_digest(value)}
+    if isinstance(value, dict):
+        pairs = [[_canonicalize(key), _canonicalize(item)] for key, item in value.items()]
+        pairs.sort(key=lambda pair: _canonical_json(pair[0]))
+        return pairs
+    if isinstance(value, list):
+        return [_canonicalize(item) for item in value]
+    return value
+
+
+def _reject_escaping_name(name: str) -> None:
+    rel = Path(name)
+    if rel.is_absolute() or rel.anchor or ".." in rel.parts:
+        raise ValueError(f"cache file name is not a confined relative path: {name}")
+
+
+def step_key(workflow_version: str, family: str, inputs: dict[str, Any]) -> str:
+    payload: list[object] = [workflow_version, family, _canonicalize(inputs)]
+    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()
+
+
+def _write_json_atomic(path: Path, payload: object) -> None:
+    path.parent.mkdir(parents=True, exist_ok=True)
+    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
+    tmp_path = Path(tmp_name)
+    try:
+        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
+            json.dump(payload, handle, ensure_ascii=False, indent=2)
+            handle.write("\n")
+            handle.flush()
+            os.fsync(handle.fileno())
+        os.replace(tmp_path, path)  # noqa: PTH105  # os.replace is atomic on Windows
+    except Exception:
+        tmp_path.unlink(missing_ok=True)
+        raise
+
+
+def _copy_atomic(src: Path, dest: Path) -> None:
+    dest.parent.mkdir(parents=True, exist_ok=True)
+    fd, tmp_name = tempfile.mkstemp(prefix=f".{dest.name}.", suffix=".tmp", dir=dest.parent)
+    tmp_path = Path(tmp_name)
+    try:
+        with os.fdopen(fd, "wb") as handle:
+            with src.open("rb") as reader:
+                shutil.copyfileobj(reader, handle)
+            handle.flush()
+            os.fsync(handle.fileno())
+        os.replace(tmp_path, dest)  # noqa: PTH105  # os.replace is atomic on Windows
+    except Exception:
+        tmp_path.unlink(missing_ok=True)
+        raise
+
+
+class StepCache:
+    """Filesystem store for a step's JSON result and content-addressed files."""
+
+    def __init__(self, root: Path) -> None:
+        self._entries = root / "entries"
+        self._blobs = root / "blobs"
+
+    def _entry_path(self, key: str) -> Path:
+        return self._entries / key
+
+    def _blob_path(self, digest: str) -> Path:
+        return self._blobs / digest
+
+    def get(self, key: str, *, restore_into: Path | None = None) -> Any | None:
+        path = self._entry_path(key)
+        if not path.is_file():
+            return None
+        raw: object = json.loads(path.read_text(encoding="utf-8"))
+        if not isinstance(raw, dict):
+            raise TypeError(f"cache entry is not a JSON object: {path}")
+        if restore_into is not None:
+            stored = raw.get("files", {})
+            if isinstance(stored, dict):
+                confined: list[tuple[str, str]] = []
+                for relative, digest in stored.items():
+                    if not isinstance(relative, str) or not isinstance(digest, str):
+                        continue
+                    _reject_escaping_name(relative)
+                    confined.append((relative, digest))
+                for relative, digest in confined:
+                    dest = restore_into / relative
+                    dest.parent.mkdir(parents=True, exist_ok=True)
+                    shutil.copyfile(self._blob_path(digest), dest)
+        return raw["value"]
+
+    def put(
+        self,
+        key: str,
+        value: Any,
+        *,
+        files: Mapping[str, Path] | None = None,
+    ) -> None:
+        mapping: dict[str, str] = {}
+        if files:
+            for relative in files:
+                _reject_escaping_name(relative)
+            for relative, src in files.items():
+                digest = _file_digest(src)
+                dest = self._blob_path(digest)
+                if not dest.is_file():
+                    _copy_atomic(src, dest)
+                mapping[relative] = digest
+        _write_json_atomic(self._entry_path(key), {"value": value, "files": mapping})
```

## Answer concisely
1. Are the three fixes correct and complete (marked Path so no string collision; Path dict-keys content-hashed via sorted `[key,value]` pairs with preserved determinism; `..`/absolute/anchor names refused in both put and get)?
2. Any remaining correctness bug: key stability/order-independence, on-disk round-trip, atomic writes, restore confinement, or a regression from the first version?
3. Scope/gate-integrity: confined to `sdk/sfvf/cache.py`; nothing weakened.

First, in one sentence, confirm you can see the diff (name the marker constant used for a hashed Path) so it's clear you received it.

End with a single final line, exactly one of:
VERDICT: APPROVE
VERDICT: REJECT — <reason>
VERDICT: ESCALATE-INTENT — <one plain-language intent question>
