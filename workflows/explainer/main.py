import json
from datetime import date
from html import escape

from sfvf import Context, Result, agents, media

# Real providers: a cheap OpenRouter model for the LLM steps; local Chatterbox for narration.
_LLM_MODEL = "openai/gpt-4o-mini"
_TTS_MODEL = "chatterbox"

_GROUP_SIZE = 4
_GROUP_HOLD_S = 0.4
_GROUP_GAP_S = 0.05


def _sec(value: object) -> float:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0


def _caption_groups(timings: object) -> list[dict[str, object]]:
    words: list[dict[str, object]] = []
    if isinstance(timings, list):
        for item in timings:
            if not isinstance(item, dict):
                continue
            words.append(
                {
                    "id": f"w{len(words)}",
                    "text": str(item.get("word", "")),
                    "start": _sec(item.get("start", 0)),
                    "end": _sec(item.get("end", 0)),
                }
            )
    chunks = [words[i : i + _GROUP_SIZE] for i in range(0, len(words), _GROUP_SIZE)]
    groups: list[dict[str, object]] = []
    for gi, chunk in enumerate(chunks):
        last_end = _sec(chunk[-1]["end"])
        hold_end = last_end + _GROUP_HOLD_S
        if gi + 1 < len(chunks):
            next_start = _sec(chunks[gi + 1][0]["start"])
            end = min(hold_end, next_start - _GROUP_GAP_S)
        else:
            end = hold_end
        groups.append(
            {
                "id": f"g{gi}",
                "start": _sec(chunk[0]["start"]),
                "end": end,
                "words": chunk,
            }
        )
    return groups


def _composition_html(script: str, timings: object, css_path: str) -> str:
    # `script` / `css_path` stay in the signature; on-screen text is the timed words.
    del script, css_path
    groups = _caption_groups(timings)
    payload: list[dict[str, object]] = []
    markup: list[str] = []
    for group in groups:
        word_spans: list[str] = []
        js_words: list[dict[str, object]] = []
        for word in group["words"]:  # type: ignore[union-attr]
            safe = escape(str(word["text"]))
            word_spans.append(
                f'<span class="cap-word" id="{word["id"]}"><span class="bg"></span>{safe}</span>'
            )
            js_words.append(
                {
                    "id": word["id"],
                    "start": word["start"],
                    "end": word["end"],
                }
            )
        markup.append(f'<div class="cap-group" id="{group["id"]}">{"".join(word_spans)}</div>')
        payload.append(
            {
                "id": group["id"],
                "start": group["start"],
                "end": group["end"],
                "words": js_words,
            }
        )
    # json.dumps' default ensure_ascii=True is REQUIRED for injection safety here —
    # it escapes U+2028/U+2029 (JS line terminators) and non-ASCII so untrusted word
    # text cannot break out of the inline <script>; do not pass ensure_ascii=False.
    groups_json = json.dumps(payload)
    return f"""<style>
@import url("https://fonts.googleapis.com/css2?family=Montserrat:wght@800&display=swap");
#captions {{
  position:absolute; left:0; right:0; bottom:22%;
  display:flex; flex-wrap:wrap; justify-content:center; align-items:flex-end;
  gap:10px; padding:0 90px;
}}
.cap-word {{
  font-family:"Montserrat",sans-serif; font-weight:800; font-size:76px;
  text-transform:uppercase; color:#ffffff; letter-spacing:0.02em; line-height:1.05;
  position:relative; isolation:isolate; display:inline-block; padding:6px 14px;
  text-shadow:0 6px 20px rgba(0,0,0,0.5);
}}
.cap-word .bg {{
  position:absolute; inset:0; z-index:-1; border-radius:12px;
  background:linear-gradient(135deg,#38bdf8,#2563eb);
  opacity:0; transform:scaleX(0); transform-origin:0% 50%;
}}
.cap-group {{
  position:absolute; left:0; right:0; bottom:0;
  display:flex; flex-wrap:wrap; justify-content:center; align-items:flex-end;
  gap:10px; padding:0 90px;
  opacity:0; visibility:hidden;
}}
</style>
<div id="captions">{"".join(markup)}</div>
<script>
window.__timelines = window.__timelines || {{}};
var GROUPS = {groups_json};
var tl = gsap.timeline({{paused:true}});
GROUPS.forEach(function (g) {{
  var group = "#" + g.id;
  tl.set(group, {{visibility:"visible"}}, g.start);
  tl.fromTo(group, {{opacity:0}}, {{opacity:1, duration:0.12, ease:"power2.out"}}, g.start);
  g.words.forEach(function (w) {{
    var bg = "#" + w.id + " .bg";
    tl.to(bg, {{opacity:1, scaleX:1, duration:0.12, ease:"power2.out"}}, w.start);
    tl.to(bg, {{opacity:0, scaleX:1.02, duration:0.1, ease:"power2.in"}}, w.end);
  }});
  tl.to(group, {{opacity:0, duration:0.1}}, g.end - 0.1);
  tl.set(group, {{visibility:"hidden"}}, g.end);
}});
tl.seek(0);
window.__timelines["main"] = tl;
</script>"""


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
                        model=_LLM_MODEL,
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
                    model=_LLM_MODEL,
                )
            )
    script = step.value

    with ctx.step("speech", inputs={"script": script, "voice": voice}) as step:
        if not step.cached:
            step.set(media.speech.speak(script, voice=voice, model=_TTS_MODEL))
    speech = step.value

    html = _composition_html(script, speech["timings"], media.graphics.safe_zone_css())
    with ctx.step("render", inputs={"html": html}) as step:
        if not step.cached:
            step.set(media.graphics.render(html, duration_s=speech["duration"]))
    visual = step.value

    captions = media.graphics.captions(speech["audio"], speech["timings"], style="bold")
    final = media.finalize(visual, audio=speech["audio"], captions=captions)
    return Result(video=ctx.video_dir / final, caption=_caption(script))
