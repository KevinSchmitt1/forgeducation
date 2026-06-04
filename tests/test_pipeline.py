"""Offline tests — no network, no API key required.

These cover the architecture's load-bearing parts:
  * pipeline config loads and validates (and rejects broken dataflow)
  * notebook assembly from the model's JSON cell format
  * the executor actually runs a notebook AND flags a failing cell

Run from the repo root:  pytest -q
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from eduforge.artifacts import Artifact, ArtifactStore
from eduforge.config import PipelineConfig, load_pipeline
from eduforge.executor import ExecutorStage
from eduforge.notebook import build_notebook, cells_from_json, render_indexed

CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"


# ── Config ───────────────────────────────────────────────────────────────────

def test_skeleton_config_loads_expected_stages():
    pipeline = load_pipeline(CONFIG_DIR / "pipeline.skeleton.yaml")
    assert pipeline.name == "skeleton"
    assert [s.name for s in pipeline.stages] == [
        "planner", "code_author", "executor", "student",
    ]


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
    # The loop re-runs and re-checks the revised notebook.
    assert "reviser" in names
    assert names.index("executor_revised") > names.index("reviser")
    assert names.index("student_revised") > names.index("executor_revised")


# ── Executor (the anti-bug layer) ────────────────────────────────────────────

def _store_with_notebook(tmp_path: Path, sources: list[str]) -> ArtifactStore:
    store = ArtifactStore(tmp_path)
    cells = [{"type": "code", "source": s} for s in sources]
    store.put(Artifact(name="notebook", kind="notebook", content=build_notebook(cells)))
    return store


def _executor_stage():
    from eduforge.config import StageConfig

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
    from eduforge.config import PipelineConfig
    from eduforge.report import build_summary

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


def test_clean_keeps_newest_runs(tmp_path):
    from argparse import Namespace

    from eduforge.cli import _cmd_clean

    runs = tmp_path / "runs"
    runs.mkdir()
    for stamp in ["20260101-000000_x", "20260102-000000_x", "20260103-000000_x"]:
        (runs / stamp).mkdir()

    _cmd_clean(Namespace(keep=2, runs=str(runs)))

    remaining = sorted(p.name for p in runs.iterdir())
    assert remaining == ["20260102-000000_x", "20260103-000000_x"]


# ── Acceptance gate (graded keep-best) ───────────────────────────────────────
#
# The gate links each notebook version to the executor report that ran it and the
# critiques grounded on that report. Quality is GRADED (a 0–100 score from the
# findings), facts are BINARY (a crashing cell or a BLOCKER is a hard floor). It
# keeps the BEST version: prefer no crucial issue, then higher quality, then earliest
# — so a revision is adopted only when it genuinely improves the lesson.

from eduforge.executor import executed_notebook_filename  # noqa: E402
from eduforge.gate import evaluate_candidates, notebook_candidates  # noqa: E402


def _review_loop_pipeline() -> PipelineConfig:
    return load_pipeline(CONFIG_DIR / "pipeline.review-loop.yaml")


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
    from eduforge.orchestrator import Orchestrator

    store = ArtifactStore(tmp_path)
    _populate_review_loop(store, orig_ok=True, orig_fb=CLEAN_FEEDBACK,
                          revised_ok=False, revised_fb=BLOCKER_FEEDBACK)
    # The executor writes an executed-with-outputs notebook per version on disk.
    store.write_file(executed_notebook_filename("execution_report"),
                     build_notebook([{"type": "code", "source": "v = 'original'"}]))
    store.write_file(executed_notebook_filename("revised_execution_report"),
                     build_notebook([{"type": "code", "source": "v = 'revised'"}]))

    orch = Orchestrator(_review_loop_pipeline(), tmp_path, tmp_path)
    orch._finalize(store, "Some topic", "default.md")

    delivered = store.read_file("lesson.ipynb")
    assert "v = 'original'" in delivered
    assert "v = 'revised'" not in delivered

    manifest = json.loads(store.read_file("manifest.json"))
    assert manifest["gate"]["delivered"] == "notebook"
    assert manifest["gate"]["satisfied"] is True
    assert manifest["gate"]["delivered_quality"] == 100
    assert len(manifest["gate"]["candidates"]) == 2


def test_summary_surfaces_quality_and_residual_issues(tmp_path):
    # Minor leftovers must be listed for the human, never silently buried.
    from eduforge.gate import evaluate_candidates as _eval
    from eduforge.report import build_summary

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

from eduforge.ledger import (  # noqa: E402
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
