"""ExecutorStage — the anti-bug layer.

This is the stage that would have caught today's notebook errors. It does not call
an LLM. It actually *runs* the generated notebook in a real kernel, captures each
cell's outputs and any errors, and writes a structured report. Downstream agents
(student, reviewer) then judge what the code genuinely does — not what someone
assumed it would do.
"""

from __future__ import annotations

import json
import os
import traceback
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO

import nbformat
from nbclient import NotebookClient
from nbclient.exceptions import CellExecutionError
from nbformat.v4 import new_output

from .artifacts import Artifact, ArtifactStore
from .config import StageConfig

DEFAULT_TIMEOUT_SECONDS = 120
DEFAULT_KERNEL = "python3"
MAX_OUTPUT_CHARS = 2000  # Truncate long cell outputs to keep the report readable.
HEADLESS_MPL_BACKEND = "Agg"  # Non-interactive matplotlib backend for the run kernel.


def _ensure_headless_matplotlib() -> None:
    """Force a non-interactive matplotlib backend for the kernel subprocess.

    The run kernel inherits this process's environment. matplotlib's default backend
    on macOS is the GUI ``macosx`` backend, which blocks on window-server init under a
    headless nbclient kernel — on a cold venv the very first ``import matplotlib.pyplot``
    then exceeds the per-cell timeout and kills the whole run at iteration 0. ``Agg``
    renders off-screen and imports in well under a second. ``setdefault`` so an explicit
    caller-provided ``MPLBACKEND`` still wins.
    """
    os.environ.setdefault("MPLBACKEND", HEADLESS_MPL_BACKEND)


def executed_notebook_filename(output_name: str) -> str:
    """Name of the executed-with-outputs notebook an executor stage writes.
    Single source of truth so the orchestrator can locate the deliverable."""
    return f"{output_name}_executed.ipynb"


class ExecutorStage:
    """Executes a notebook artifact and reports per-cell results."""

    def __init__(self, stage: StageConfig):
        self._stage = stage
        self._timeout = int(stage.params.get("timeout", DEFAULT_TIMEOUT_SECONDS))
        self._kernel = str(stage.params.get("kernel", DEFAULT_KERNEL))

    def run(self, store: ArtifactStore) -> Artifact:
        """Run the single input notebook and write a JSON execution report."""
        if len(self._stage.inputs) != 1:
            raise ValueError(
                f"Executor stage '{self._stage.name}' expects exactly one input "
                f"notebook, got {self._stage.inputs}"
            )

        notebook_artifact = store.get(self._stage.inputs[0])
        notebook = nbformat.reads(notebook_artifact.content, as_version=4)

        report = self._execute(notebook, store)

        artifact = Artifact(
            name=self._stage.output,
            kind="json",
            content=json.dumps(report, indent=2),
        )
        return store.put(artifact)

    def _execute(self, notebook, store: ArtifactStore) -> dict:
        """Run the notebook, persist the executed copy, and summarise results."""
        _ensure_headless_matplotlib()
        try:
            client = NotebookClient(
                notebook,
                timeout=self._timeout,
                kernel_name=self._kernel,
                allow_errors=True,  # Run every cell so we see ALL failures, not just the first.
                resources={"metadata": {"path": str(store.run_dir)}},
            )
            error: str | None = None
            try:
                client.execute()
            except CellExecutionError as exc:  # Defensive: allow_errors should prevent this.
                error = str(exc)
        except PermissionError:
            error = None
            self._execute_in_process(notebook)

        # Save the executed notebook (with real outputs) for inspection.
        executed_path = store.run_dir / executed_notebook_filename(self._stage.output)
        executed_path.write_text(nbformat.writes(notebook), encoding="utf-8")

        cell_reports = [
            self._summarise_cell(index, cell)
            for index, cell in enumerate(notebook.cells)
            if cell.cell_type == "code"
        ]
        failed = [c for c in cell_reports if c["status"] == "error"]

        return {
            "ok": not failed and error is None,
            "executed_notebook": executed_path.name,
            "code_cell_count": len(cell_reports),
            "failed_cell_count": len(failed),
            "harness_error": error,
            "cells": cell_reports,
        }

    def _execute_in_process(self, notebook) -> None:
        """Fallback used when a kernel cannot be spawned in the current sandbox."""
        namespace: dict[str, object] = {"__name__": "__main__"}
        for index, cell in enumerate(notebook.cells):
            if cell.cell_type != "code":
                continue

            stdout = StringIO()
            stderr = StringIO()
            cell.outputs = []
            cell.execution_count = index + 1
            try:
                with redirect_stdout(stdout), redirect_stderr(stderr):
                    exec(compile(cell.source, f"<cell {index}>", "exec"), namespace)
            except Exception as exc:  # noqa: BLE001 - notebook execution should continue
                cell.outputs = [
                    new_output(
                        "error",
                        ename=exc.__class__.__name__,
                        evalue=str(exc),
                        traceback=traceback.format_exception(exc),
                    )
                ]
                continue

            text = stdout.getvalue() + stderr.getvalue()
            if text:
                cell.outputs = [new_output("stream", name="stdout", text=text)]

    @staticmethod
    def _summarise_cell(index: int, cell) -> dict:
        """Reduce a single code cell's outputs to a compact status + text."""
        texts: list[str] = []
        status = "ok"
        error_detail: str | None = None

        for output in cell.get("outputs", []):
            output_type = output.get("output_type")
            if output_type == "error":
                status = "error"
                error_detail = f"{output.get('ename')}: {output.get('evalue')}"
            elif output_type == "stream":
                texts.append(output.get("text", ""))
            elif output_type in ("execute_result", "display_data"):
                data = output.get("data", {})
                if "text/plain" in data:
                    texts.append(data["text/plain"])

        joined = "".join(texts)
        return {
            "cell_index": index,
            "status": status,
            "error": error_detail,
            "source_preview": cell.source[:200],
            "output_preview": joined[:MAX_OUTPUT_CHARS],
        }
