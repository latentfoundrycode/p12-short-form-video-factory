import json
import posixpath
import re
from html import escape
from urllib.parse import urlparse

from sfvf import Context, Result, agents, media

# Real providers: a cheap OpenRouter model for the LLM steps; local Chatterbox for narration.
_LLM_MODEL = "openai/gpt-4o-mini"
_TTS_MODEL = "chatterbox"
_DURATION_S = 30

_GROUP_SIZE = 4
_GROUP_HOLD_S = 0.4
_GROUP_GAP_S = 0.05

_USED_SUBJECTS_CAP = 500
_POOL_PROMPT_LIMIT = 40
_POOL_TEXT_TITLE_MAX = 200
_POOL_TEXT_SNIPPET_MAX = 200

_SCIENCE_NEWS_ALLOWLIST: list[tuple[str, str]] = [
    ("sciencenews.org", ""),
    ("science.org", ""),
    ("sciencedaily.com", ""),
    ("nature.com", ""),
    ("scientificamerican.com", ""),
    ("bbc.com", "/news/science_and_environment"),
    ("phys.org", ""),
    ("sci.news", ""),
    ("livescience.com", ""),
    ("npr.org", "/sections/science"),
    ("cbc.ca", "/news/science"),
    ("snexplores.org", ""),
    ("newscientist.com", ""),
    ("reuters.com", "/science"),
    ("bloomberg.com", "/ai"),
    ("news.mit.edu", ""),
    ("reuters.com", "/technology"),
]

_SUBJECT_PICKER_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {"subjects": {"type": "array", "items": {"type": "string"}}},
    "required": ["subjects"],
}


def _normalize_host(host: str) -> str:
    h = host.lower()
    if h.startswith("www."):
        return h[4:]
    return h


def _url_on_allowlist(url: str, entry_host: str, path_prefix: str) -> bool:
    parsed = urlparse(url)
    hostname = parsed.hostname
    if hostname is None:
        return False
    if _normalize_host(hostname) != _normalize_host(entry_host):
        return False
    if path_prefix == "":
        return True
    raw_path = parsed.path or ""
    path = posixpath.normpath(raw_path or "/")
    if path == ".":
        path = "/"
    return path == path_prefix or path.startswith(path_prefix + "/")


def _allowlist_filter(sources: list) -> list:
    kept: list = []
    for source in sources:
        url = source.get("url", "")
        for host, prefix in _SCIENCE_NEWS_ALLOWLIST:
            if _url_on_allowlist(url, host, prefix):
                kept.append(source)
                break
    return kept


def _dedupe_sources_by_url(sources: list) -> list:
    seen: set[str] = set()
    out: list = []
    for source in sources:
        url = source.get("url", "")
        if url in seen:
            continue
        seen.add(url)
        out.append(source)
    return out


def _allowlist_site_hints() -> str:
    seen: set[str] = set()
    parts: list[str] = []
    for host, _ in _SCIENCE_NEWS_ALLOWLIST:
        if host in seen:
            continue
        seen.add(host)
        parts.append(f"site:{host}")
    return " OR ".join(parts)


def _research_query(*, strict: bool) -> str:
    if strict:
        hints = _allowlist_site_hints()
        return (
            f"Recent captivating science news stories for a lay audience ({hints}). "
            "Focus on surprising, entertaining discoveries and breakthroughs."
        )
    return (
        "Recent science news, discoveries, and research breakthroughs "
        "suitable for a general audience."
    )


def _build_sources_map(chosen: list[str], pool: list) -> dict[str, list]:
    by_title = {s.get("title", ""): s for s in pool}
    mapping: dict[str, list] = {}
    for subject in chosen:
        if subject in by_title:
            mapping[subject] = [by_title[subject]]
        else:
            mapping[subject] = list(pool)
    return mapping


def _pool_title_by_casefold(pool: list) -> dict[str, str]:
    out: dict[str, str] = {}
    for source in pool:
        title = str(source.get("title", ""))
        if title:
            out.setdefault(title.casefold(), title)
    return out


def _finalize_subject_list(picked: list[str], pool: list, used: set[str], n: int) -> list[str]:
    title_by_fold = _pool_title_by_casefold(pool)
    chosen: list[str] = []
    seen_fold: set[str] = set()
    for subject in picked:
        canonical = title_by_fold.get(subject.casefold())
        if canonical is None:
            continue
        if canonical in used:
            continue
        key = canonical.casefold()
        if key in seen_fold:
            continue
        seen_fold.add(key)
        chosen.append(canonical)
        if len(chosen) >= n:
            return chosen
    for source in pool:
        title = str(source.get("title", ""))
        if not title or title in used:
            continue
        key = title.casefold()
        if key in seen_fold:
            continue
        seen_fold.add(key)
        chosen.append(title)
        if len(chosen) >= n:
            break
    return chosen


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
  gap:10px; padding:0 162px;
}}
.cap-word {{
  font-family:"Montserrat",sans-serif; font-weight:800; font-size:76px;
  text-transform:uppercase; color:#ffffff; letter-spacing:0.02em; line-height:1.05;
  position:relative; isolation:isolate; display:inline-block; padding:6px 14px;
  text-shadow:0 6px 20px rgba(0,0,0,0.5);
  max-width:100%; overflow-wrap:anywhere;
}}
.cap-word .bg {{
  position:absolute; inset:0; z-index:-1; border-radius:12px;
  background:linear-gradient(135deg,#38bdf8,#2563eb);
  opacity:0; transform:scaleX(0); transform-origin:0% 50%;
}}
.cap-group {{
  position:absolute; left:0; right:0; bottom:0;
  display:flex; flex-wrap:wrap; justify-content:center; align-items:flex-end;
  gap:10px; padding:0 162px;
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


def _narration_text(raw: str) -> str:
    """Reduce an LLM 'script' to the words meant to be spoken: drop bracketed stage directions,
    markdown emphasis, speaker labels, and quotation marks; collapse whitespace."""
    text = re.sub(r"\[[^\]]*\]", " ", raw)  # [Scene: …], [Cut …], [End …]
    text = re.sub(
        r"(?i)\b(?:narrator|voice[\s-]?over|vo|host|speaker)\b\s*(?:\([^)]*\))?\s*:",
        " ",
        text,
    )  # "Narrator (voice-over):", "Narrator:"
    text = re.sub(r"[*_]+", "", text)  # markdown ** * __ _
    text = text.replace('"', " ").replace("\u201c", " ").replace("\u201d", " ")  # VO quotes
    return re.sub(r"\s+", " ", text).strip()


def _caption(script: str) -> str:
    stripped = " ".join(script.split())
    return stripped[:120] if stripped else "Science news"


def prepare(ctx: Context) -> dict:
    sources_map: dict[str, list] = {}
    n = ctx.video_count
    with ctx.step("choose-subjects", inputs={"count": n}) as step:
        if not step.cached:
            raw = list(agents.research(_research_query(strict=True)))
            pool = _allowlist_filter(raw)
            if len(pool) < n:
                broad_raw = list(agents.research(_research_query(strict=False)))
                raw = _dedupe_sources_by_url(raw + broad_raw)
                pool = _dedupe_sources_by_url(pool + _allowlist_filter(broad_raw))
            if not pool:
                if ctx.dry_run:
                    pool = raw
                else:
                    raise RuntimeError(
                        "No research sources matched the science-news allowlist; "
                        "cannot choose subjects."
                    )
            stored_used: list[str] = []
            if ctx.library is not None:
                raw_used = ctx.library.value("used-subjects")
                if isinstance(raw_used, list):
                    stored_used = [str(x) for x in raw_used]
            used = set(stored_used)
            prompt_pool = pool[:_POOL_PROMPT_LIMIT]
            pool_lines: list[str] = []
            for s in prompt_pool:
                title = str(s.get("title", ""))[:_POOL_TEXT_TITLE_MAX]
                snippet = str(s.get("snippet", ""))[:_POOL_TEXT_SNIPPET_MAX]
                pool_lines.append(f"- {title}: {snippet}")
            pool_text = "\n".join(pool_lines)
            used_text = ", ".join(sorted(used)) if used else "(none)"
            picker_prompt = "\n".join(
                [
                    "Rank and select the most captivating science-news subjects for short "
                    "vertical videos aimed at a lay audience. Entertainment value comes first.",
                    f"Pick up to {n} distinct subjects from the pool below. Do not reuse any "
                    "subject already used in prior runs.",
                    "",
                    "Already used (forbidden):",
                    used_text,
                    "",
                    "Research pool:",
                    pool_text,
                ]
            )
            llm_result = agents.llm(
                picker_prompt,
                agent="subject-picker",
                model=_LLM_MODEL,
                schema=_SUBJECT_PICKER_SCHEMA,
            )
            picked = llm_result.get("subjects", [])
            if not isinstance(picked, list):
                picked = []
            chosen = _finalize_subject_list(picked, pool, used, n)
            if ctx.library is not None:
                merged: list[str] = []
                seen_merge: set[str] = set()
                for item in stored_used + chosen:
                    if item in seen_merge:
                        continue
                    seen_merge.add(item)
                    merged.append(item)
                if len(merged) > _USED_SUBJECTS_CAP:
                    merged = merged[-_USED_SUBJECTS_CAP:]
                ctx.library.put(
                    "used-subjects",
                    merged,
                    kind="value",
                )
            sources_map = _build_sources_map(chosen, pool)
            step.set(chosen)
    return {"subjects": step.value, "sources": sources_map}


def run(ctx: Context) -> Result:
    subject = ctx.shared["subjects"][ctx.video_index - 1]
    voice = ctx.voice

    with ctx.step(
        "script",
        inputs={"subject": subject, "variant": ctx.video_index, "duration": _DURATION_S},
    ) as step:
        if not step.cached:
            step.set(
                agents.llm(
                    f"Write only the spoken narration for a {_DURATION_S}-second "
                    f"short-form sensational science news video about {subject}. "
                    "Output plain sentences to be read aloud — no scene directions, "
                    "no bracketed stage cues, no speaker labels or 'voice-over', "
                    "no markdown, no quotation marks. Just the words the narrator says.",
                    agent="scriptwriter",
                    model=_LLM_MODEL,
                )
            )
    script = step.value
    narration = _narration_text(script)

    with ctx.step("speech", inputs={"script": narration, "voice": voice}) as step:
        if not step.cached:
            step.set(media.speech.speak(narration, voice=voice, model=_TTS_MODEL))
    speech = step.value

    html = _composition_html(narration, speech["timings"], media.graphics.safe_zone_css())
    with ctx.step("render", inputs={"html": html}) as step:
        if not step.cached:
            step.set(media.graphics.render(html, duration_s=speech["duration"]))
    visual = step.value

    captions = media.graphics.captions(speech["audio"], speech["timings"], style="bold")
    final = media.finalize(visual, audio=speech["audio"], captions=captions)
    return Result(
        video=ctx.video_dir / final,
        caption=_caption(narration),
        description="",
    )
