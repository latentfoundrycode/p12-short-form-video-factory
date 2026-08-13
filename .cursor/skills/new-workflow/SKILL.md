---
name: new-workflow
description: scaffold a new workflow plug-in. Use when adding a workflow to workflows/.
paths: workflows/**
---

# New workflow

Scaffold under `workflows/<id>/`. Contract: `docs/SFVF_Workflow_SDK.md`.

A workflow never writes into its own folder at runtime. All output goes to `runs/`.

## Folder contents (SDK §1)

- `workflow.toml` — required; the manifest; no logic
- `requirements.txt` — required; may be empty. Never add a dependency without being asked.
- `main.py` — required; the entry point
- `criteria/` — what "good" means, for learning
- `rules/` — instructions for this workflow's agents
- `skills/` — on-demand reference for this workflow's agents
- `stubs/` — optional; dry-run stand-ins only this workflow needs

Do not import from other workflows. Reusable assets belong in the library, not here.

## Manifest (SDK §2)

`[workflow]`: `id` (must equal the folder name; permanent), `name` (display; changeable), `version` (bump when behaviour changes), `description`, `entrypoint` (`main:run`), optional `prepare`, `python` (`3.12`), `sdk`. See §2.6 for `video_semantics` / `max_videos`, §2.6a for `atomic` / `safety_factor`.

Also: `requires_binaries`, `requires_capabilities` (§2.9), `[[requires_keys]]`, `[[requires_connections]]`.

`[output]` — aspect, fps, safe_zone (§2.7). `[library]` and `[[library.facets]]` (§7). `[[limits]]` per family; silence, not elapsed time (§2.8). `[[params]]` (§2.2–2.4; never declare chassis-owned settings). `[[recovery]]` names a family (§2.5). `[[quality_factors]]` — specific questions (§9).

## Entry points (SDK §3)

`run(ctx) -> Result` is required (once per video). `prepare(ctx) -> dict` is optional (once per request). End with `finalize()` (§6.9).
