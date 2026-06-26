"""Offline tests — no network, no API key required.

These cover the architecture's load-bearing parts:
  * pipeline config loads and validates (and rejects broken dataflow)
  * notebook assembly from the model's JSON cell format
  * the executor actually runs a notebook AND flags a failing cell

Run from the repo root:  pytest -q
"""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from forged.artifacts import Artifact, ArtifactStore
from forged.config import PipelineConfig, StageType, load_pipeline
from forged.executor import ExecutorStage
from forged.notebook import build_notebook, cells_from_json, render_indexed

CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"


# ── Config ───────────────────────────────────────────────────────────────────

def test_skeleton_config_loads_expected_stages():
    pipeline = load_pipeline(CONFIG_DIR / "pipeline.skeleton.yaml")
    assert pipeline.name == "skeleton"
    assert [s.name for s in pipeline.stages] == [
        "planner", "code_author", "executor", "student",
    ]
    assert pipeline.resolved_model_name("planner").model == "gpt-5-mini"
    assert pipeline.resolved_model_name("code_author").model == "gpt-5"
    assert pipeline.resolved_model_name("student").model == "gpt-5-mini"


def test_profile_is_a_valid_seed_input():
    # Stages may read the 'profile' seed without any stage producing it.
    config = {
        "name": "p",
        "stages": [
            {"name": "s1", "persona": "x.md", "inputs": ["brief", "profile"],
             "output": "out"},
        ],
    }
    pipeline = PipelineConfig.model_validate(config)
    assert pipeline.stages[0].inputs == ["brief", "profile"]


def test_config_rejects_stage_reading_unknown_artifact():
    broken = {
        "name": "bad",
        "stages": [
            {"name": "s1", "persona": "p.md", "inputs": ["nope"], "output": "out"},
        ],
    }
    with pytest.raises(ValueError, match="no .*earlier stage produces"):
        PipelineConfig.model_validate(broken)


def test_config_rejects_llm_stage_without_persona():
    broken = {
        "name": "bad",
        "stages": [{"name": "s1", "type": "llm", "inputs": ["brief"], "output": "o"}],
    }
    with pytest.raises(ValueError, match="must declare a persona"):
        PipelineConfig.model_validate(broken)


def test_revision_policy_requires_baseline_executor_and_notebook():
    broken = {
        "name": "bad",
        "stages": [
            {"name": "planner", "persona": "planner.md", "inputs": ["brief"], "output": "plan"},
        ],
        "revision": {
            "reviser": "reviser.md",
            "critics": ["student.md"],
        },
    }
    with pytest.raises(ValueError, match="Revision policy requires"):
        PipelineConfig.model_validate(broken)


# ── Notebook assembly ────────────────────────────────────────────────────────

def test_cells_from_json_handles_bare_array():
    raw = '[{"type": "markdown", "source": "# Hi"}, {"type": "code", "source": "x=1"}]'
    cells = cells_from_json(raw)
    assert [c["type"] for c in cells] == ["markdown", "code"]


def test_cells_from_json_strips_code_fence():
    raw = '```json\n[{"type": "code", "source": "x=1"}]\n```'
    cells = cells_from_json(raw)
    assert cells[0]["source"] == "x=1"


def test_cells_from_json_rejects_bad_cell_type():
    with pytest.raises(ValueError, match="invalid type"):
        cells_from_json('[{"type": "sql", "source": "select 1"}]')


def test_build_notebook_produces_valid_ipynb():
    cells = [{"type": "markdown", "source": "# T"}, {"type": "code", "source": "x=1"}]
    nb_json = json.loads(build_notebook(cells))
    assert nb_json["nbformat"] == 4
    assert len(nb_json["cells"]) == 2


def test_render_indexed_labels_cells_consistently():
    # Indices in the rendering must match notebook cell positions (markdown included)
    # so agent feedback lines up with the executor's report.
    nb = build_notebook(
        [
            {"type": "markdown", "source": "# Title"},
            {"type": "code", "source": "x = 1"},
            {"type": "markdown", "source": "Done"},
        ]
    )
    rendered = render_indexed(nb)
    assert "indexed 0..2" in rendered
    assert "[cell 0 · markdown]" in rendered
    assert "[cell 1 · code]" in rendered
    assert "[cell 2 · markdown]" in rendered


def test_review_loop_config_validates():
    pipeline = load_pipeline(CONFIG_DIR / "pipeline.review-loop.yaml")
    names = [s.name for s in pipeline.stages]
    assert names == ["planner", "code_author", "executor", "student", "reviewer"]
    assert pipeline.revision is not None
    assert pipeline.revision.reviser == "reviser.md"
    assert pipeline.revision.critics == ["student.md", "reviewer.md"]
    assert pipeline.revision.max_iterations == 3
    assert pipeline.resolved_model_name("reviewer").model == "gpt-5-mini"
    assert pipeline.resolved_model_name("reviser").model == "gpt-5"


def test_resolved_model_prefers_stage_override_then_stage_models_then_defaults():
    pipeline = PipelineConfig.model_validate(
        {
            "name": "models",
            "defaults": {"provider": "openai", "model": "fallback-model"},
            "stage_models": {
                "planner": {"provider": "openai", "model": "planner-model"},
                "reviser": {"provider": "openai", "model": "reviser-model"},
            },
            "stages": [
                {
                    "name": "planner",
                    "persona": "planner.md",
                    "inputs": ["brief"],
                    "output": "plan",
                    "model": {"provider": "openai", "model": "stage-override"},
                },
                {
                    "name": "student",
                    "persona": "student.md",
                    "inputs": ["plan"],
                    "output": "feedback",
                },
            ],
        }
    )

    assert pipeline.resolved_model(pipeline.stages[0]).model == "stage-override"
    assert pipeline.resolved_model(pipeline.stages[1]).model == "fallback-model"
    assert pipeline.resolved_model_name("planner").model == "stage-override"
    assert pipeline.resolved_model_name("reviser").model == "reviser-model"
    assert pipeline.resolved_model_name("unknown").model == "fallback-model"


# ── Executor (the anti-bug layer) ────────────────────────────────────────────

def _store_with_notebook(tmp_path: Path, sources: list[str]) -> ArtifactStore:
    store = ArtifactStore(tmp_path)
    cells = [{"type": "code", "source": s} for s in sources]
    store.put(Artifact(name="notebook", kind="notebook", content=build_notebook(cells)))
    return store


def _executor_stage():
    from forged.config import StageConfig

    return StageConfig(
        name="executor", type="executor", inputs=["notebook"],
        output="report", params={"timeout": 60},
    )


def test_executor_reports_success_for_clean_notebook(tmp_path):
    store = _store_with_notebook(tmp_path, ["a = 2 + 2", "print(a)"])
    report = json.loads(ExecutorStage(_executor_stage()).run(store).content)
    assert report["ok"] is True
    assert report["failed_cell_count"] == 0


def test_executor_flags_failing_cell(tmp_path):
    # A cell that raises must be caught and reported — the exact class of problem
    # that slipped through the original lesson notebook.
    store = _store_with_notebook(tmp_path, ["ok = 1", "raise ValueError('boom')"])
    report = json.loads(ExecutorStage(_executor_stage()).run(store).content)
    assert report["ok"] is False
    assert report["failed_cell_count"] == 1
    failing = [c for c in report["cells"] if c["status"] == "error"][0]
    assert "ValueError" in failing["error"]


# ── Finalize / cleanup ───────────────────────────────────────────────────────

def test_finalize_keeps_only_named_files(tmp_path):
    store = ArtifactStore(tmp_path)
    store.put(Artifact(name="execution_report", kind="json", content="{}"))
    store.put(Artifact(name="lesson_plan", kind="text", content="plan"))
    store.write_file("lesson.ipynb", "{}")
    store.write_file("SUMMARY.md", "# summary")

    removed = store.finalize({"lesson.ipynb", "SUMMARY.md", "manifest.json"})

    remaining = {p.name for p in tmp_path.iterdir()}
    assert remaining == {"lesson.ipynb", "SUMMARY.md"}
    assert "execution_report.json" in removed
    assert "lesson_plan.md" in removed


def test_build_summary_reports_execution_and_narrative(tmp_path):
    from forged.config import PipelineConfig
    from forged.report import build_summary

    pipeline = PipelineConfig.model_validate(
        {
            "name": "t",
            "stages": [
                {"name": "code", "persona": "c.md", "inputs": ["brief"],
                 "output": "nb", "output_kind": "notebook"},
                {"name": "executor", "type": "executor", "inputs": ["nb"],
                 "output": "execution_report"},
            ],
        }
    )
    store = ArtifactStore(tmp_path)
    store.put(Artifact(name="nb", kind="notebook",
                       content=build_notebook([{"type": "code", "source": "x=1"}])))
    failing_report = {
        "ok": False, "code_cell_count": 1, "failed_cell_count": 1,
        "cells": [{"cell_index": 0, "status": "error",
                   "error": "ValueError: boom", "source_preview": "raise ..."}],
    }
    store.put(Artifact(name="execution_report", kind="json",
                       content=json.dumps(failing_report)))

    summary = build_summary(pipeline, store, "My topic", "learner.md")
    assert "My topic" in summary
    assert "ValueError: boom" in summary  # failure surfaced
    assert "1/1 cells failed" in summary   # stage result column


def _clean_args(**overrides):
    from argparse import Namespace

    defaults = {"keep": 10, "runs": None, "yes": True, "dry_run": False}
    defaults.update(overrides)
    return Namespace(**defaults)


def _make_runs(tmp_path, stamps):
    runs = tmp_path / "runs"
    runs.mkdir()
    for stamp in stamps:
        (runs / stamp).mkdir()
    return runs


def test_clean_keeps_newest_runs(tmp_path):
    from forged.cli import _cmd_clean

    runs = _make_runs(tmp_path, ["20260101-000000_x", "20260102-000000_x", "20260103-000000_x"])

    _cmd_clean(_clean_args(keep=2, runs=str(runs), yes=True))

    remaining = sorted(p.name for p in runs.iterdir())
    assert remaining == ["20260102-000000_x", "20260103-000000_x"]


def test_clean_dry_run_deletes_nothing(tmp_path):
    from forged.cli import _cmd_clean

    runs = _make_runs(tmp_path, ["20260101-000000_x", "20260102-000000_x", "20260103-000000_x"])

    rc = _cmd_clean(_clean_args(keep=1, runs=str(runs), dry_run=True))

    assert rc == 0
    assert len(list(runs.iterdir())) == 3  # nothing removed


def test_clean_rejects_negative_keep(tmp_path):
    from forged.cli import _cmd_clean

    runs = _make_runs(tmp_path, ["20260101-000000_x"])

    rc = _cmd_clean(_clean_args(keep=-1, runs=str(runs)))

    assert rc == 2
    assert len(list(runs.iterdir())) == 1  # untouched


def test_clean_refuses_without_confirmation_when_not_a_tty(tmp_path, monkeypatch):
    # No --yes and stdin is not interactive → refuse rather than wipe runs blindly.
    import sys

    from forged.cli import _cmd_clean

    runs = _make_runs(tmp_path, ["20260101-000000_x", "20260102-000000_x"])
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)

    rc = _cmd_clean(_clean_args(keep=0, runs=str(runs), yes=False))

    assert rc == 1
    assert len(list(runs.iterdir())) == 2  # nothing deleted


# ── Acceptance gate (graded keep-best) ───────────────────────────────────────
#
# The gate links each notebook version to the executor report that ran it and the
# critiques grounded on that report. Quality is GRADED (a 0–100 score from the
# findings), facts are BINARY (a crashing cell or a BLOCKER is a hard floor). It
# keeps the BEST version: prefer no crucial issue, then higher quality, then earliest
# — so a revision is adopted only when it genuinely improves the lesson.

from forged.executor import executed_notebook_filename  # noqa: E402
from forged.gate import evaluate_candidates, notebook_candidates  # noqa: E402


def _review_loop_pipeline() -> PipelineConfig:
    return PipelineConfig.model_validate(
        {
            "name": "review-loop",
            "stages": [
                {"name": "planner", "persona": "planner.md", "inputs": ["brief", "profile"],
                 "output": "lesson_plan"},
                {"name": "code_author", "persona": "code_author.md",
                 "inputs": ["lesson_plan", "profile"], "output": "notebook",
                 "output_kind": "notebook",
                 "model": {"provider": "openai", "model": "gpt-4o-mini",
                           "temperature": 0.2, "max_tokens": 4096}},
                {"name": "executor", "type": "executor", "inputs": ["notebook"],
                 "output": "execution_report"},
                {"name": "student", "persona": "student.md",
                 "inputs": ["notebook", "execution_report", "profile"],
                 "output": "student_feedback"},
                {"name": "reviewer", "persona": "reviewer.md",
                 "inputs": ["notebook", "execution_report", "profile"],
                 "output": "reviewer_feedback"},
                {"name": "reviser", "persona": "reviser.md",
                 "inputs": ["notebook", "student_feedback", "reviewer_feedback", "profile"],
                 "output": "revised_notebook", "output_kind": "notebook",
                 "model": {"provider": "openai", "model": "gpt-4o-mini",
                           "temperature": 0.2, "max_tokens": 4096}},
                {"name": "executor_revised", "type": "executor",
                 "inputs": ["revised_notebook"], "output": "revised_execution_report"},
                {"name": "student_revised", "persona": "student.md",
                 "inputs": ["revised_notebook", "revised_execution_report", "profile"],
                 "output": "revised_feedback"},
                {"name": "reviewer_revised", "persona": "reviewer.md",
                 "inputs": ["revised_notebook", "revised_execution_report", "profile"],
                 "output": "revised_reviewer_feedback"},
            ],
        }
    )


def _put_report(store: ArtifactStore, report_name: str, ok: bool) -> None:
    report = {
        "ok": ok,
        "executed_notebook": executed_notebook_filename(report_name),
        "code_cell_count": 1,
        "failed_cell_count": 0 if ok else 1,
        "harness_error": None,
        "cells": [],
    }
    store.put(Artifact(name=report_name, kind="json", content=json.dumps(report)))


def _put_text(store: ArtifactStore, name: str, content: str) -> None:
    store.put(Artifact(name=name, kind="text", content=content))


def _put_notebook(store: ArtifactStore, name: str, marker: str) -> None:
    store.put(Artifact(name=name, kind="notebook",
                       content=build_notebook([{"type": "code", "source": marker}])))


# Quality score = 100 − severity burden (BLOCKER=100, CONFUSING=5, NITPICK=1);
# a version aggregates the findings of BOTH critics.
CLEAN_FEEDBACK = "Verdict: yes, I'd understand it."                            # → 100
NITPICK_FEEDBACK = "NITPICK cell 2 — tiny typo. Verdict: yes."                 # → 99
BLOCKER_FEEDBACK = "BLOCKER cell 1 — claim contradicts output. Verdict: no."   # crucial → 0


def _confusing(n: int) -> str:
    """Feedback carrying n CONFUSING findings (burden 5n → score 100−5n)."""
    lines = [f"CONFUSING cell {i} — leap {i} I couldn't follow." for i in range(1, n + 1)]
    return "\n".join(lines) + "\nVerdict: maybe."


def _populate_review_loop(store, *, orig_ok, orig_fb, revised_ok, revised_fb,
                          orig_review_fb=CLEAN_FEEDBACK, revised_review_fb=CLEAN_FEEDBACK):
    """Seed a store as the review-loop pipeline would, for both versions —
    including both critics (student + reviewer) per version."""
    _put_notebook(store, "notebook", "v = 'original'")
    _put_report(store, "execution_report", ok=orig_ok)
    _put_text(store, "student_feedback", orig_fb)
    _put_text(store, "reviewer_feedback", orig_review_fb)
    _put_notebook(store, "revised_notebook", "v = 'revised'")
    _put_report(store, "revised_execution_report", ok=revised_ok)
    _put_text(store, "revised_feedback", revised_fb)
    _put_text(store, "revised_reviewer_feedback", revised_review_fb)


def _scripted_runner_factory(*, notebook_markers: dict[str, str], text_outputs: dict[str, str],
                             report_ok: dict[str, bool]):
    """Build a deterministic runner factory for orchestrator loop tests."""

    class _Runner:
        def __init__(self, stage):
            self._stage = stage

        def run(self, store: ArtifactStore):
            if self._stage.type is StageType.EXECUTOR:
                return self._run_executor(store)
            return self._run_llm(store)

        def _run_executor(self, store: ArtifactStore):
            input_name = self._stage.inputs[0]
            executed_name = executed_notebook_filename(self._stage.output)
            store.write_file(executed_name, store.get(input_name).content)
            ok = report_ok.get(self._stage.output, True)
            report = {
                "ok": ok,
                "executed_notebook": executed_name,
                "code_cell_count": 1,
                "failed_cell_count": 0 if ok else 1,
                "harness_error": None,
                "cells": [],
            }
            return store.put(Artifact(
                name=self._stage.output,
                kind="json",
                content=json.dumps(report),
            ))

        def _run_llm(self, store: ArtifactStore):
            if self._stage.output_kind == "notebook":
                marker = notebook_markers[self._stage.output]
                return store.put(Artifact(
                    name=self._stage.output,
                    kind="notebook",
                    content=build_notebook([{"type": "code", "source": marker}]),
                ))
            content = text_outputs[self._stage.output]
            return store.put(Artifact(
                name=self._stage.output,
                kind="text",
                content=content,
            ))

    return lambda stage: _Runner(stage)


def _revision_store(tmp_path: Path, *, baseline_fb: str, revision_fb: str,
                    baseline_ok: bool = True, revision_ok: bool = True) -> ArtifactStore:
    store = ArtifactStore(tmp_path)
    _put_notebook(store, "notebook", "baseline")
    _put_report(store, "execution_report", ok=baseline_ok)
    _put_text(store, "student_feedback", baseline_fb)
    _put_text(store, "reviewer_feedback", CLEAN_FEEDBACK)
    _put_notebook(store, "revised_notebook__i1", "revision-1")
    _put_report(store, "revised_execution_report__i1", ok=revision_ok)
    _put_text(store, "student_feedback__i1", revision_fb)
    _put_text(store, "reviewer_feedback__i1", CLEAN_FEEDBACK)
    return store


def test_notebook_candidates_link_each_version_to_its_report_and_critics():
    candidates = notebook_candidates(_review_loop_pipeline())
    assert [(c.notebook, c.report, c.feedbacks) for c in candidates] == [
        ("notebook", "execution_report", ("student_feedback", "reviewer_feedback")),
        ("revised_notebook", "revised_execution_report",
         ("revised_feedback", "revised_reviewer_feedback")),
    ]


def test_gate_adopts_a_revision_only_when_it_improves_quality(tmp_path):
    # Original is below the bar (3 CONFUSING → 85); the revision is clean (100).
    store = ArtifactStore(tmp_path)
    _populate_review_loop(store, orig_ok=True, orig_fb=_confusing(3),
                          revised_ok=True, revised_fb=CLEAN_FEEDBACK)

    decision = evaluate_candidates(_review_loop_pipeline(), store)

    assert decision.chosen.candidate.notebook == "revised_notebook"
    assert decision.chosen.quality_score == 100
    assert decision.gate_satisfied is True


def test_gate_keeps_original_when_revision_is_no_better(tmp_path):
    # Equal quality → no value in adopting the revision; avoid churn, keep original.
    store = ArtifactStore(tmp_path)
    _populate_review_loop(store, orig_ok=True, orig_fb=CLEAN_FEEDBACK,
                          revised_ok=True, revised_fb=CLEAN_FEEDBACK)

    decision = evaluate_candidates(_review_loop_pipeline(), store)

    assert decision.chosen.candidate.notebook == "notebook"
    assert decision.gate_satisfied is True


def test_gate_keeps_prior_when_revision_fails_execution(tmp_path):
    store = ArtifactStore(tmp_path)
    _populate_review_loop(store, orig_ok=True, orig_fb=CLEAN_FEEDBACK,
                          revised_ok=False, revised_fb=CLEAN_FEEDBACK)

    decision = evaluate_candidates(_review_loop_pipeline(), store)

    assert decision.chosen.candidate.notebook == "notebook"
    assert decision.gate_satisfied is True  # the version we ship is itself clean


def test_gate_keeps_prior_when_revision_has_blocker(tmp_path):
    store = ArtifactStore(tmp_path)
    _populate_review_loop(store, orig_ok=True, orig_fb=CLEAN_FEEDBACK,
                          revised_ok=True, revised_fb=BLOCKER_FEEDBACK)

    decision = evaluate_candidates(_review_loop_pipeline(), store)

    assert decision.chosen.candidate.notebook == "notebook"


def test_gate_blocker_from_reviewer_alone_rejects_revision(tmp_path):
    # A BLOCKER from the reviewer (student clean) must still reject the revision.
    store = ArtifactStore(tmp_path)
    _populate_review_loop(store, orig_ok=True, orig_fb=CLEAN_FEEDBACK,
                          revised_ok=True, revised_fb=CLEAN_FEEDBACK,
                          revised_review_fb=BLOCKER_FEEDBACK)

    decision = evaluate_candidates(_review_loop_pipeline(), store)

    assert decision.chosen.candidate.notebook == "notebook"


def test_gate_ships_least_bad_when_no_version_is_good_enough(tmp_path):
    # Neither clears the bar, neither is crucial → ship the higher-quality one but
    # flag the gate as not satisfied (a human should review the residuals).
    store = ArtifactStore(tmp_path)
    _populate_review_loop(store, orig_ok=True, orig_fb=_confusing(4),    # quality 80
                          revised_ok=True, revised_fb=_confusing(3))      # quality 85

    decision = evaluate_candidates(_review_loop_pipeline(), store)

    assert decision.chosen.candidate.notebook == "revised_notebook"
    assert decision.chosen.quality_score == 85
    assert decision.gate_satisfied is False
    assert decision.crucial_open is False


def test_gate_flags_crucial_open_when_all_versions_crucial(tmp_path):
    store = ArtifactStore(tmp_path)
    _populate_review_loop(store, orig_ok=False, orig_fb=BLOCKER_FEEDBACK,
                          revised_ok=False, revised_fb=BLOCKER_FEEDBACK)

    decision = evaluate_candidates(_review_loop_pipeline(), store)

    assert decision.chosen.candidate.notebook == "notebook"  # earliest on a tie
    assert decision.gate_satisfied is False
    assert decision.crucial_open is True


def test_gate_threshold_is_configurable(tmp_path):
    # A stricter bar makes an otherwise-fine version no longer 'good enough'.
    store = ArtifactStore(tmp_path)
    _put_notebook(store, "notebook", "v = 1")
    _put_report(store, "execution_report", ok=True)
    _put_text(store, "student_feedback", _confusing(1))   # quality 95

    skeleton = load_pipeline(CONFIG_DIR / "pipeline.skeleton.yaml")
    assert evaluate_candidates(skeleton, store, min_quality=90).gate_satisfied is True
    assert evaluate_candidates(skeleton, store, min_quality=99).gate_satisfied is False


def test_gate_single_candidate_passes_through(tmp_path):
    store = ArtifactStore(tmp_path)
    _put_notebook(store, "notebook", "v = 1")
    _put_report(store, "execution_report", ok=True)
    _put_text(store, "student_feedback", CLEAN_FEEDBACK)

    decision = evaluate_candidates(
        load_pipeline(CONFIG_DIR / "pipeline.skeleton.yaml"), store
    )

    assert decision.chosen.candidate.notebook == "notebook"
    assert decision.gate_satisfied is True


def test_orchestrator_delivers_the_accepted_notebook(tmp_path):
    # End-to-end of finalize: a failing revision must not become lesson.ipynb,
    # and the manifest must record the gate decision.
    from forged.orchestrator import Orchestrator

    store = ArtifactStore(tmp_path)
    _populate_review_loop(store, orig_ok=True, orig_fb=CLEAN_FEEDBACK,
                          revised_ok=False, revised_fb=BLOCKER_FEEDBACK)
    # The executor writes an executed-with-outputs notebook per version on disk.
    store.write_file(executed_notebook_filename("execution_report"),
                     build_notebook([{"type": "code", "source": "v = 'original'"}]))
    store.write_file(executed_notebook_filename("revised_execution_report"),
                     build_notebook([{"type": "code", "source": "v = 'revised'"}]))

    orch = Orchestrator(_review_loop_pipeline(), tmp_path, tmp_path)
    orch._finalize(store, "Some topic", "default.md", _review_loop_pipeline())

    delivered = store.read_file("lesson.ipynb")
    assert "v = 'original'" in delivered
    assert "v = 'revised'" not in delivered

    manifest = json.loads(store.read_file("manifest.json"))
    assert manifest["gate"]["delivered"] == "notebook"
    assert manifest["gate"]["satisfied"] is True
    assert manifest["gate"]["delivered_quality"] == 100
    assert len(manifest["gate"]["candidates"]) == 2


def test_orchestrator_runs_revision_loop_until_good_enough(tmp_path):
    from forged.orchestrator import Orchestrator

    pipeline = load_pipeline(CONFIG_DIR / "pipeline.review-loop.yaml")
    runner = _scripted_runner_factory(
        notebook_markers={
            "notebook": "baseline",
            "revised_notebook__i1": "revision-1",
        },
        text_outputs={
            "lesson_plan": "plan",
            "student_feedback": _confusing(3),
            "reviewer_feedback": CLEAN_FEEDBACK,
            "student_feedback__i1": CLEAN_FEEDBACK,
            "reviewer_feedback__i1": CLEAN_FEEDBACK,
        },
        report_ok={
            "execution_report": True,
            "revised_execution_report__i1": True,
        },
    )

    runs_root = tmp_path / "runs"
    orch = Orchestrator(pipeline, tmp_path, runs_root, runner_factory=runner)
    store = orch.run("How a hash map works", "default.md", profile_label="learner.md")

    delivered = store.read_file("lesson.ipynb")
    assert "revision-1" in delivered
    assert "baseline" not in delivered

    manifest = json.loads(store.read_file("manifest.json"))
    assert manifest["status"] == "completed"
    assert manifest["gate"]["iterations"] == 2
    assert manifest["gate"]["delivered_iteration"] == 2
    assert manifest["gate"]["quality_scores"] == [85, 100]
    assert manifest["gate"]["satisfied"] is True

    summary = store.read_file("SUMMARY.md")
    assert "**Iterations:** 2" in summary
    assert "**Quality trend:** 85 → 100" in summary
    # Regression: the success path must pass timings to the summary, not just the
    # manifest — the README promises per-stage timing + total runtime in SUMMARY.md.
    assert "Total runtime" in summary


def _script_iterations(*, baseline_student, baseline_review, per_iter_student,
                       per_iter_review, max_iterations):
    """Build notebook_markers / text_outputs / report_ok dicts covering the baseline
    plus every revision iteration the full-budget loop may run."""
    notebook_markers = {"notebook": "baseline"}
    text_outputs = {
        "lesson_plan": "plan",
        "student_feedback": baseline_student,
        "reviewer_feedback": baseline_review,
    }
    report_ok = {"execution_report": True}
    for i in range(1, max_iterations + 1):
        notebook_markers[f"revised_notebook__i{i}"] = f"revision-{i}"
        text_outputs[f"student_feedback__i{i}"] = per_iter_student
        text_outputs[f"reviewer_feedback__i{i}"] = per_iter_review
        report_ok[f"revised_execution_report__i{i}"] = True
    return notebook_markers, text_outputs, report_ok


def test_orchestrator_hard_fails_when_crucial_issues_remain(tmp_path):
    from forged.orchestrator import Orchestrator

    pipeline = load_pipeline(CONFIG_DIR / "pipeline.review-loop.yaml")
    # Every iteration keeps the same BLOCKER → loop spends its full budget, then hard-fails.
    markers, texts, reports = _script_iterations(
        baseline_student=BLOCKER_FEEDBACK, baseline_review=CLEAN_FEEDBACK,
        per_iter_student=BLOCKER_FEEDBACK, per_iter_review=CLEAN_FEEDBACK,
        max_iterations=pipeline.revision.max_iterations,
    )
    runner = _scripted_runner_factory(
        notebook_markers=markers, text_outputs=texts, report_ok=reports,
    )

    runs_root = tmp_path / "runs"
    orch = Orchestrator(pipeline, tmp_path, runs_root, runner_factory=runner)

    with pytest.raises(RuntimeError, match="crucial issue still open"):
        orch.run("How a hash map works", "default.md", profile_label="learner.md")

    run_dir = next(runs_root.iterdir())
    manifest = json.loads((run_dir / "manifest.json").read_text())
    assert manifest["status"] == "failed"
    assert manifest["gate"]["crucial_open"] is True
    assert not (run_dir / "lesson.ipynb").exists()
    # P3: a failed run still leaves a human-readable summary, not just the manifest.
    assert (run_dir / "SUMMARY.md").exists()
    assert "NEEDS HUMAN REVIEW" in (run_dir / "SUMMARY.md").read_text()
    # last_run_dir is exposed for the CLI to surface, even on failure (#11).
    assert orch.last_run_dir == run_dir


def test_revision_loop_uses_full_budget_on_a_persistent_stall(tmp_path):
    # P1: with require_progress, a quality tie no longer aborts the loop after one round.
    # Every version sits at 85 (3 CONFUSING) — below the bar, never crucial — so the loop
    # should run all max_iterations rounds before shipping the least-bad version.
    from forged.orchestrator import Orchestrator

    pipeline = load_pipeline(CONFIG_DIR / "pipeline.review-loop.yaml")
    max_iter = pipeline.revision.max_iterations
    markers, texts, reports = _script_iterations(
        baseline_student=_confusing(3), baseline_review=CLEAN_FEEDBACK,
        per_iter_student=_confusing(3), per_iter_review=CLEAN_FEEDBACK,
        max_iterations=max_iter,
    )
    runner = _scripted_runner_factory(
        notebook_markers=markers, text_outputs=texts, report_ok=reports,
    )

    runs_root = tmp_path / "runs"
    orch = Orchestrator(pipeline, tmp_path, runs_root, runner_factory=runner)
    store = orch.run("How a hash map works", "default.md", profile_label="learner.md")

    manifest = json.loads(store.read_file("manifest.json"))
    # baseline + every iteration evaluated → full budget spent, not a single round.
    assert manifest["gate"]["iterations"] == max_iter + 1
    assert manifest["gate"]["satisfied"] is False
    assert manifest["gate"]["crucial_open"] is False
    # #8: timing is recorded for the whole run.
    assert "total_seconds" in manifest
    assert manifest["timings"]  # per-stage durations present


def test_summary_surfaces_quality_and_residual_issues(tmp_path):
    # Minor leftovers must be listed for the human, never silently buried.
    from forged.gate import evaluate_candidates as _eval
    from forged.report import build_summary

    store = ArtifactStore(tmp_path)
    _put_notebook(store, "notebook", "v = 1")
    _put_report(store, "execution_report", ok=True)
    _put_text(store, "student_feedback", _confusing(2))   # quality 90, 2 residuals

    pipeline = load_pipeline(CONFIG_DIR / "pipeline.skeleton.yaml")
    decision = _eval(pipeline, store)

    summary = build_summary(pipeline, store, "Topic", "default.md", decision)
    assert "## Acceptance" in summary
    assert "quality 90/100" in summary
    assert "Residual issues (2)" in summary


# ── Ledger (findings parsing + graded quality score) ─────────────────────────

from forged.ledger import (  # noqa: E402
    burden,
    has_blocker,
    parse_findings,
    quality_score,
)


def test_parse_findings_extracts_severity_and_cell():
    feedback = "[BLOCKER] cell 3 — wrong claim\nCONFUSING cell 7 — unclear\nVerdict: no."
    findings = parse_findings(feedback)
    assert [(f.severity, f.cell) for f in findings] == [("BLOCKER", 3), ("CONFUSING", 7)]


def test_parse_findings_ignores_prose_and_verdict_lines():
    # "no blockers" in prose must NOT register as a finding.
    feedback = "Overall this reads well, no blockers at all.\nVerdict: yes."
    assert parse_findings(feedback) == ()


def test_parse_findings_reads_structured_json_block():
        feedback = """Narrative summary here.

```json
{
    "quality_score": 75,
    "blockers": [],
    "findings": [
        {
            "source": "student",
            "severity": "CONFUSING",
            "scope": "cell",
            "location": {"type": "cell", "cell_index": 4, "label": null},
            "text": "Hash table explanation is too thin."
        },
        {
            "source": "student",
            "severity": "NITPICK",
            "scope": "notebook",
            "location": {"type": "notebook", "cell_index": null, "label": null},
            "text": "Needs a stronger capstone example."
        }
    ]
}
```
"""
        findings = parse_findings(feedback)
        assert [(f.severity, f.cell, f.text) for f in findings] == [
                ("CONFUSING", 4, "Hash table explanation is too thin."),
                ("NITPICK", None, "Needs a stronger capstone example."),
        ]


def test_quality_score_drops_with_severity_weight():
    assert quality_score(parse_findings("Verdict: clean.")) == 100
    assert quality_score(parse_findings("NITPICK cell 1 — typo.")) == 99
    assert quality_score(parse_findings("CONFUSING cell 1 — unclear.")) == 95
    assert quality_score(parse_findings("BLOCKER cell 1 — wrong.")) == 0


def test_quality_score_clamps_at_zero():
    feedback = "\n".join("BLOCKER cell 1 — wrong." for _ in range(3))
    assert burden(parse_findings(feedback)) == 300
    assert quality_score(parse_findings(feedback)) == 0


def test_has_blocker_detects_only_blocker_severity():
    assert has_blocker(parse_findings("BLOCKER cell 1 — wrong.")) is True
    assert has_blocker(parse_findings("CONFUSING cell 1 — unclear.")) is False


# ── Revision stages (P5: reviser anchored to the brief) ──────────────────────

def test_reviser_stage_receives_the_brief_as_input():
    from forged.orchestrator import Orchestrator

    pipeline = load_pipeline(CONFIG_DIR / "pipeline.review-loop.yaml")
    orch = Orchestrator(pipeline, Path("personas"), Path("runs"))
    stages = orch._build_revision_stages(
        policy=pipeline.revision, iteration=1,
        notebook_name="notebook", ledger_name="issue_ledger__i1",
    )
    reviser = stages[0]
    assert reviser.name == "reviser__i1"
    assert "brief" in reviser.inputs  # anchor to the original topic, not just the notebook


# ── CLI boundaries (#2 bad config, #3 empty topic, #4 honest exit code) ──────

def test_cli_rejects_empty_topic_without_running(capsys):
    from forged.cli import main

    rc = main(["build", "--topic", "   ", "--config", str(CONFIG_DIR / "pipeline.skeleton.yaml")])

    assert rc == 2  # usage error, before any API call
    assert "topic" in capsys.readouterr().err.lower()


def test_cli_reports_clean_error_for_missing_config(capsys, tmp_path):
    from forged.cli import main

    rc = main(["build", "--topic", "Hashing", "--config", str(tmp_path / "nope.yaml")])

    err = capsys.readouterr().err
    assert rc == 2
    assert "not found" in err.lower()
    assert "Traceback" not in err  # clean message, not a raw stack trace


def _write_manifest_with_gate(store, gate: dict) -> None:
    store.write_file("manifest.json", json.dumps({"gate": gate}))
    store.write_file("lesson.ipynb", "{}")
    store.write_file("SUMMARY.md", "# s")


def test_cli_exits_nonzero_when_crucial_issue_is_open(tmp_path):
    # #4: a notebook the gate marks crucial-open must NOT report success.
    from forged.cli import _report_outcome

    store = ArtifactStore(tmp_path)
    _write_manifest_with_gate(store, {"crucial_open": True, "satisfied": False})

    assert _report_outcome(store) == 1


def test_cli_warns_but_succeeds_below_quality_bar(tmp_path):
    from forged.cli import _report_outcome

    store = ArtifactStore(tmp_path)
    _write_manifest_with_gate(store, {"crucial_open": False, "satisfied": False})

    assert _report_outcome(store) == 0


def test_cli_reports_clean_success(tmp_path):
    from forged.cli import _report_outcome

    store = ArtifactStore(tmp_path)
    _write_manifest_with_gate(store, {"crucial_open": False, "satisfied": True})

    assert _report_outcome(store) == 0


def test_pipelines_command_lists_bundled_configs(capsys):
    from forged.cli import main

    rc = main(["pipelines"])

    out = capsys.readouterr().out
    assert rc == 0
    assert "skeleton" in out
    assert "review-loop" in out


# ── LLM client connection wiring (no network) ────────────────────────────────

def test_connection_kwargs_for_ollama_uses_placeholder_key(monkeypatch):
    from forged.config import Provider
    from forged.llm import DEFAULT_OLLAMA_BASE_URL, OLLAMA_PLACEHOLDER_KEY, _connection_kwargs

    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
    kwargs = _connection_kwargs(Provider.OLLAMA)

    assert kwargs == {"base_url": DEFAULT_OLLAMA_BASE_URL, "api_key": OLLAMA_PLACEHOLDER_KEY}


def test_connection_kwargs_for_ollama_honours_env_base_url(monkeypatch):
    from forged.config import Provider
    from forged.llm import _connection_kwargs

    monkeypatch.setenv("OLLAMA_BASE_URL", "http://example.test:9999/v1")
    assert _connection_kwargs(Provider.OLLAMA)["base_url"] == "http://example.test:9999/v1"


def test_connection_kwargs_for_openai_requires_a_key(monkeypatch):
    from forged.config import Provider
    from forged.llm import _connection_kwargs

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        _connection_kwargs(Provider.OPENAI)


def test_connection_kwargs_for_openai_passes_key_through(monkeypatch):
    from forged.config import Provider
    from forged.llm import _connection_kwargs

    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-123")
    assert _connection_kwargs(Provider.OPENAI) == {"api_key": "sk-test-123"}


# ── Executor: input contract + in-process fallback ───────────────────────────

def test_executor_rejects_more_than_one_input(tmp_path):
    from forged.config import StageConfig

    store = _store_with_notebook(tmp_path, ["x = 1"])
    stage = StageConfig(
        name="executor", type="executor", inputs=["notebook", "extra"], output="report"
    )
    with pytest.raises(ValueError, match="exactly one input"):
        ExecutorStage(stage).run(store)


def test_in_process_fallback_captures_stdout_and_errors(tmp_path):
    # The PermissionError fallback runs cells in-process; it must still capture a
    # cell's printed output and turn an exception into an error output (allow-errors
    # semantics), so the report stays truthful even without a kernel.
    import nbformat

    notebook = nbformat.reads(
        build_notebook([
            {"type": "code", "source": "print('hello fallback')"},
            {"type": "markdown", "source": "# skip me"},
            {"type": "code", "source": "raise ValueError('boom')"},
        ]),
        as_version=4,
    )

    ExecutorStage(_executor_stage())._execute_in_process(notebook)

    code_cells = [c for c in notebook.cells if c.cell_type == "code"]
    assert "hello fallback" in code_cells[0].outputs[0]["text"]
    assert code_cells[1].outputs[0]["output_type"] == "error"
    assert code_cells[1].outputs[0]["ename"] == "ValueError"


# ── Progress spinner (TTY-gated) ─────────────────────────────────────────────

class _FakeTTY(io.StringIO):
    """A writable stream that reports itself as interactive."""

    def isatty(self) -> bool:
        return True


def test_spinner_is_inactive_when_stream_is_not_a_tty():
    from forged.progress import Spinner

    stream = io.StringIO()  # StringIO.isatty() is False
    spinner = Spinner("planner", stream=stream).start()
    spinner.stop()

    assert spinner._active is False
    assert stream.getvalue() == ""  # no animation, nothing to clear


def test_spinner_animates_then_clears_on_a_tty():
    import time

    from forged.progress import FRAME_INTERVAL_SECONDS, SPINNER_FRAMES, Spinner

    stream = _FakeTTY()
    with Spinner("planner", stream=stream):
        time.sleep(FRAME_INTERVAL_SECONDS * 2)  # let at least one frame render

    output = stream.getvalue()
    assert any(frame in output for frame in SPINNER_FRAMES)  # animated
    assert output.endswith("\r\033[K")  # line cleared on exit


# ── LLMAgent prompt assembly + post-processing (no network) ──────────────────

def _ollama_agent(persona_dir: Path, *, output_kind: str):
    """An LLMAgent whose client targets Ollama, so construction needs no API key
    and no network call (the OpenAI SDK only connects on an actual request)."""
    from forged.agent import LLMAgent

    pipeline = PipelineConfig.model_validate({
        "name": "t",
        "defaults": {"provider": "ollama"},
        "stages": [{
            "name": "code_author", "persona": "code_author.md",
            "inputs": ["brief"], "output": "notebook", "output_kind": output_kind,
        }],
    })
    return LLMAgent(pipeline.stages[0], pipeline, persona_dir)


def test_agent_post_process_strips_text_output(tmp_path):
    agent = _ollama_agent(tmp_path, output_kind="text")
    assert agent._post_process("  spaced feedback  \n") == "spaced feedback"


def test_agent_post_process_assembles_notebook_from_json(tmp_path):
    agent = _ollama_agent(tmp_path, output_kind="notebook")
    raw = '[{"type": "markdown", "source": "# Title"}, {"type": "code", "source": "x = 1"}]'

    assembled = agent._post_process(raw)

    assert '"cell_type": "markdown"' in assembled
    assert '"cell_type": "code"' in assembled


def test_agent_user_prompt_delimits_inputs_and_indexes_notebooks(tmp_path):
    agent = _ollama_agent(tmp_path, output_kind="text")
    store = ArtifactStore(tmp_path)
    store.put(Artifact(name="brief", kind="text", content="Explain hashing"))
    store.put(Artifact(
        name="notebook", kind="notebook",
        content=build_notebook([{"type": "code", "source": "x = 1"}]),
    ))
    # The stage only declares 'brief'; point it at both to exercise notebook rendering.
    agent._stage = agent._stage.model_copy(update={"inputs": ["brief", "notebook"]})

    prompt = agent._build_user_prompt(store)

    assert '<artifact name="brief" kind="text">' in prompt
    assert "Explain hashing" in prompt
    assert '<artifact name="notebook" kind="notebook">' in prompt
    assert render_indexed(store.get("notebook").content) in prompt


# ── LLMClient.complete: success + error wrapping (fake client, no network) ────

def _llm_client_with_fake(create):
    """An LLMClient whose underlying OpenAI client is replaced by a fake. The Ollama
    provider lets the real client construct without a key; we then swap the transport."""
    from types import SimpleNamespace

    from forged.config import ModelConfig, Provider
    from forged.llm import LLMClient

    client = LLMClient(ModelConfig(provider=Provider.OLLAMA))
    client._client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create))
    )
    return client


def _completion(content):
    from types import SimpleNamespace

    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])


def test_llm_complete_returns_model_text():
    client = _llm_client_with_fake(lambda **_: _completion("the answer"))
    assert client.complete("sys", "user") == "the answer"


def test_llm_complete_wraps_api_errors_with_context():
    def boom(**_):
        raise ConnectionError("Connection error.")

    client = _llm_client_with_fake(boom)
    with pytest.raises(RuntimeError, match="LLM call failed.*ollama.*Connection error"):
        client.complete("sys", "user")


def test_llm_complete_rejects_empty_content():
    client = _llm_client_with_fake(lambda **_: _completion(""))
    with pytest.raises(RuntimeError, match="empty content"):
        client.complete("sys", "user")


def test_llm_complete_passes_response_format_to_openai_provider():
    from types import SimpleNamespace

    from forged.config import ModelConfig, Provider
    from forged.llm import LLMClient

    captured = {}

    def create(**kwargs):
        captured.update(kwargs)
        return _completion('{"ok": true}')

    client = LLMClient(ModelConfig(provider=Provider.OPENAI))
    client._client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create))
    )
    response_format = {
        "type": "json_schema",
        "json_schema": {
            "name": "demo",
            "strict": True,
            "schema": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    }

    assert client.complete("sys", "user", response_format=response_format) == '{"ok": true}'
    assert captured["response_format"] == response_format


def test_llm_complete_omits_response_format_for_ollama_provider():
    captured = {}

    def create(**kwargs):
        captured.update(kwargs)
        return _completion('{"ok": true}')

    client = _llm_client_with_fake(create)
    response_format = {
        "type": "json_schema",
        "json_schema": {
            "name": "demo",
            "strict": True,
            "schema": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    }

    assert client.complete("sys", "user", response_format=response_format) == '{"ok": true}'
    assert "response_format" not in captured


def test_llm_complete_records_trace_context_and_usage():
    from types import SimpleNamespace

    from forged.config import ModelConfig, Provider
    from forged.llm import LLMClient, LLMTraceContext

    class _FakeTracer:
        def __init__(self):
            self.started = None
            self.succeeded = None
            self.errored = None

        def start_generation(self, config, messages, trace_context):
            self.started = (config, messages, trace_context)
            return "observation"

        def record_success(self, observation, output, usage_details):
            self.succeeded = (observation, output, usage_details)

        def record_error(self, observation, message):
            self.errored = (observation, message)

    response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="the answer"))],
        usage=SimpleNamespace(prompt_tokens=11, completion_tokens=7, total_tokens=18),
    )
    client = LLMClient(ModelConfig(provider=Provider.OLLAMA, model="demo-model"))
    client._client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **_: response))
    )
    tracer = _FakeTracer()
    client._tracer = tracer
    trace_context = LLMTraceContext(
        stage_name="planner",
        pipeline_kind="agentic",
        run_id="run-123",
        run_dir="/tmp/run-123",
        iteration=2,
    )

    result = client.complete("sys", "user", trace_context=trace_context)

    assert result == "the answer"
    assert tracer.started is not None
    assert tracer.started[1] == [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "user"},
    ]
    assert tracer.started[2] == trace_context
    assert tracer.succeeded == (
        "observation",
        "the answer",
        {"input": 11, "output": 7, "total": 18},
    )
    assert tracer.errored is None


def test_llm_complete_works_without_langfuse_credentials(monkeypatch):
    from forged.config import ModelConfig, Provider
    from forged.llm import _LangfuseTracer

    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_HOST", raising=False)
    monkeypatch.delenv("LANGFUSE_BASE_URL", raising=False)

    client = _llm_client_with_fake(lambda **_: _completion("the answer"))
    client._config = ModelConfig(provider=Provider.OLLAMA)
    client._tracer = _LangfuseTracer()

    assert client.complete("sys", "user") == "the answer"


# ── LLMAgent.run + persona loading (fake client, no network) ─────────────────

def test_agent_load_persona_raises_for_missing_file(tmp_path):
    agent = _ollama_agent(tmp_path, output_kind="text")  # tmp_path has no persona files
    with pytest.raises(FileNotFoundError, match="Persona file for stage 'code_author'"):
        agent._load_persona()


def test_agent_run_writes_processed_output_to_store(tmp_path):
    persona_dir = tmp_path / "personas"
    persona_dir.mkdir()
    (persona_dir / "code_author.md").write_text("You are the author.", encoding="utf-8")

    agent = _ollama_agent(persona_dir, output_kind="text")
    agent._client = _llm_client_with_fake(lambda **_: _completion("  drafted lesson  "))

    store = ArtifactStore(tmp_path)
    store.put(Artifact(name="brief", kind="text", content="Explain hashing"))

    artifact = agent.run(store)

    assert artifact.content == "drafted lesson"  # post-processed (stripped)
    assert store.get("notebook").content == "drafted lesson"  # persisted under stage output


# ── CLI helpers (header, profile loading, stage reporter, .env) ───────────────

def test_build_header_advertises_revision_rounds():
    from forged.cli import _build_header

    pipeline = load_pipeline(CONFIG_DIR / "pipeline.review-loop.yaml")
    header = _build_header(pipeline, "learner.md")

    assert "review-loop" in header
    assert "revision round(s)" in header  # honest about the bounded extra rounds
    assert "learner.md" in header


def test_build_header_for_a_linear_pipeline_counts_stages():
    from forged.cli import _build_header

    pipeline = load_pipeline(CONFIG_DIR / "pipeline.skeleton.yaml")
    assert "stage(s)" in _build_header(pipeline, "default.md")


def test_stage_reporter_prints_done_and_error_lines(capsys):
    from forged.cli import _StageReporter

    reporter = _StageReporter()
    reporter("planner", "start", "llm")   # spinner inactive under captured (non-TTY) stdout
    reporter("planner", "done", "lesson_plan.md  (1.2s)")
    reporter("executor", "error", "boom")

    out = capsys.readouterr().out
    assert "✓ planner  → lesson_plan.md  (1.2s)" in out
    assert "✗ executor  → boom" in out


def test_load_dotenv_sets_only_absent_keys(tmp_path, monkeypatch):
    from forged.cli import _load_dotenv

    env_file = tmp_path / ".env"
    env_file.write_text('NEW_KEY="from-file"\nEXISTING=should-not-win\n', encoding="utf-8")
    monkeypatch.delenv("NEW_KEY", raising=False)
    monkeypatch.setenv("EXISTING", "already-set")

    _load_dotenv(env_file)

    import os
    assert os.environ["NEW_KEY"] == "from-file"      # absent key loaded (quotes stripped)
    assert os.environ["EXISTING"] == "already-set"   # never overrides the environment
