"""Minimal live-path smoke workflow: one cheap OpenRouter call, no speech/render/HyperFrames.

Purpose: validate the live OpenRouter adapter + the budget breaker end to end with the smallest
possible real spend (one short `agents.llm` call on the cheapest reliable model). In dry_run the SDK
stubs the call (no key, no spend); in real mode it exercises secret injection → budget reserve → the
OpenRouter request → reconcile of the real usage.cost into the ledger.
"""

from sfvf import Context, Result, agents

_MODEL = "openai/gpt-4o-mini"


def run(ctx: Context) -> Result:
    reply = agents.llm(
        "Reply with exactly the single word: ok",
        agent="smoke",
        model=_MODEL,
    )
    text = reply if isinstance(reply, str) else str(reply)
    note = ctx.video_dir / "smoke.txt"
    note.write_text(text, encoding="utf-8")
    return Result(
        video=note,
        caption="openrouter smoke ok",
        extra={"model": _MODEL, "reply": text},
    )
