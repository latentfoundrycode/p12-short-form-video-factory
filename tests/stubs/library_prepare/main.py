def prepare(ctx):
    # The documented place to provision library assets (§7.5). In prepare, video_dir is the shared
    # dir. In a dry run this write lands in the per-run overlay shared with run().
    art = ctx.video_dir / "hero.png"
    art.write_bytes(b"HERO-PIXELS")
    ctx.library.put("char/hero", art, kind="image", facets={"subject": "hero"})
    return {}


def run(ctx) -> None:
    # run() must see the asset provisioned in prepare() — the overlay is shared across the request.
    found = ctx.library.find(facets={"subject": "hero"})
    if not found:
        raise AssertionError("prepare-provisioned asset was not visible to run()")
    ctx.emit({"t": "result", "video": "final.mp4", "caption": "ok"})
