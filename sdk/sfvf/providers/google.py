"""Google (Vertex / Agent Platform) media adapter — SA-OAuth; Gemini image via :generateContent."""

from __future__ import annotations

import base64
import binascii
import json
import time
from typing import Any, cast

from .._ratelimit import LIMITER
from ._auth import GoogleSaAuth
from ._http import parse_json, request
from .base import AdapterError, Cost, Output
from .registry import CapabilityError

_API_VERSION = "v1"
_POLL_INTERVAL_S = 5.0  # monkeypatched to 0 in tests
_POLL_TIMEOUT_S = 1800.0


def _transport() -> Any | None:
    return None


def _client(base_url: str) -> Any:
    import httpx2

    return httpx2.Client(base_url=base_url, timeout=60.0, transport=_transport())


def _sa(secrets: dict[str, str]) -> dict[str, Any]:
    raw = secrets["GOOGLE_SA_JSON"]
    try:
        return cast(dict[str, Any], json.loads(raw))
    except json.JSONDecodeError:
        raise AdapterError("google", where="config", detail="invalid GOOGLE_SA_JSON") from None


def _auth(sa: dict[str, Any]) -> GoogleSaAuth:
    return GoogleSaAuth(sa, transport=_transport())


def _endpoint(region: str, project: str, slug: str, method: str) -> tuple[str, str]:
    """Return (base_url, path) for a publisher-model method on the regional/global Vertex host."""
    if region == "global":
        base = "https://aiplatform.googleapis.com"
    else:
        base = f"https://{region}-aiplatform.googleapis.com"
    path = (
        f"/{_API_VERSION}/projects/{project}/locations/{region}"
        f"/publishers/google/models/{slug}:{method}"
    )
    return base, path


_MAGIC = (
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"GIF8", "image/gif"),
)


def _sniff(data: bytes) -> str:
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    for magic, mime in _MAGIC:
        if data.startswith(magic):
            return mime
    return "image/png"


def _inline(data: bytes) -> dict[str, Any]:
    return {"inlineData": {"mimeType": _sniff(data), "data": base64.b64encode(data).decode()}}


def _extract_image(payload: dict[str, Any]) -> Output:
    for cand in payload.get("candidates", []):
        for part in (cand.get("content") or {}).get("parts", []):
            inline = part.get("inlineData")
            if inline and inline.get("data"):
                try:
                    raw = base64.b64decode(inline["data"])
                except (binascii.Error, ValueError):
                    raise AdapterError(
                        "google", where="generate", detail="invalid base64 image data"
                    ) from None
                return Output(data=raw, media_type=inline.get("mimeType", "image/png"))
    raise AdapterError("google", where="generate", detail="no inlineData image in response")


def image_price(model: Any, size: str | None) -> float:
    return float(model.price.amount)


def _generate_content(
    provider: Any,
    model: Any,
    parts: list[dict[str, Any]],
    secrets: dict[str, str],
) -> Output:
    sa = _sa(secrets)
    project = sa["project_id"]
    region = provider.region or "us-central1"
    base, path = _endpoint(region, project, model.slug, "generateContent")
    auth = _auth(sa)
    body = {
        "contents": {"role": "USER", "parts": parts},
        "generationConfig": {"responseModalities": ["TEXT", "IMAGE"]},
    }
    with _client(base) as client:
        resp = request(
            client,
            "POST",
            path,
            provider="google",
            auth=auth,
            limiter=LIMITER,
            json=body,
        )
        return _extract_image(parse_json(resp, provider="google", where="generate"))


def generate(
    prompt: str,
    *,
    model: Any,
    provider: Any,
    size: str | None,
    secrets: dict[str, str],
) -> Output:
    return _generate_content(provider, model, [{"text": prompt}], secrets)


def edit(
    image: bytes,
    prompt: str,
    *,
    model: Any,
    provider: Any,
    size: str | None,
    refs_bytes: list[bytes],
    secrets: dict[str, str],
) -> Output:
    parts: list[dict[str, Any]] = [{"text": prompt}, _inline(image)]
    parts.extend(_inline(ref) for ref in refs_bytes)
    return _generate_content(provider, model, parts, secrets)


def video_estimate(model: Any, duration_s: float | None, extra: dict[str, Any] | None) -> float:
    return float(model.price.amount * (duration_s or 8.0))


def _image_part_from_url(url: str) -> dict[str, Any]:
    if url.startswith("data:"):
        header, _, b64 = url.partition(",")
        mime = header[len("data:") :].split(";", 1)[0] or "application/octet-stream"
        return {"bytesBase64Encoded": b64, "mimeType": mime}
    import httpx2

    with httpx2.Client(transport=_transport()) as client:
        resp = client.get(url)
    if resp.status_code // 100 != 2:
        raise AdapterError(
            "google", status=resp.status_code, where="frame fetch", detail="frame download failed"
        )
    data = resp.content
    return {"bytesBase64Encoded": base64.b64encode(data).decode(), "mimeType": _sniff(data)}


def generate_video(
    prompt: str,
    *,
    model: Any,
    provider: Any,
    first_frame_url: str | None,
    last_frame_url: str | None,
    ref_urls: list[str],
    duration_s: float | None,
    extra: dict[str, Any] | None,
    secrets: dict[str, str],
    ctx: Any,
) -> tuple[Output, Cost]:
    if last_frame_url is not None:
        raise CapabilityError("veo does not support last-frame conditioning")
    sa = _sa(secrets)
    project = sa["project_id"]
    region = provider.region or "us-central1"
    base, submit_path = _endpoint(region, project, model.slug, "predictLongRunning")
    _, poll_path = _endpoint(region, project, model.slug, "fetchPredictOperation")
    auth = _auth(sa)
    instance: dict[str, Any] = {"prompt": prompt}
    if first_frame_url:
        instance["image"] = _image_part_from_url(first_frame_url)
    parameters: dict[str, Any] = {"sampleCount": 1, "personGeneration": "allow_adult"}
    if duration_s is not None:
        parameters["durationSeconds"] = round(duration_s)
    parameters.update(extra or {})  # aspectRatio / negativePrompt / resolution passthrough
    body = {"instances": [instance], "parameters": parameters}
    with _client(base) as client:
        submit = request(
            client,
            "POST",
            submit_path,
            provider="google",
            auth=auth,
            limiter=LIMITER,
            json=body,
        )
        name = parse_json(submit, provider="google", where="submit")["name"]
        deadline = time.monotonic() + _POLL_TIMEOUT_S
        op: dict[str, Any] = {}
        while True:
            if time.monotonic() > deadline:
                raise AdapterError("google", where="poll", detail="operation timed out")
            poll = request(
                client,
                "POST",
                poll_path,
                provider="google",
                auth=auth,
                limiter=LIMITER,
                json={"operationName": name},
            )
            op = parse_json(poll, provider="google", where="poll")
            if op.get("done"):
                break
            ctx.heartbeat("video", waiting_on="google")
            time.sleep(_POLL_INTERVAL_S)
    if "error" in op:
        raise AdapterError("google", where="poll", detail="operation failed")
    try:
        video = op["response"]["videos"][0]
        data = base64.b64decode(video["bytesBase64Encoded"])
    except (KeyError, IndexError, TypeError, binascii.Error, ValueError):
        raise AdapterError(
            "google", where="poll", detail="no inline video in operation response"
        ) from None
    amount = (duration_s or 8.0) * model.price.amount
    return Output(data=data, media_type=video.get("mimeType", "video/mp4")), Cost(
        amount=amount, source="priced"
    )
