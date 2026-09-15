# TASK — run-record video player + two-column layout (Frontend §6)

## Goal (one sentence)
On a completed run's record, show the run's video(s) in a **playable** panel at the top of a **right**
column, with the **Your judgement** panel beneath it, and move every other panel into a **left**
column.

## Why
Right now the run record lists artifacts as filenames only — there is no way to watch the video, and
the judgement panel is buried at the bottom of a mixed layout. The backend already serves the file
bytes at `GET /api/workflows/{id}/runs/{run}/files/{path}` (a `FileResponse` with the right media
type); the UI just never uses it.

## Desired layout (terminal/completed run only)
A two-column grid for the completed-run record:
- **LEFT column** (the panels that have plenty of horizontal room): **Status**, **Cost**, **Steps**,
  **Self-review**, **Artifacts** (run-level and per-video) — everything that is there today EXCEPT the
  video and the judgement.
- **RIGHT column**: **Video** panel at the TOP (playable), then the **Your judgement** panel beneath
  it.
On a narrow viewport (≤ ~960px) the two columns stack (right column below left), matching the existing
`.record-grid` responsive rule.

The live (non-terminal) run view is unchanged — this layout is for the terminal record only.

## Files in play
- `frontend/src/components/RunView.tsx` — renders the page header + the **Status** panel + (when
  terminal) `<RunRecordView>`. The Status panel markup + the Replay button + `onReplayClick`/
  `replaying`/`replayError` live here.
- `frontend/src/components/RunRecordView.tsx` — renders `CostPanel` + a `.record-grid` of
  Steps/Artifacts (left) and Self-review/Artifacts/**QualityPanel** (right). Owns `files`,
  `videoRecords`, `reload`.
- `frontend/src/api.ts`, `frontend/src/types.ts`, `frontend/src/index.css`.

## Implementation

### 1) `api.ts` — a file-URL helper
Add:
```ts
export function runFileUrl(workflowId: string, runId: string, path: string): string {
  const encPath = path.split("/").map(encodeURIComponent).join("/");
  return `/api/workflows/${encodeURIComponent(workflowId)}/runs/${encodeURIComponent(runId)}/files/${encPath}`;
}
```
(The `{path:path}` route keeps slashes; encode each segment.)

### 2) A `VideoPanel` (new component, e.g. `frontend/src/components/VideoPanel.tsx`)
Props: `workflowId: string`, `runId: string`, `videos: VideoRecord[]`, `files: RunFile[]`.
- For each video record (sorted by index), find its playable file: the entry in `files` whose path is
  that video's `final.mp4` — i.e. path `\`${videoDir}/final.mp4\`` where `videoDir` is the two-digit
  zero-padded index (reuse the SAME video-dir derivation the record view already uses to group files;
  do not hardcode "01"). Fall back to the first `.mp4` under that video's prefix if `final.mp4` is
  absent. If none, show a `page-note` "No video file for #{index}".
- Render a `.panel` titled "Video" (eyebrow). Body: for each video, a small caption (`#{index}`) and a
  `<video controls preload="metadata" src={runFileUrl(workflowId, runId, path)} />` with
  `className="run-video"`. Multiple videos stack vertically.
- Do NOT autoplay. No download attribute needed (the controls' own menu is fine).

### 3) Two-column terminal layout
Restructure so, for the terminal record, Status + Cost + Steps + Self-review + Artifacts are the LEFT
column and Video + Your judgement are the RIGHT column. Keep all existing data-fetching where it is
(`RunRecordView` keeps `files`/`videoRecords`/`reload`; `QualityPanel` keeps its props). Recommended
shape (you may choose a cleaner equivalent, but do not duplicate the Status markup):
- Extract the existing Status `.panel` from `RunView` into a small `RunStatusPanel` component (props:
  the `run`, the derived `stage`, and an `actions` ReactNode for the buttons). Use it in BOTH
  `RunView`'s non-terminal branch (with Stop/Force-stop actions, as today) and the terminal record's
  left column (with the Replay action).
- Have `RunView`'s terminal branch render `<RunRecordView ... onReplay={onReplayClick}
  replaying={replaying} replayError={replayError} />` and let `RunRecordView` build the whole terminal
  two-column layout: LEFT = `RunStatusPanel` (Replay action) + `CostPanel` + `StepsPanel` +
  per-video `SelfReviewPanel` + `ArtifactsPanel`(s); RIGHT = `VideoPanel` + `QualityPanel`.
- `CostPanel` currently renders full-width above the grid — move it into the LEFT column.
Preserve all current behaviour (replay handler, stop buttons in the live view, reload-on-save, error
lines). Do not change the live-feed (non-terminal) view other than swapping in `RunStatusPanel`.

### 4) `index.css`
Add a two-column grid for the terminal record (mirror `.record-grid`'s existing breakpoint):
```css
.run-two { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; align-items: start; }
@media (width <= 960px) { .run-two { grid-template-columns: 1fr; } }
.run-video { width: 100%; max-height: 70vh; border-radius: var(--r); background: #000; display: block; }
```
Use the existing tokens/format style; no raw colors except the video letterbox `#000` (acceptable for
a media element). Do not restyle existing selectors beyond moving Cost into the left column.

## Constraints / do-nots
- Frontend only: `RunView.tsx`, `RunRecordView.tsx`, new `VideoPanel.tsx`, `api.ts`, `types.ts` (if a
  prop type is needed), `index.css`. No Python, no `app/web/` (build output — do not commit it; restore
  `app/web/.gitkeep` if the build removes it).
- No new npm dependency. Keep accessibility (real controls; the `<video>` has native controls).
- Keep it working when `files` is still loading or a video has no mp4 (graceful `page-note`).

## Verify (from `frontend/`)
- `npm run typecheck`, `npm run lint`, `npm run stylelint` → clean.
- `npm run build` → succeeds (do not commit the emitted `app/web/`).
