"""Tests for the per-run deliverable writers (doc 18, D6 — honest failure reporting).

A HARD failure (no acceptable notebook — provisioning refused, an error, budget
exhaustion, or a run that never reached a terminal state) must NOT ship
`lesson.ipynb`; it ships a short `FAILED.md` stub instead. A run that ended with
an ACCEPTABLE notebook — degraded or not — still ships `lesson.ipynb` exactly as
before; that prior decision (doc 10, P6) is narrowed here, not reversed.

No LLM, no network: these exercise the writers directly against hand-built
`PipelineState`s and a real `ArtifactStore` over a tmp_path run dir.
"""

from __future__ import annotations

from pathlib import Path

import nbformat
import pytest

from forged.artifacts import Artifact, ArtifactStore
from forged.deliverables import (
    FAILED_STUB_FILE,
    write_final_notebook,
    write_learner_package,
)
from forged.models import LearnerProfile
from forged.pipeline.state import (
    Degradation,
    PipelineStage,
    StageOutput,
    create_initial_state,
)


def _profile() -> LearnerProfile:
    return LearnerProfile(
        name="Kevin",
        description="Junior DS moving into AI engineering.",
        prior_knowledge=[],
        environment="jupyter_notebook",
        material_density="standard",
        learning_style="hands_on",
        background_context="",
    )


def _store_with_notebook(run_dir: Path, iteration: int = 0) -> ArtifactStore:
    """A store seeded with a real assembled notebook artifact (as CodeAuthor would)."""
    store = ArtifactStore(run_dir)
    notebook = nbformat.v4.new_notebook()
    notebook.cells = [nbformat.v4.new_code_cell("print('hi')")]
    store.put(
        Artifact(
            name=f"lesson_notebook_v{iteration}",
            kind="notebook",
            content=nbformat.writes(notebook),
        )
    )
    return store


def _acceptable_state(store: ArtifactStore, iteration: int = 0):
    state = create_initial_state(run_id="r1")
    state = state.with_output(
        StageOutput(
            stage=PipelineStage.CODE_AUTHOR,
            artifact_name=f"lesson_notebook_v{iteration}",
            iteration=iteration,
        )
    )
    return state.with_terminal("acceptable", ok=True)


# ── write_final_notebook: acceptable path unchanged (regression guard) ──────────


@pytest.mark.unit
def test_acceptable_run_still_ships_lesson_notebook(tmp_path: Path) -> None:
    store = _store_with_notebook(tmp_path)
    state = _acceptable_state(store)

    write_final_notebook(tmp_path, store, state)

    assert (tmp_path / "lesson.ipynb").is_file()
    assert not (tmp_path / FAILED_STUB_FILE).is_file()


@pytest.mark.unit
def test_degraded_but_acceptable_run_still_ships_lesson_notebook(tmp_path: Path) -> None:
    """A degradation was recorded but the run still ended ACCEPTABLE — the prior
    decision (a degraded run still ships an openable lesson.ipynb) must hold."""
    store = _store_with_notebook(tmp_path)
    state = _acceptable_state(store)
    state = state.with_degradation(
        Degradation(stage=PipelineStage.CODE_AUTHOR, kind="llm_empty_fallback", detail="boom")
    )

    write_final_notebook(tmp_path, store, state)

    assert (tmp_path / "lesson.ipynb").is_file()
    assert not (tmp_path / FAILED_STUB_FILE).is_file()


# ── write_final_notebook: hard failure suppresses lesson.ipynb ──────────────────


@pytest.mark.unit
def test_hard_failure_suppresses_lesson_notebook_and_writes_stub(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path)
    state = create_initial_state(run_id="r1").with_terminal(
        "Environment provisioning failed: package(s) outside the allow-list: openai", ok=False
    )

    write_final_notebook(tmp_path, store, state)

    assert not (tmp_path / "lesson.ipynb").is_file()
    assert (tmp_path / FAILED_STUB_FILE).is_file()


@pytest.mark.unit
def test_failure_stub_names_the_reason(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path)
    reason = "Environment provisioning failed: package(s) outside the allow-list: openai"
    state = create_initial_state(run_id="r1").with_terminal(reason, ok=False)

    write_final_notebook(tmp_path, store, state)

    stub = (tmp_path / FAILED_STUB_FILE).read_text(encoding="utf-8")
    assert reason in stub


@pytest.mark.unit
def test_failure_stub_names_degradation_detail(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path)
    state = create_initial_state(run_id="r1").with_degradation(
        Degradation(
            stage=PipelineStage.EXECUTOR,
            kind="provision_failed",
            detail="package(s) outside the allow-list: openai, faiss-cpu, pytest",
        )
    )
    state = state.with_terminal("Environment provisioning failed", ok=False)

    write_final_notebook(tmp_path, store, state)

    stub = (tmp_path / FAILED_STUB_FILE).read_text(encoding="utf-8")
    assert "openai, faiss-cpu, pytest" in stub


@pytest.mark.unit
def test_failure_stub_points_to_raw_notebooks_and_summary(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path)
    state = create_initial_state(run_id="r1").with_terminal("boom", ok=False)

    write_final_notebook(tmp_path, store, state)

    stub = (tmp_path / FAILED_STUB_FILE).read_text(encoding="utf-8")
    assert "lesson_notebook_v" in stub
    assert "SUMMARY.md" in stub


@pytest.mark.unit
def test_failure_stub_preserves_raw_v_files_on_disk(tmp_path: Path) -> None:
    """The v-file notebook attempts are not touched by this writer — the missing
    canonical lesson.ipynb is the signal, not a deleted attempt."""
    store = _store_with_notebook(tmp_path)  # writes lesson_notebook_v0.ipynb to disk
    state = create_initial_state(run_id="r1").with_terminal("Executor error: boom", ok=False)

    write_final_notebook(tmp_path, store, state)

    assert (tmp_path / "lesson_notebook_v0.ipynb").is_file()
    assert not (tmp_path / "lesson.ipynb").is_file()


@pytest.mark.unit
def test_non_terminal_run_also_suppresses_lesson_notebook(tmp_path: Path) -> None:
    """A run that never reached a terminal state at all (e.g. an interrupted
    orchestrator call) is a hard failure too — never write a lesson.ipynb for it."""
    store = ArtifactStore(tmp_path)
    state = create_initial_state(run_id="r1")  # never terminated

    write_final_notebook(tmp_path, store, state)

    assert not (tmp_path / "lesson.ipynb").is_file()
    assert (tmp_path / FAILED_STUB_FILE).is_file()


# ── write_learner_package: README surfaces the failure reason ───────────────────


@pytest.mark.unit
def test_learner_package_readme_has_no_failure_banner_when_acceptable(tmp_path: Path) -> None:
    store = _store_with_notebook(tmp_path)
    state = _acceptable_state(store)

    write_learner_package(tmp_path, store, state, "Test topic", _profile())

    readme = (tmp_path / "README.md").read_text(encoding="utf-8")
    assert "did not complete" not in readme.lower()


@pytest.mark.unit
def test_learner_package_readme_surfaces_reason_on_hard_failure(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path)
    reason = "Environment provisioning failed: package(s) outside the allow-list: openai"
    state = create_initial_state(run_id="r1").with_terminal(reason, ok=False)

    write_learner_package(tmp_path, store, state, "Test topic", _profile())

    readme = (tmp_path / "README.md").read_text(encoding="utf-8")
    assert reason in readme
    assert "did not complete" in readme.lower()
