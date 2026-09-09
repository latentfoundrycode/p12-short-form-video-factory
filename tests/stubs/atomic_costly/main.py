def run(ctx) -> None:
    # An atomic run whose pre-flight should refuse it before any work — so this must never execute.
    raise AssertionError("atomic pre-flight should have refused this run before it started")
