# Future: Project Mode (Multi-File Output)

## Motivation

The current pipeline is entirely built around Jupyter notebooks. Every run produces
a `.ipynb` file executed by a Jupyter kernel via `nbclient`. The `environment` field
in `LearnerProfile` accepts values like `vscode`, `cli`, and `book`, but these have
no real effect — the output is always a notebook, regardless of what is specified.

A **project mode** would generate real, runnable file trees instead of notebooks.
This enables learning experiences that mirror actual software development:
a Langfuse observability setup, a FastAPI service, a CLI tool, a test suite — built
from actual `.py` (or `.js`, `.ts`, etc.) files, not notebook cells.

## What Changes vs. the Notebook Mode

| Concern | Notebook mode (current) | Project mode (new) |
|---|---|---|
| Output format | Single `.ipynb` (nbformat JSON) | File tree: `main.py`, `config.py`, `tests/`, etc. |
| Execution | `nbclient` + Jupyter kernel | `python main.py` or `pytest` or language-specific runner |
| Failure detection | Cell raised an exception | Non-zero exit code / failed test assertions |
| Revision signal | Cell index + traceback | File path + line number + test output |
| Learner artifact | Open `.ipynb` in Jupyter | Clone/copy files, run in terminal or IDE |

## Required Architecture Changes

### 1. New artifact kind: `"project"`

`ArtifactStore` already supports arbitrary `kind` strings. A `"project"` artifact
would store a JSON-serialised file map:

```json
{
  "files": {
    "main.py": "...",
    "utils/tracer.py": "...",
    "tests/test_tracer.py": "..."
  },
  "entrypoint": "python main.py",
  "test_command": "pytest tests/"
}
```

### 2. New `CodeAuthorAgent` variant: `ProjectAuthorAgent`

Instead of asking the LLM for a cell list, this agent asks for a file tree.
The LLM response format would be a JSON map of `filename → source`, validated
and written into a project artifact.

The existing `notebook.py` module has a clean parallel:

```
notebook.py          →  project.py
build_notebook()     →  build_project()
cells_from_json()    →  files_from_json()
render_indexed()     →  render_file_tree()
```

### 3. New `ExecutorAgent` variant: `ProjectExecutorAgent`

Runs the project in a subprocess sandbox (e.g. a temp directory with the files
written out), captures stdout/stderr and exit code, and produces the same
`ExecutionReport`-compatible dict the rest of the pipeline already understands.

```python
# Rough sketch
result = subprocess.run(
    entrypoint.split(),
    cwd=project_dir,
    capture_output=True,
    timeout=60,
)
report = {
    "ok": result.returncode == 0,
    "stdout": result.stdout.decode(),
    "stderr": result.stderr.decode(),
    "failed_cells": [],  # reuse existing field or rename
    "error_summary": result.stderr.decode() if result.returncode != 0 else None,
}
```

### 4. Pipeline configuration

A new pipeline YAML (e.g. `config/pipeline.project-mode.yaml`) would wire the
new agents together. The existing orchestrator already dispatches on `output_kind`,
so adding `"project"` as a recognised kind is the primary hook point.

### 5. `LearnerProfile.environment` becomes meaningful

With project mode, `environment` would actually change what the agent generates:

| Value | Effect |
|---|---|
| `jupyter_notebook` / `google_colab` | Current notebook mode (no change) |
| `vscode` / `ide` | Project mode: Python files + `.vscode/` launch config |
| `cli` | Project mode: script(s) runnable from the terminal |
| `book` | Static markdown + code blocks, no execution |

## Example: Langfuse Setup as a Learning Project

With project mode, a prompt like:

```bash
forged build \
  --topic "Setting up Langfuse for LLM observability" \
  --learner-profile templates/examples/learner-backend-junior.yaml \
  --environment cli
```

could produce:

```
run/
  main.py          # Langfuse client setup + example trace
  config.py        # environment variable loading
  tracer.py        # reusable tracing helper
  requirements.txt
  tests/
    test_tracer.py # asserts trace was created
  README.md        # how to run it
```

The executor would run `pytest tests/` and report pass/fail per test, feeding
the same revision loop already used by the notebook pipeline.

## What Stays the Same

- `PlannerAgent` — produces a lesson plan regardless of output format
- `StudentAgent` — reads the plan and evaluates completeness
- `ReviserAgent` — requests changes; only the target artifact type differs
- `ArtifactStore` — already format-agnostic
- `LLMClient` + Langfuse tracing — unchanged
- Failure classification and revision loop logic — largely reusable

## Open Questions

- **Sandboxing**: subprocess execution is less isolated than a Jupyter kernel.
  A Docker container or `nsjail` would be safer for untrusted LLM-generated code.
- **Multi-language**: the executor would need to be language-aware
  (`node index.js`, `cargo run`, `go run .`, etc.).
- **File diffing for revision**: the reviser currently references cell indices.
  For project mode it would need to reference file paths and line numbers instead.
- **Output delivery**: notebooks open in Jupyter directly; a project needs to be
  zipped or written to a directory the learner can use.
