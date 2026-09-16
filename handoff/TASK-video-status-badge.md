# TASK — per-video status badge in the run Video panel

## Goal (one sentence)
Show each video's status as a pill next to its `#index`, and when it failed self-review, show the
reason — so a video that is playable but failed the quality gate is clearly labelled rather than
looking like an unexplained failure.

## Why
When a run produces several videos, one can render a playable `final.mp4` yet be marked `failed`
because it failed self-review (e.g. audio clipping). Today the Video panel shows only `#index` and
the player, so the user can't tell why a playable video "failed" or that the failure is a
self-review verdict. Add a badge + reason.

## Background (already in the data — no backend change)
Each `VideoRecord` (`frontend/src/types.ts`) has `status: VideoStatus`
(`"pending" | "running" | "complete" | "failed" | "stopped"`) and an optional
`self_review?: Record<string, unknown> | null`. The self-review payload, when present, carries
`passed: boolean` and `failures: string[]` (names of hard failures; empty when it passed).

## What to change — `frontend/src/components/VideoPanel.tsx` only
For each video, in the `.field` header row that currently shows `<div className="eyebrow">#{index}</div>`:
1. Keep the `#index` eyebrow, and next to it render a status pill:
   `<span className={\`pill ${pillClass(video.status)}\`}>{video.status}</span>`
   where `pillClass` maps: `complete → "done"`, `failed → "fail"`, `stopped → "warn"`,
   `running → "run"`, `pending → "idle"` (these `.pill.*` classes already exist in `index.css`).
   Put the eyebrow + pill in a small flex row (reuse an existing row class if one fits, else a
   `<div className="video-head">` with a tiny new CSS rule `display:flex; gap:8px; align-items:center;`
   added to `index.css` using existing variables).
2. Below the header, when the video has a self-review that did NOT pass, render a `.form-error`-style
   note naming the failures, e.g. `Self-review failed: audio_clipping, silent_audio`. Parse defensively:
   read `self_review` only if it is a non-null object; treat `passed === false` as failed; render the
   `failures` array joined by ", " when it is an array of strings, else a generic
   "Self-review did not pass." Do NOT show anything when there is no self-review or it passed.
   Use a small helper, e.g.:
   ```ts
   function selfReviewFailure(sr: Record<string, unknown> | null | undefined): string | null {
     if (!sr || typeof sr !== "object") return null;
     if (sr.passed !== false) return null;
     const failures = Array.isArray(sr.failures)
       ? sr.failures.filter((f): f is string => typeof f === "string")
       : [];
     return failures.length > 0
       ? `Self-review failed: ${failures.join(", ")}`
       : "Self-review did not pass.";
   }
   ```
   Render it as `<div className="page-note video-review-fail">{msg}</div>` (add a tiny CSS rule
   `.video-review-fail { color: var(--red); }` if you want it to read as a warning; keep it subtle).

The existing player and "No video file" fallback stay exactly as they are — the badge/reason are
additive to the `.field` header, and a failed-self-review video must STILL show its player (it is
playable).

## Constraints / do-nots
- Touch ONLY `frontend/src/components/VideoPanel.tsx` and (for the tiny rules) `frontend/src/index.css`.
- Do NOT write into `app/web/` or touch `app/web/.gitkeep`; do not commit built assets.
- No `any`; keep the React 19 idiom. Keep `npm run lint` / `npm run typecheck` clean.

## Scope
- `frontend/src/components/VideoPanel.tsx`
- `frontend/src/index.css`

## Verify (from the worktree)
- `cd frontend && npm run lint` → clean.
- `cd frontend && npm run typecheck` → clean.
- `cd frontend && npm run build` → succeeds (do NOT commit the `app/web/` output).
- `cd frontend && npm run format:check` / `npm run stylelint` → fix anything your new lines flag
  (pre-existing failures on RunRecordView.tsx / VideoPanel.tsx from prettier are not blocking, but do
  keep your VideoPanel.tsx edits prettier-clean).
