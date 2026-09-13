# TASK G-2 fixes — accessible labels for the judgement textareas (design-auditor BLOCKING)

## Why
design-auditor BLOCKING: each answer `<textarea className="ta">` has no accessible name — the
`<div className="factor-q">` question is only a visual sibling. The house pattern
(`frontend/src/components/RunLaunchForm.tsx`) wraps every control in a `<label>`, so its controls are
named; QualityPanel regresses from that. With many videos × factors, a screen-reader user cannot tell
which question a textarea belongs to. Also addressed: the "Video NN" section heading reuses `.factor-q`
so it is indistinguishable from the questions (design-auditor advisory), and `.factor` is used for both
the per-video wrapper and each factor (double-use advisory).

## Scope
- `frontend/src/components/QualityPanel.tsx`
- `frontend/src/index.css`

## Exact change
In `QualityPanel.tsx`, restructure each video block's JSX so:
1. The per-video wrapper is `<div className="q-video" key={draft.index}>` (NOT `.factor`).
2. The "Video NN" heading is `<div className="eyebrow">{videoLabel(draft.index)}</div>` (the existing
   mono/uppercase eyebrow class — visually distinct from the questions).
3. Each factor becomes a `<label className="factor" key={factor.key}>` that WRAPS both the question and
   the textarea, so the textarea is implicitly labelled:
   ```tsx
   <label className="factor" key={factor.key}>
     <span className="factor-q">{factor.question}</span>
     <textarea
       className="ta"
       value={draft.answers[factor.key] ?? ""}
       disabled={submitting}
       onChange={(e) => { setAnswer(draft.index, factor.key, e.target.value); }}
     />
   </label>
   ```
   (`.factor-q` was a `<div>`; making it a `<span>` inside the label is fine — the class styling is
   unchanged. A `<label>` wrapping the textarea gives it its accessible name from the question text.)
Keep the verdict row exactly as is (the two buttons already have `aria-pressed`). Do not change any
logic (drafts, collectSubmission, submit, toggleVerdict), only the JSX structure above.

In `frontend/src/index.css`, add one rule so per-video blocks stay separated now that the wrapper is
no longer `.factor`:
```css
.q-video {
  margin-bottom: 22px;
}
```
(Place it near the ported `.factor` rules. Only add; do not restyle existing rules.)

## Verify (from the worktree)
- `cd frontend && npm run build && npm run lint && npm run stylelint` → all clean.
- Prettier: `npx prettier --check src/components/QualityPanel.tsx src/index.css` → clean (run
  `npx prettier --write` on those two if needed).
