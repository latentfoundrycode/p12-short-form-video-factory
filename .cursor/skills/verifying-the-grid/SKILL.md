---
name: verifying-the-grid
description: Acceptance checklist for the Stage 1 workflow grid. Use when reviewing or verifying the Main tab, workflow cards, rescan, or the live frontend against the mockup.
---

# Verifying the grid

Concrete acceptance checklist for the Workflows view. `docs/SFVF_UI_Mockup.html` is the visual spec. The grid is fed by `GET /api/workflows` and `POST /api/workflows/rescan`.

## Data and order

- [ ] Renders from the live API in folder order (the order `GET /api/workflows` returns).
- [ ] Title uses `name`, falling back to `id` when `name` is null.
- [ ] Description is shown when present.
- [ ] Thumbnail uses `thumbnail_url` when set, with an empty-thumb placeholder when null or when the image fails to load. No mock gradient thumb classes on real workflows.

## Card treatments

- [ ] Valid, no warnings: neutral "Idle" pill; "Run workflow" is present and DISABLED.
- [ ] Valid, with warning(s): Idle + disabled Run, plus an amber warning badge/message (e.g. `sdk_version_mismatch`).
- [ ] Invalid (any error-severity problem): "Broken" treatment using the mockup's error visual language (red border/pill), no run action, and the list of problem messages shown.

## Empty, loading, and error

- [ ] Empty, loading, and error states: empty grid references `workflows/`; loading is indicated; a fetch failure states what happened (never fabricated data) and offers retry.

## Rescan

- [ ] Rescan updates the grid: "Rescan folder" calls `POST /api/workflows/rescan` and replaces the cards with the response. The button is disabled while in flight.

## Accessibility and layout

- [ ] Keyboard focus visible (`:focus-visible`).
- [ ] Reduced motion respected (`prefers-reduced-motion`).
- [ ] Grid collapses on a narrow viewport (`auto-fill` / `minmax(400px, 1fr)`).
- [ ] Tokens and type match the mockup (Space Grotesk, IBM Plex Sans, IBM Plex Mono; mockup `:root` colours).

## Out of scope for this view

Do not expect meters, cost, run progress, Schedule/Learning/Statistics/Settings content, or a working Run action.
