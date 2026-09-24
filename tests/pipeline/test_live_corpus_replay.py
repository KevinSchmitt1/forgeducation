"""Live single-slice replay of the real critics over the doc-22 regression corpus.

This is the missing **vertical** rung (Lane 1). Every other check on the pipeline is
horizontal: unit tests and the mocked-LLM graph-integration test prove the *plumbing*
carries a value, but they can never prove an **LLM critic produces a good judgement**.
The only vertical check today is a full paid run — manual, rare, gated. So R2 and R5 both
shipped "plumbing-validated only" (see docs/architecture/22-*.md, both "Confidence level"
notes).

This harness feeds a real captured notebook + its execution report through the *real*
Student and Reviewer agents on **gpt-5-mini** (cheap — two calls, cents) and makes a
weak-but-real assertion about each change:

  * **R2** — the critic no longer restates the execution failure verbatim.
  * **R5** — a ``goal_fit`` verdict is emitted and parses.

It is a **manual pre-merge ritual for LLM-judgement changes**, not a CI test: the
``live`` marker opts it out of the no-billable-calls guard (tests/conftest.py), and the
default suite excludes it. Run it once before merging a critic/persona/router change:

    .venv/bin/python -m pytest -m live tests/pipeline/test_live_corpus_replay.py

Needs ``OPENAI_API_KEY`` (loaded from .env by conftest); skips cleanly without one.

This lane only *observes* the pipeline — it must not modify pipeline logic. If the replay
reveals a bug, file it in TODO.md; the fix belongs to R6/R7 or a bugfix lane.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import pytest

from forged.artifacts import Artifact, ArtifactStore
from forged.config import load_pipeline
from forged.llm import LLMClient
from forged.pipeline.agents import Agent
from forged.pipeline.agents.reviewer import ReviewerAgent
from forged.pipeline.agents.student import StudentAgent
from forged.pipeline.state import PipelineState, create_initial_state

# ── Corpus wiring ───────────────────────────────────────────────────────────────

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_CORPUS_DIR = _PROJECT_ROOT / "tests" / "corpus" / "doc22-regression-run"
_PERSONAS_DIR = _PROJECT_ROOT / "personas"
_PIPELINE_CONFIG = _PROJECT_ROOT / "config" / "pipeline.review-loop.yaml"

# v0 is a real execution failure (IndentationError) with an error_summary — the exact
# shape R2 is about. v3 (the 26-cell sprawl) is the case R6's digest will care about.
_CORPUS_VERSION = 0

# skipif keeps a keyless `-m live` invocation a clean skip instead of a RuntimeError.
_requires_api_key = pytest.mark.skipif(
    not os.environ.get("OPENAI_API_KEY"),
    reason="live replay needs OPENAI_API_KEY (set it in .env)",
)


@pytest.fixture(autouse=True)
def _only_when_live_selected(request: pytest.FixtureRequest) -> None:
    """Skip unless the run explicitly asked for live tests via ``-m live``.

    The ``live`` marker alone does not deselect a test from a bare ``pytest`` run — it
    only opts the test out of the no-billable-calls guard (tests/conftest.py). Without
    this gate a plain ``pytest`` on a machine that has OPENAI_API_KEY would *spend money*
    running this harness. Requiring the marker to be named in the ``-m`` expression makes
    the documented ritual (``pytest -m live …``) the only way these paid calls fire, so
    the default suite genuinely excludes them.
    """
    markexpr = request.config.getoption("-m", default="")
    if "live" not in markexpr:
        pytest.skip("live replay only runs under an explicit `-m live` selection")


def _load_corpus_iteration(store: ArtifactStore, version: int) -> str:
    """Populate ``store`` with one corpus iteration's inputs; return its error_summary.

    Artifacts are registered under the iteration-0 fallback names the critics resolve to
    when no CODE_AUTHOR/EXECUTOR output exists in state (see ``_latest_notebook_name`` /
    ``_latest_execution_name``), so the state's iteration and the corpus version stay
    decoupled — any captured version can be replayed against a fresh iteration-0 state.
    """
    notebook = (_CORPUS_DIR / f"lesson_notebook_v{version}.ipynb").read_text(encoding="utf-8")
    exec_report = (_CORPUS_DIR / f"execution_report_v{version}.json").read_text(encoding="utf-8")
    context = (_CORPUS_DIR / "lesson_context.md").read_text(encoding="utf-8")

    store.put(Artifact(name="lesson_notebook_v0", kind="notebook", content=notebook))
    store.put(Artifact(name="execution_report_v0", kind="json", content=exec_report))
    store.put(Artifact(name="lesson_context", kind="text", content=context))

    return json.loads(exec_report).get("error_summary", "")


def _replay_critic(agent: Agent, store: ArtifactStore, report_artifact: str) -> dict:
    """Run one critic against the loaded corpus and return its parsed report dict."""
    state: PipelineState = create_initial_state(run_id="live-corpus-replay")
    asyncio.run(agent.run(state, store))
    return json.loads(store.get(report_artifact).content)


def _assert_emits_goal_fit(report: dict) -> None:
    """R5 — a goal_fit verdict was emitted and parses into the expected shape."""
    assert "goal_fit" in report, "critic emitted no goal_fit verdict (R5 regression)"
    verdict = report["goal_fit"]
    assert isinstance(verdict, dict), f"goal_fit was not an object: {verdict!r}"
    assert isinstance(verdict.get("fit"), bool), "goal_fit.fit must be a boolean"
    assert isinstance(verdict.get("problems"), list), "goal_fit.problems must be a list"
    assert isinstance(verdict.get("text"), str), "goal_fit.text must be a string"


def _assert_does_not_restate_failure(report: dict, error_summary: str) -> None:
    """R2 — the critic did not reproduce the execution error verbatim in its findings.

    The execution report and revision brief already carry the failed-cell list once;
    a verbatim restatement wastes a finding slot (only the first five reach the brief),
    evicting a real judgement. Paraphrase is fine — this only forbids the literal copy.
    """
    if not error_summary:
        pytest.skip("corpus iteration has no error_summary to restate")
    finding_texts = [f.get("text", "") for f in report.get("findings", [])]
    carried = finding_texts + report.get("blockers", [])
    restated = [text for text in carried if error_summary in text]
    assert not restated, f"critic restated the execution failure verbatim (R2): {restated}"


# ── Fixtures ────────────────────────────────────────────────────────────────────


@pytest.fixture
def store(tmp_path: Path) -> ArtifactStore:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    return ArtifactStore(run_dir)


@pytest.fixture
def pipeline_config():
    return load_pipeline(_PIPELINE_CONFIG)


# ── Tests ───────────────────────────────────────────────────────────────────────


@pytest.mark.live
@_requires_api_key
def test_reviewer_replay_emits_goal_fit_and_does_not_restate_failure(
    store: ArtifactStore, pipeline_config
) -> None:
    error_summary = _load_corpus_iteration(store, _CORPUS_VERSION)
    reviewer = ReviewerAgent(
        personas_dir=_PERSONAS_DIR,
        llm_client=LLMClient(pipeline_config.resolved_model_name("reviewer")),
    )

    # State iteration is 0, so the critic writes its report under the _v0 name
    # regardless of which corpus version was loaded into the store.
    report = _replay_critic(reviewer, store, "reviewer_report_v0")

    assert report.get("reviewed") is True, f"reviewer degraded instead of reviewing: {report}"
    _assert_emits_goal_fit(report)  # R5
    _assert_does_not_restate_failure(report, error_summary)  # R2


@pytest.mark.live
@_requires_api_key
def test_student_replay_emits_goal_fit_and_does_not_restate_failure(
    store: ArtifactStore, pipeline_config
) -> None:
    error_summary = _load_corpus_iteration(store, _CORPUS_VERSION)
    student = StudentAgent(
        personas_dir=_PERSONAS_DIR,
        llm_client=LLMClient(pipeline_config.resolved_model_name("student")),
    )

    report = _replay_critic(student, store, "student_grade_report_v0")

    assert report.get("graded") is True, f"student degraded instead of grading: {report}"
    _assert_emits_goal_fit(report)  # R5
    # The Student may never say `drifted` — that asymmetry is load-bearing (doc 22 R5).
    assert "drifted" not in report["goal_fit"]["problems"], "Student must not report `drifted`"
    _assert_does_not_restate_failure(report, error_summary)  # R2
