# TASK E-4b — records/replay: run-record detail on the run view (§5.8, §8.6)

## Goal (one sentence)
When a run is terminal, extend the run view to show its record — a per-video **Self-review** panel
(rendering the §5.8 `self_review`), a **Steps** summary, **Cost** meters, and an **Artifacts** list —
matching the approved mockup's run-detail (`#p-video`).

## Design source (approved mockup — build against it, it is guidance not a pixel contract)
`docs/SFVF_UI_Mockup.html`, the `#p-video` run-detail pseudo-view. The panels this task implements:
- **Self-review** (mockup lines ~1256-1265): a panel headed "Self-review" with a pass/fail pill and
  one check row per §5.8 check (file valid + duration/resolution; no black/broken frames; audio not
  silent/clipping; captions present; motion adequate / not a slideshow; composition checks).
- **Steps** (~1190-1206): a compact list of the run's steps (name, reused/gate tag, status).
- **Cost** (~1168-1175): per-meter cost tiles (value + "N without cache").
- **Artifacts** (~1241-1250): the run's files (name + size).

Applicable frozen rule: `.cursor/rules/30-frontend.mdc` (React + TypeScript; compositions are HTML,
never React). Match the existing `frontend/src/index.css` design tokens and the look of
`RunView`/`StatisticsView`; add new CSS classes (check rows, meters, steps, artifact rows) in
`index.css` consistent with the mockup and the existing tokens.

## Data (all already available — no backend change)
- `RunDetail.video_records[]` (from `fetchRun`) — each `VideoRecord` has `self_review`, `cost`,
  `status`, `index`. `self_review` shape (E-3), or `null` if the run emitted none:
  ```
  { passed: bool,
    structural: { duration_s: number, width: number, height: number,
                  has_audio: bool, has_captions: bool },
    content: { black, silent, clipping, slideshow: bool,
               audio_mean_dbfs: number|null, audio_peak_dbfs: number|null,
               motion_score: number } | null,   // null on a dry run (content review skipped)
    composition: { checked: number, violations: [{kind: string, detail: string}] },
    failures: string[] }
  ```
- Steps: the SSE event stream `RunView` already consumes — the `step` events (`{t:"step", name,
  key, label, status}`). For a terminal run the stream replays all of them. Build the Steps summary
  from the `step` events already in component state.
- `cost`: `VideoRecord.cost` = `{ uncached: {meter: number}, actual?: {meter: number} }`.
- Artifacts: add `fetchRunFiles(workflowId, runId)` to `api.ts` calling `GET
  /api/workflows/{id}/runs/{runId}/files` → `{files: [{path: string, size: number}]}` (E-4a). Add a
  `RunFile`/`RunFiles` type in `types.ts`. Group files by their leading `NN/` video-index segment for
  the per-video Artifacts list; a file with no video prefix is a run-level artifact.

## Self-review → check-row mapping (render exactly this)
Per video, a panel titled "Self-review · #{index}" with a pill: **Passed** (`pill done`) when
`self_review.passed`, else **Failed** (`pill fail`). Rows (each with a ✓/✗/– state icon):
- **File valid** — always ✓ when a `self_review` exists; text `{duration_s}s · {width}×{height}`.
- **No black or broken frames** — ✓ when `content && !content.black`; ✗ when `content.black`; **–
  "not checked (dry run)"** when `content === null`.
- **Audio** — when `structural.has_audio`: ✓ when `content && !content.silent && !content.clipping`
  (text e.g. `mean {audio_mean_dbfs} dBFS · no clipping`), ✗ otherwise; when `!has_audio`, show –
  "no audio track". `content === null` → – "not checked (dry run)".
- **Captions** — ✓ "present" when `structural.has_captions`, else – "none".
- **Motion / slideshow** — ✓ "not a slideshow" when `content && !content.slideshow` (text `motion
  {motion_score}`), the slideshow verdict when `content.slideshow` (recorded, shown as an info –,
  NOT a ✗ — per E-1 it is not a hard failure), – "not checked (dry run)" when `content === null`.
- **Composition** — only when `composition.checked > 0`: ✓ "{checked} checked, no issues" when no
  violations; one ✗ row per violation `{kind}: {detail}` otherwise.
- If `self_review.failures` is non-empty, show them beneath the rows as the reasons the video failed.
A video whose `self_review` is `null` shows the panel with a muted "No self-review recorded" note.

## Where it renders
In `RunView` (`frontend/src/components/RunView.tsx`), when `isTerminalStatus(run.status)`: render the
record panels (Self-review per video, Steps, Cost, Artifacts) in place of — or below — the live feed.
While the run is not terminal, keep the current live-progress layout unchanged. You may extract a
`RunRecord`/`RunRecordView` sub-component under `frontend/src/components/` for the panels; keep
`RunView`'s existing live behavior intact. Fetch the files listing once when the run is terminal.

## Out of scope (do NOT build — later increment E-4c)
Player/replay controls, the "Replay run" action, past-run list navigation (browsing a workflow's
history), and the Decisions / Instructions-in-force panels. Do not add a router or new tab.

## Constraints / do-nots
- Frontend only. Do NOT change any backend file, `app/`, `sdk/`, or any API. Do NOT add a
  dependency (no test runner, no router, no chart lib). Do NOT edit the mockup or any doc.
- Keep `npm --prefix frontend run typecheck`, `npm --prefix frontend run lint`, and
  `npm --prefix frontend run build` all clean. Type the `self_review` access defensively (it is
  `Record<string, unknown> | null`); narrow with small typed helpers rather than `any`.

## Scope
- `frontend/src/`

## Verify (from the worktree)
- `npm --prefix frontend run typecheck` → clean.
- `npm --prefix frontend run lint` → clean.
- `npm --prefix frontend run build` → succeeds.
- (Python is unaffected; the supervisor runs the full pytest gate and in-browser verification.)
