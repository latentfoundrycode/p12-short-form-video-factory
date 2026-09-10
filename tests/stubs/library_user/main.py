def run(ctx) -> None:
    # Uses ctx.library, which the supervisor wires (D-3c): writes a file into the library under the
    # declared namespace with a declared facet. In a dry run this lands in the discarded overlay.
    art = ctx.video_dir / "sheet.png"
    art.write_bytes(b"BERTIE-PIXELS")
    ctx.library.put("char/bertie", art, kind="image", facets={"subject": "bertie"})
    ctx.emit({"t": "result", "video": "final.mp4", "caption": "ok"})
