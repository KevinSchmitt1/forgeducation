"""The provisioning preflight — prove the environment BEFORE the expensive author pass.

Provisioning used to happen only inside the ExecutorAgent, i.e. *after* the gpt-5
CodeAuthor had already written a notebook. A refusable environment therefore threw away
the most expensive stage of the run — which is exactly what both 2026-07-30 paid course
runs did (see docs/architecture/18-*.md). The gate runs the same provisioning attempt
immediately after the planner (gpt-5-mini), so an unbuildable environment costs one cheap
call instead of a full notebook.

This is a *timing* change, not a policy one: the gate applies no allow-list and refuses no
package. It only moves the moment we find out pip cannot build what the plan asked for.

Run with:
    pytest tests/pipeline/test_provision_gate.py -v
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from forged.artifacts import Artifact, ArtifactStore
from forged.config import PipelineConfig, load_pipeline
from forged.pipeline.state import (
    PipelineStage,
    PipelineState,
    StageOutput,
    create_initial_state,
)
from forged.provisioning import ProvisionResult

REQUIREMENTS_BLOCK = "```requirements\nnumpy>=1.26\n```"


@pytest.fixture
def store(tmp_path: Path) -> ArtifactStore:
    run_dir = tmp_path / "runs" / "run-1"
    run_dir.mkdir(parents=True)
    return ArtifactStore(run_dir)


@pytest.fixture
def personas_dir(tmp_path: Path) -> Path:
    d = tmp_path / "personas"
    d.mkdir()
    for name in ("planner", "code_author", "student", "reviewer", "reviser"):
        (d / f"{name}.md").write_text(f"Persona for {name}.", encoding="utf-8")
    return d


@pytest.fixture
def pipeline_config() -> PipelineConfig:
    config_path = Path(__file__).resolve().parents[2] / "config" / "pipeline.review-loop.yaml"
    return load_pipeline(config_path)


def _seed_plan(store: ArtifactStore, requirements_block: str = REQUIREMENTS_BLOCK) -> None:
    plan = f"## Prerequisites\nstuff\n{requirements_block}\n## Learning objectives\n- x\n"
    store.put(Artifact(name="lesson_plan_v0", kind="text", content=plan))


def _planned_state() -> PipelineState:
    state = create_initial_state(run_id="gate-1")
    state = state.with_output(StageOutput(PipelineStage.PLANNER, "lesson_plan_v0", 0))
    return state.with_current_stage(PipelineStage.CODE_AUTHOR)


def _failing(*_args, **_kwargs) -> ProvisionResult:
    return ProvisionResult(
        ok=False, requirements_hash="h", kernel_name=None, error="pip could not resolve numpy"
    )


def _succeeding(*_args, **_kwargs) -> ProvisionResult:
    return ProvisionResult(ok=True, requirements_hash="h", kernel_name="forged-abc")


# ── The extracted gate function ────────────────────────────────────────────────


@pytest.mark.unit
def test_gate_returns_terminal_state_when_provisioning_fails(monkeypatch, store) -> None:
    from forged.pipeline.provision_gate import provision_for_state

    monkeypatch.setattr("forged.provisioning.provision_environment", _failing)
    _seed_plan(store)

    outcome = provision_for_state(_planned_state(), store)

    assert outcome.terminal_state is not None
    assert outcome.terminal_state.is_terminal
    assert outcome.terminal_state.terminal_ok is False
    kinds = [d.kind for d in outcome.terminal_state.degradations]
    assert "provision_failed" in kinds


@pytest.mark.unit
def test_gate_failure_writes_an_honest_execution_report(monkeypatch, store) -> None:
    """A learner reading the run must see *why* it stopped, not an absent report."""
    from forged.pipeline.provision_gate import provision_for_state

    monkeypatch.setattr("forged.provisioning.provision_environment", _failing)
    _seed_plan(store)

    provision_for_state(_planned_state(), store)

    report = json.loads(store.get("execution_report_v0").content)
    assert report["ok"] is False
    assert "pip could not resolve numpy" in report["error_summary"]


@pytest.mark.unit
def test_gate_returns_the_provisioned_kernel_on_success(monkeypatch, store) -> None:
    from forged.pipeline.provision_gate import provision_for_state

    monkeypatch.setattr("forged.provisioning.provision_environment", _succeeding)
    _seed_plan(store)

    outcome = provision_for_state(_planned_state(), store)

    assert outcome.terminal_state is None
    assert outcome.kernel == "forged-abc"


@pytest.mark.unit
def test_gate_falls_back_to_the_base_kernel_when_no_deps_are_needed(monkeypatch, store) -> None:
    from forged.executor import DEFAULT_KERNEL
    from forged.pipeline.provision_gate import provision_for_state

    monkeypatch.setattr(
        "forged.provisioning.provision_environment",
        lambda *a, **k: ProvisionResult(ok=True, requirements_hash="h", kernel_name=None),
    )
    _seed_plan(store, requirements_block="")

    outcome = provision_for_state(_planned_state(), store)

    assert outcome.terminal_state is None
    assert outcome.kernel == DEFAULT_KERNEL


# ── Graph wiring ───────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_gate_node_is_absent_when_provisioning_is_disabled(
    store, personas_dir, pipeline_config
) -> None:
    from forged.pipeline.graph import build_pipeline_graph

    graph = build_pipeline_graph(
        store=store, pipeline=pipeline_config, personas_dir=personas_dir, provision=False
    )

    assert "provision_gate" not in set(graph.get_graph().nodes.keys())
    pairs = {(e.source, e.target) for e in graph.get_graph().edges}
    assert ("planner", "code_author") in pairs


@pytest.mark.unit
def test_gate_node_sits_between_planner_and_code_author_when_enabled(
    store, personas_dir, pipeline_config
) -> None:
    from forged.pipeline.graph import build_pipeline_graph

    graph = build_pipeline_graph(
        store=store, pipeline=pipeline_config, personas_dir=personas_dir, provision=True
    )

    assert "provision_gate" in set(graph.get_graph().nodes.keys())
    pairs = {(e.source, e.target) for e in graph.get_graph().edges}
    assert ("planner", "provision_gate") in pairs
    assert ("provision_gate", "code_author") in pairs
    # The expensive stage must not be reachable directly from the planner any more.
    assert ("planner", "code_author") not in pairs


@pytest.mark.integration
def test_failed_provisioning_never_reaches_the_code_author(
    monkeypatch, store, personas_dir, pipeline_config
) -> None:
    """The whole point: a broken environment must not cost a gpt-5 notebook."""
    from forged.pipeline.agents.code_author import CodeAuthorAgent
    from forged.pipeline.agents.planner import PlannerAgent
    from forged.pipeline.graph import run_pipeline

    authored: list[str] = []

    async def _fake_planner(self, state: PipelineState, store: ArtifactStore) -> PipelineState:
        _seed_plan(store)
        return state.with_output(
            StageOutput(PipelineStage.PLANNER, "lesson_plan_v0", state.iteration)
        ).with_current_stage(PipelineStage.CODE_AUTHOR)

    async def _fake_code_author(
        self, state: PipelineState, store: ArtifactStore
    ) -> PipelineState:
        authored.append("called")
        return state

    monkeypatch.setattr(PlannerAgent, "run", _fake_planner)
    monkeypatch.setattr(CodeAuthorAgent, "run", _fake_code_author)
    monkeypatch.setattr("forged.provisioning.provision_environment", _failing)

    final = asyncio.run(
        run_pipeline(
            create_initial_state(run_id="gate-e2e"),
            store=store,
            pipeline=pipeline_config,
            personas_dir=personas_dir,
            provision=True,
        )
    )

    assert authored == [], "CodeAuthor ran despite an unprovisionable environment"
    assert final.is_terminal
    assert final.terminal_ok is False
