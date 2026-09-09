def run(ctx) -> None:
    # A benign atomic run that completes without any priced work. Used to prove a DRY run bypasses
    # the atomic budget pre-flight (a dry run spends nothing, so it is never refused for budget).
    ctx.log("atomic dry preview")
    ctx.emit({"t": "result", "video": "final.mp4", "caption": "preview"})
