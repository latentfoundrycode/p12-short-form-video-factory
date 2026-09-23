import json
from pathlib import Path


def prepare(ctx) -> None:
    # H18 trigger: a prepare that writes shared/result.json (its cwd) carrying its own injected
    # secret VALUE, then exits non-zero. The runner's inline result redaction never runs (prepare
    # raised), so _run_prepare returns before the success-path redact — the leaked secret would
    # persist on disk (and result.json, unlike context.json, is downloadable) unless the finally
    # scrubs it best-effort.
    key = ctx.secret("OPENROUTER_API_KEY")
    Path("result.json").write_text(json.dumps({"leaked": key}), encoding="utf-8")
    raise RuntimeError("prepare boom after writing result.json")


def run(ctx) -> None:
    ctx.emit({"t": "result", "video": "final.mp4", "caption": "unreached"})
