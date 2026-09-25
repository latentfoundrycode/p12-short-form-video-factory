# TASK-SSN-A7-r3 — Focus management for the tag-chip keyboard edit path

A7-r2 is otherwise accepted; the design-auditor found ONE remaining BLOCKING accessibility defect in the Mood/Energy tag input, plus one related advisory. Fix both in `frontend/src/components/LibraryView.tsx` only. Do NOT touch anything else, do NOT edit the frozen test, do NOT run `npm run build`.

## The defect (BLOCKING)

In the `TagInput` component, pressing Enter/F2 on a focused chip enters edit mode: the chip `<span>` (React key `chip-<i>-<tag>`) unmounts and an `<input className="chip-edit">` (key `edit-<i>`) mounts in its place. Nothing moves focus into that input, so focus falls to `document.body` and a keyboard/AT user cannot type without tabbing back in. See `LibraryView.tsx` around lines 140-155 (the `editingIndex === index` branch) and `startEdit` around line 104.

A supervisor-authored frozen test now pins the contract (`frontend/src/components/LibraryView.test.tsx`, the test "entering edit mode moves focus into the edit input"): it focuses the "wonder" chip, presses `{F2}`, and asserts `document.activeElement` is the edit `<input>` with value `"wonder"`. It is currently RED. Do NOT edit this test.

## Fix

- When edit mode is entered, move focus into the `chip-edit` input and select its contents (mirroring the mockup's `inp.focus(); inp.select();` in `docs/mockups/library-tab.html`). Use a ref focused in an effect keyed on `editingIndex` (a bare `autoFocus` alone will focus but not select; either add a small effect that focuses + selects, or `autoFocus` plus `onFocus={e => e.currentTarget.select()}`). It must work when edit mode is entered by keyboard (F2/Enter), right-click menu "Edit", and any other entry point.

## Advisory (fix in the same round — same component, same defect class)

- When the chip right-click context menu closes (Escape or outside click), return focus to the chip it was opened from, instead of dropping focus to `document.body`. See the `chipMenu` effect around lines 86-98. Track the originating chip (e.g. a ref, or focus the chip by index on close) and restore focus to it when the menu closes. Keep the existing Escape-to-close behaviour.

## Scope

- frontend/src/components/LibraryView.tsx

Do NOT modify: the frozen tests, `frontend/src/index.css` (no styling change needed), any other frontend file, `docs/`, `handoff/`, dependencies. Do NOT run `npm run build`.

## Constraints

- Workspace boundary; one paragraph is one line in Markdown.
- Record any tooling friction / defect in `docs/BUILDER_NOTES.md`.

## Done when

- `npm --prefix frontend run test` — all LibraryView.test.tsx tests pass, including the two accessibility tests (keyboard delete + keyboard-edit focus), with no `console.error`.
- `npm --prefix frontend run lint` and `npm --prefix frontend run typecheck` clean.
- Print the file(s) you changed and a one-paragraph summary.
