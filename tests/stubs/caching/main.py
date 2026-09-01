def run(ctx) -> None:
    ctx.emit(
        {
            "t": "identity",
            "workflow_id": ctx.workflow_id,
            "workflow_version": ctx.workflow_version,
            "run_id": ctx.run_id,
            "video_index": ctx.video_index,
            "video_count": ctx.video_count,
            "dry_run": ctx.dry_run,
            "step_concurrency": ctx.step_concurrency,
            "video_dir": str(ctx.video_dir),
            "shared_dir": str(ctx.shared_dir),
            "workflow_dir": str(ctx.workflow_dir),
        }
    )
    ctx.decision(kind="model", chosen="alpha", alternatives=["beta"], reason="unit test")
    with ctx.step("compute", inputs={"index": ctx.video_index}) as step:
        if not step.cached:
            ctx.log("computing-body")
            step.set({"index": ctx.video_index})
    ctx.emit({"t": "result", "video": "final.mp4", "caption": "hi"})
