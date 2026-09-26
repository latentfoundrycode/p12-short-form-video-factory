# TASK-SSN-C1-r2 — Fix broken smart-quote stripping in the narration cleaner

Review A found a real regression in `workflows/sensational-science-news/main.py`: in `_narration_text`, the copied smart-quote stripping was converted to straight quotes, producing an accidental `"""` triple-quoted string, so curly/smart quotes ("" "") are no longer stripped and leak into the narration handed to `media.speech.speak`. Fix ONLY `workflows/sensational-science-news/main.py`. Make the supervisor-authored frozen test green without editing it: `tests/registry/test_ssn_workflow.py::test_narration_cleaning_strips_quotes_and_stage_directions` (currently RED). Keep the other SSN tests green.

## Fix

In `_narration_text`, restore stripping of BOTH straight and curly double quotes, written with ASCII-safe unicode escapes so the source stays ASCII:

```
text = text.replace('"', " ").replace("“", " ").replace("”", " ")
```

(`“` is the left double quotation mark, `”` the right.) Do not change any other logic in the function.

## Scope

- workflows/sensational-science-news/main.py

Do NOT modify: any test, other files, dependencies.

## Done when

- `./.venv/Scripts/python.exe -m pytest tests/registry/test_ssn_workflow.py -q` passes (incl. the narration-cleaning test).
- `./.venv/Scripts/python.exe -m ruff check workflows/sensational-science-news` and `./.venv/Scripts/python.exe -m ruff format --check .` clean.
- Print the one-line change made.
