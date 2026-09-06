# Create and Validate .github/copilot-instructions.md and AGENTS.md

> Auto-generated learner guide. This module did not complete — see the failure banner below.

## ⚠ This module did not complete

Code needs fixing, but code author budget exhausted.

No `lesson.ipynb` was produced. See `FAILED.md` for what was refused or missing, `SUMMARY.md` for the full pipeline log, and any `lesson_notebook_v*.ipynb` files in this directory for what was attempted.

## What this teaches

- Produce .github/copilot-instructions.md containing purpose, scope, coding conventions, examples, security constraints, and escalation guidance tailored to a Python repo.
- Produce AGENTS.md with agent personas, responsibilities, allowed/forbidden actions, task templates, sample interactions, and explicit sensitive-data boundaries.
- Encode repository-specific conventions (package layout, import style, typing expectations, test commands, CI hooks) into these documents with before/after examples.
- Implement and run a small Python validation script in the repo that programmatically checks file existence, required headings, examples, forbidden patterns, and basic Markdown sanity; iterate until validation passes and commit changes.

## Who this is for

Kevin: Junior Data Scientist and AI Engineer — Rudimentary experience with Python and machine learning. Transitioning from data science to AI engineering, 
with a focus on deep learning and model deployment.


## Environment setup

- Jupyter Notebook running locally and a local clone of the target repository with write access and git configured.
- Python 3.8+ (standard library used only).
- Notebook will call git via subprocess; ensure git is on PATH.

requirements

_This lesson needs no third-party packages._

## How to run

1. Create and activate a virtual environment:
   ```bash
   python -m venv .venv
   source .venv/bin/activate      # Windows: .venv\Scripts\activate
   ```
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Register this environment as a Jupyter kernel so your editor can find it:
   ```bash
   python -m ipykernel install --user --name create-and-validate-github-copilot-instr --display-name "Python (create-and-validate-github-copilot-instr)"
   ```
4. There is no `lesson.ipynb` for this module (see the failure banner above) — inspect the raw `lesson_notebook_v*.ipynb` attempts instead, selecting the `Python (create-and-validate-github-copilot-instr)` kernel if you open one.

## If the kernel doesn't show up

A newly registered kernel only appears after the editor rescans:
- **VS Code:** run *Developer: Reload Window*, then re-open the kernel picker (or pick the interpreter at `.venv/bin/python` directly).
- **Jupyter:** restart the `jupyter notebook`/Lab server.
You can confirm it was registered with `jupyter kernelspec list` (look for `create-and-validate-github-copilot-instr`).
