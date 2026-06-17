"""Unit tests for the ExecutorAgent's provisioning hook (Phase 5).

When provision=True the executor builds/reuses a venv from the plan's requirements and
runs the notebook against that kernel. These tests patch provision_environment (no real
venv/pip) and ExecutorStage (no real kernel) to assert the wiring: the provisioned
kernel is threaded into execution, and a provisioning failure terminates the run
honestly (ok=False) instead of producing a green-but-hollow notebook.

Run with:
    pytest tests/pipeline/test_executor_provisioning.py -v
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import nbformat
import pytest

from forged.artifacts import Artifact, ArtifactStore
from forged.pipeline.agents.executor import ExecutorAgent
from forged.pipeline.state import PipelineStage, PipelineState, StageOutput, create_initial_state
from forged.provisioning import ProvisionResult


@pytest.fixture
def store(tmp_path: Path) -> ArtifactStore:
    run_dir = tmp_path / "runs" / "run-1"
    run_dir.mkdir(parents=True)
    return ArtifactStore(run_dir)


def _seed_plan_and_notebook(store: ArtifactStore, requirements_block: str = "") -> None:
    plan = f"## Prerequisites\nstuff\n{requirements_block}\n## Learning objectives\n- x\n"
    store.put(Artifact(name="lesson_plan_v0", kind="text", content=plan))
    nb = nbformat.v4.new_notebook()
    nb.cells = [nbformat.v4.new_code_cell("print(1)")]
    store.put(Artifact(name="lesson_notebook_v0", kind="notebook", content=nbformat.writes(nb)))


def _state() -> PipelineState:
    s = create_initial_state(run_id="exec-prov")
    s = s.with_output(StageOutput(PipelineStage.PLANNER, "lesson_plan_v0", 0))
    s = s.with_output(StageOutput(PipelineStage.CODE_AUTHOR, "lesson_notebook_v0", 0))
    return s.with_current_stage(PipelineStage.EXECUTOR)


def _agent(personas_dir: Path | None = None) -> ExecutorAgent:
    return ExecutorAgent(personas_dir=None, provision=True)


class _StubExecutorStage:
    """Captures the kernel passed via StageConfig and returns a clean report."""

    captured_kernel: str | None = None

    def __init__(self, stage):
        type(self).captured_kernel = stage.params.get("kernel")
        self._stage = stage

    def run(self, store):
        report = {"ok": True, "executed_notebook": "x", "cells": []}
        return store.put(Artifact(name=self._stage.output, kind="json", content=json.dumps(report)))


def test_provisioned_kernel_is_threaded_into_execution(monkeypatch, store, tmp_path):
    _seed_plan_and_notebook(store, "```requirements\nnumpy>=1.26\n```")

    def fake_provision(requirement_set, **kwargs):
        return ProvisionResult(
            ok=True, requirements_hash="h", kernel_name="forged-abc", cache_hit=True
        )

    monkeypatch.setattr("forged.provisioning.provision_environment", fake_provision)
    monkeypatch.setattr("forged.pipeline.agents.executor.ExecutorStage", _StubExecutorStage)

    result = asyncio.run(_agent().run(_state(), store))

    assert _StubExecutorStage.captured_kernel == "forged-abc"
    assert result.current_stage == PipelineStage.STUDENT
    assert not result.is_terminal


def test_no_requirements_runs_on_base_kernel(monkeypatch, store):
    _seed_plan_and_notebook(store, requirements_block="")  # no deps

    def fake_provision(requirement_set, **kwargs):
        # Mirror real behaviour: empty deps → base kernel.
        return ProvisionResult(ok=True, requirements_hash="h", kernel_name=None)

    monkeypatch.setattr("forged.provisioning.provision_environment", fake_provision)
    monkeypatch.setattr("forged.pipeline.agents.executor.ExecutorStage", _StubExecutorStage)

    asyncio.run(_agent().run(_state(), store))

    assert _StubExecutorStage.captured_kernel == "python3"  # DEFAULT_KERNEL


def test_provision_failure_terminates_run_honestly(monkeypatch, store):
    _seed_plan_and_notebook(store, "```requirements\nnumpy>=1.26\n```")

    def fake_provision(requirement_set, **kwargs):
        return ProvisionResult(
            ok=False, requirements_hash="h", kernel_name=None, error="could not install numpy"
        )

    monkeypatch.setattr("forged.provisioning.provision_environment", fake_provision)
    # ExecutorStage must NOT run when provisioning failed.
    monkeypatch.setattr(
        "forged.pipeline.agents.executor.ExecutorStage",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("executor should not run")),
    )

    result = asyncio.run(_agent().run(_state(), store))

    assert result.is_terminal
    assert result.terminal_ok is False
    assert "provisioning failed" in (result.terminal_reason or "").lower()
    # The failure is recorded honestly and a report exists for the summary.
    assert any(d.kind == "provision_failed" for d in result.degradations)
    assert store.has("execution_report_v0")
    assert json.loads(store.get("execution_report_v0").content)["ok"] is False


def test_provisioning_off_by_default_skips_provision(monkeypatch, store):
    _seed_plan_and_notebook(store, "```requirements\nnumpy>=1.26\n```")

    def boom(*a, **k):
        raise AssertionError("provision_environment must not be called when provision=False")

    monkeypatch.setattr("forged.provisioning.provision_environment", boom)
    monkeypatch.setattr("forged.pipeline.agents.executor.ExecutorStage", _StubExecutorStage)

    # Default agent: provision is off.
    result = asyncio.run(ExecutorAgent(personas_dir=None).run(_state(), store))

    assert result.current_stage == PipelineStage.STUDENT
    assert _StubExecutorStage.captured_kernel == "python3"
