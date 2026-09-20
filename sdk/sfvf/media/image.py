from __future__ import annotations

import importlib

from .._ffmpeg import solid_image
from .._runtime import current_context
from ..providers import CapabilityError, resolve
from .graphics import _artifact, _sha8

_EXT = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}
_DEFAULT_W = _DEFAULT_H = 1024


def generate(
    prompt: str,
    *,
    model: str,
    refs: list[dict[str, str]] | None = None,
    size: str | None = None,
) -> str:
    ctx = current_context()
    stem = _sha8(["image.generate", prompt, model, refs, size])
    if ctx.dry_run:
        dest, rel = _artifact(ctx, f"image-{stem}.png")
        solid_image(dest, width=_DEFAULT_W, height=_DEFAULT_H)
        return rel
    provider, mdl = resolve(model)
    if mdl.kind != "image" or "image.generate" not in mdl.capabilities:
        raise CapabilityError(f"model {model!r} cannot generate images")
    secrets = {name: ctx.secret(name) for name in provider.secret_names}
    adapter = importlib.import_module(f"sfvf.providers.{provider.adapter}")
    price = adapter.image_price(mdl, size)
    with ctx._budget_reserved(provider.meter, provider.unit, estimate=price) as token:
        out = adapter.generate(prompt, model=mdl, provider=provider, size=size, secrets=secrets)
    # paid call returned (provider billed) -> reconcile the KNOWN cost before any filesystem write:
    ctx.record_cost(provider.meter, provider.unit, price, "priced", token=token)
    dest, rel = _artifact(ctx, f"image-{stem}.{_EXT.get(out.media_type, 'png')}")
    dest.write_bytes(out.data)
    return rel


def edit(
    image: str,
    prompt: str,
    *,
    model: str,
    refs: list[dict[str, str]] | None = None,
) -> str:
    ctx = current_context()
    stem = _sha8(["image.edit", image, prompt, model, refs])
    if ctx.dry_run:
        dest, rel = _artifact(ctx, f"image-{stem}.png")
        solid_image(dest, width=_DEFAULT_W, height=_DEFAULT_H)
        return rel
    provider, mdl = resolve(model)
    if mdl.kind != "image" or "image.edit" not in mdl.capabilities:
        raise CapabilityError(f"model {model!r} cannot edit images")
    secrets = {name: ctx.secret(name) for name in provider.secret_names}
    image_bytes = (ctx.paths.video / image).read_bytes()
    refs_bytes = [(ctx.paths.video / ref["path"]).read_bytes() for ref in (refs or [])]
    adapter = importlib.import_module(f"sfvf.providers.{provider.adapter}")
    price = adapter.image_price(mdl, None)
    with ctx._budget_reserved(provider.meter, provider.unit, estimate=price) as token:
        out = adapter.edit(
            image_bytes,
            prompt,
            model=mdl,
            provider=provider,
            size=None,
            refs_bytes=refs_bytes,
            secrets=secrets,
        )
    ctx.record_cost(provider.meter, provider.unit, price, "priced", token=token)
    dest, rel = _artifact(ctx, f"image-{stem}.{_EXT.get(out.media_type, 'png')}")
    dest.write_bytes(out.data)
    return rel
