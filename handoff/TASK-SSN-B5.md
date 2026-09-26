# TASK-SSN-B5 — Per-video description (via the existing result record field)

Add an optional per-video `description` to a workflow's `Result`, carry it through the runner's result event (which the supervisor already captures verbatim into `VideoRecord.result`), and surface it READ-ONLY in the run view. No new top-level record field (delta C1) — it rides in `result`. Make the supervisor-authored frozen tests green WITHOUT editing them:
- `tests/sdk/test_result.py` (description default/carry + `_result_event` includes when set, omits when empty)
- `frontend/src/components/VideoDescription.test.tsx` (the read-only run-view display)
Keep all existing result/runner tests and frontend tests green.

## Part 1 — SDK

- `sdk/sfvf/result.py`: add a field `description: str = ""` to the `Result` dataclass (after `extra`, so it stays keyword-friendly; it is a plain str defaulting to empty).
- `sdk/sfvf/runner.py` `_result_event(...)`: after the existing `notes`/`extra` handling, add `if result.description: event["description"] = result.description` — include it ONLY when non-empty (matching the other optional fields). Nothing else in the runner changes; the supervisor already copies every non-`t` key of the result event into `VideoRecord.result`, so `result.description` reaches `VideoRecord.result["description"]` with no app/core change.

## Part 2 — frontend (`frontend/src/components/RunRecordView.tsx`)

- Add and EXPORT a small component:
  ```
  export function VideoDescription({ video }: { video: VideoRecord }) { ... }
  ```
  It reads `video.result?.description`. When that is a non-empty string, render a read-only block: a small label containing the word "Description" (e.g. an `.eyebrow`/`.field-label`-style label) plus the description text, using the existing per-video panel styling/tokens (no new colours, no restyling of other views). When there is no result or the description is empty/missing/not a string, render `null` (nothing) — never render "undefined"/"NaN". No `console.error`.
- Render `<VideoDescription video={video} />` per video in the run view, in the same per-video map where `SelfReviewPanel` is rendered (~line 761), so each video shows its description read-only.
- `frontend/src/types.ts` needs NO change (`VideoRecord.result` is already `Record<string, unknown> | null`).

## Scope

- sdk/sfvf/result.py
- sdk/sfvf/runner.py
- frontend/src/components/RunRecordView.tsx

Do NOT modify: any test, `app/`, other frontend files, `docs/`, `handoff/`, dependencies. Do NOT run `npm run build`.

## Constraints

- Workspace boundary; ASCII in Python; one paragraph is one line in Markdown. Additive only. Record any tooling friction / defect in `docs/BUILDER_NOTES.md`.

## Done when

- `./.venv/Scripts/python.exe -m pytest tests/sdk/test_result.py -q` passes.
- `npm --prefix frontend run test -- --run src/components/VideoDescription.test.tsx` passes, and `npm --prefix frontend run test -- --run` (full) stays green.
- `./.venv/Scripts/python.exe -m ruff check sdk/sfvf/result.py sdk/sfvf/runner.py`, `./.venv/Scripts/python.exe -m ruff format --check .`, project `./.venv/Scripts/python.exe -m mypy` (only the pre-existing PIL error), `npm --prefix frontend run lint`, and `npm --prefix frontend run typecheck` all clean.
- Print the files you changed and a one-paragraph summary.
