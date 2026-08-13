# Workflows

Each subfolder is an isolated plug-in with its own `requirements.txt` and its own virtual environment under `venvs/`. Workflows must never import from each other.

The manifest schema and entry point are specified in `docs/SFVF_Workflow_SDK.md`.

Never add a dependency here without being asked.
