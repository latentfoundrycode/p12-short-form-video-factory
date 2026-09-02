from sfvf._runtime import current_context


def run(ctx):
    # The runner must make the active Context ambiently available for the
    # duration of the entrypoint, so provided functions (agents/media) can
    # reach ctx.dry_run and ctx.paths without being passed ctx explicitly.
    ambient = current_context()
    return {
        "ambient_is_ctx": ambient is ctx,
        "params_topic": ctx.params.get("topic"),
    }
