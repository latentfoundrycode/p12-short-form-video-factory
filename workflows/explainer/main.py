from datetime import date
from html import escape

from sfvf import Context, Result, agents, media


def _composition_html(script: str, timings: object, css_path: str) -> str:
    cues: list[str] = []
    if isinstance(timings, list):
        for item in timings:
            if not isinstance(item, dict):
                continue
            word = escape(str(item.get("word", "")))
            start = item.get("start", 0)
            end = item.get("end", 0)
            cues.append(f'<span data-start="{start}" data-end="{end}">{word}</span>')
    body = " ".join(cues)
    return (
        "<!DOCTYPE html><html><head>"
        f'<style>@import url("{escape(css_path, quote=True)}");</style>'
        "</head><body>"
        f'<div class="safe-zone"><p>{escape(script)}</p><p>{body}</p></div>'
        "</body></html>"
    )


def _caption(script: str) -> str:
    stripped = " ".join(script.split())
    return stripped[:120] if stripped else "Explainer"


def prepare(ctx: Context) -> dict:
    given = ctx.params.get("topic") or ""
    with ctx.step("choose-topic", inputs={"given": given}) as step:
        if not step.cached:
            if given:
                step.set(given)
            else:
                step.set(
                    agents.llm(
                        "Pick one topic worth explaining.",
                        agent="researcher",
                        model="stub-llm",
                    )
                )
    topic = step.value

    with ctx.step("research", inputs={"topic": topic, "as_of": date.today().isoformat()}) as step:
        if not step.cached:
            step.set(agents.research(topic))
    return {"topic": topic, "sources": step.value}


def run(ctx: Context) -> Result:
    topic = ctx.shared["topic"]
    duration = ctx.params["duration_s"]
    voice = ctx.params["voice"]

    with ctx.step(
        "script",
        inputs={"topic": topic, "variant": ctx.video_index, "duration": duration},
    ) as step:
        if not step.cached:
            step.set(
                agents.llm(
                    f"Write a {duration}-second script on {topic}.",
                    agent="scriptwriter",
                    model="stub-llm",
                )
            )
    script = step.value

    with ctx.step("speech", inputs={"script": script, "voice": voice}) as step:
        if not step.cached:
            step.set(media.speech.speak(script, voice=voice, model="stub-tts"))
    speech = step.value

    html = _composition_html(script, speech["timings"], media.graphics.safe_zone_css())
    with ctx.step("render", inputs={"html": html}) as step:
        if not step.cached:
            step.set(media.graphics.render(html, duration_s=speech["duration"]))
    visual = step.value

    captions = media.graphics.captions(speech["audio"], speech["timings"], style="bold")
    final = media.finalize(visual, audio=speech["audio"], captions=captions)
    return Result(video=ctx.video_dir / final, caption=_caption(script))
