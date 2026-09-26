# TASK-SSN-B5-r2 — Description panel: per-video index label + wrap long source URLs

Two small design-auditor polish items on the B5 `VideoDescription` panel (the read-only per-video description in the run view). The descriptions carry sources/URLs, so these matter for the real content. Fix in `frontend/src/components/RunRecordView.tsx` (+ `frontend/src/index.css` for the wrap rule). Make the supervisor-authored frozen test green WITHOUT editing it: `frontend/src/components/VideoDescription.test.tsx` (the header now must carry the per-video index). Keep all existing tests green. Do NOT run `npm run build`.

## Fixes

1. Per-video index in the header — the `VideoDescription` section header currently reads just "Description". Match the sibling panels (SelfReviewPanel's header is `Self-review · #{video.index}`): render the header as `Description · #{video.index}`. The frozen test asserts the header text matches `/description.*#\s*2/i` for a video with `index: 2`.

2. Wrap long tokens so a source URL cannot overflow the panel horizontally — the description text is a `<p>` that will often contain long unbroken URLs. Give that `<p>` an `overflow-wrap: anywhere` (and/or `word-break: break-word`) rule via a small class in `frontend/src/index.css` (token-consistent; do not restyle other views) applied to the description text. No inline styles.

Keep everything else about `VideoDescription` unchanged (null when no/empty description, read-only, existing tokens).

## Scope

- frontend/src/components/RunRecordView.tsx
- frontend/src/index.css

Do NOT modify: any test, backend, other files, `docs/`, `handoff/`, dependencies. Do NOT run `npm run build`.

## Done when

- `npm --prefix frontend run test -- --run src/components/VideoDescription.test.tsx` passes (incl. the index-labelled header), and `npm --prefix frontend run test -- --run` (full) stays green.
- `npm --prefix frontend run lint` and `npm --prefix frontend run typecheck` clean.
- Print the files you changed and a one-line summary.
