# TASK F3-4/F3-5 — launch preflight: disk-space + missing key/program blocks

Satisfies R-036 (+R-072/R-158 refuse threshold) and R-034, PRD §8.2. RED-first:
tests/api/test_launch_preflight.py has 3 RED refuse-tests. Do NOT edit tests.

## Where (app/api/runs.py `launch_run`, alongside `_unconfigured_model_param`, BEFORE `admit_run`)
Add these admission checks after resolving the workflow entry and before spawning the run. Each raises
`HTTPException(status_code=422, detail=<specific message>)` so nothing is launched (frozen tests assert
`run_request` is never called on a refusal). `shutil` is already imported in runs.py.

1. **Disk (R-036):** `if shutil.disk_usage(_runs_dir(request)).free < 5 * 1024**3:` -> 422 with a message
   naming disk/space (e.g. "Not enough free disk space to start a run (need at least 5 GB)."). Use the
   runs dir (its drive is where output lands). Wrap in try/except OSError -> treat an unreadable path as
   not blocking (do not 500).

2. **Missing required key (R-034):** for each `entry.manifest.requires_keys` (list of RequiresKey with
   `.name`), if its name is NOT in the configured secret names
   (`app.api.workflows.configured_secret_names(_secrets(request))` — non-blank values only), raise 422
   naming the missing key (include the exact key name, e.g. "FOO_API_KEY"). Skip when manifest is None.

3. **Missing required program (R-034):** for each name in `entry.manifest.workflow.requires_binaries`,
   if `shutil.which(name) is None`, raise 422 naming the program.

Order among the three is your choice; all must run before `admit_run`. Keep the existing
`_unconfigured_model_param` check.

## Notes
- Provider-balance (R-035) is NOT in scope (no balance API; deferred pending owner decision). The
  20 GB "warn" (non-refuse) is display-only and out of scope here (this is the launch REFUSE).
- Do not change admit_run/run_request.

## Done when
- `./.venv/Scripts/python.exe -m pytest tests/api/test_launch_preflight.py -q` passes (all 5).
- Full tests/api + tests/core still pass (only the 2 pre-existing httpx `..`-path failures; supervisor
  timing tests may flake under CPU load).
- `ruff check .`, `ruff format --check .`, `mypy` clean. Frozen test unmodified.
- End with an `Assumed, not verified` list (or `none`).
