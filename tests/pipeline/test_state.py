"""Unit tests for the pipeline state schema.

Tests verify immutability, builder correctness, validation,
and query methods — all without LLM or LangGraph dependencies.
"""

from __future__ import annotations

import pytest

from forged.pipeline.state import (
    Evidence,
    Location,
    LocationType,
    PipelineStage,
    PipelineState,
    RoutingDecision,
    StageOutput,
    create_initial_state,
)

# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def initial_state() -> PipelineState:
    return create_initial_state(run_id="test-run-001")


@pytest.fixture
def cell_location() -> Location:
    return Location(type=LocationType.CELL, cell_index=3, label="hash function")


@pytest.fixture
def global_location() -> Location:
    return Location(type=LocationType.GLOBAL)


@pytest.fixture
def sample_evidence(cell_location: Location) -> Evidence:
    return Evidence(
        source="executor_report",
        severity="BLOCKER",
        scope="code",
        location=cell_location,
        text="NameError: name 'x' is not defined",
    )


@pytest.fixture
def sample_output() -> StageOutput:
    return StageOutput(
        stage=PipelineStage.PLANNER,
        artifact_name="lesson_plan_v0.md",
        iteration=0,
    )


@pytest.fixture
def sample_routing_decision(sample_evidence: Evidence) -> RoutingDecision:
    return RoutingDecision(
        iteration=0,
        from_stage=PipelineStage.REVISER,
        to_stage=PipelineStage.CODE_AUTHOR,
        classification="code_quality",
        reason="Code failed to execute",
        evidence=[sample_evidence],
    )


# ── State initialization ──────────────────────────────────────────────────────


@pytest.mark.unit
def test_create_initial_state_sets_planner_stage():
    state = create_initial_state()
    assert state.current_stage == PipelineStage.PLANNER


@pytest.mark.unit
def test_create_initial_state_starts_at_iteration_zero():
    state = create_initial_state()
    assert state.iteration == 0


@pytest.mark.unit
def test_create_initial_state_has_empty_collections():
    state = create_initial_state()
    assert state.outputs == []
    assert state.stage_attempts == {}
    assert state.routing_log == []


@pytest.mark.unit
def test_create_initial_state_is_not_terminal():
    state = create_initial_state()
    assert state.is_terminal is False
    assert state.terminal_reason is None


@pytest.mark.unit
def test_create_initial_state_generates_run_id_when_none():
    state = create_initial_state()
    assert state.run_id is not None
    assert len(state.run_id) > 0


@pytest.mark.unit
def test_create_initial_state_uses_provided_run_id():
    state = create_initial_state(run_id="my-run-123")
    assert state.run_id == "my-run-123"


@pytest.mark.unit
def test_two_initial_states_without_run_id_have_different_run_ids():
    s1 = create_initial_state()
    s2 = create_initial_state()
    assert s1.run_id != s2.run_id


# ── Immutability ──────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_with_current_stage_returns_new_instance(initial_state: PipelineState):
    new_state = initial_state.with_current_stage(PipelineStage.CODE_AUTHOR)
    assert new_state is not initial_state


@pytest.mark.unit
def test_with_current_stage_does_not_mutate_original(initial_state: PipelineState):
    initial_state.with_current_stage(PipelineStage.CODE_AUTHOR)
    assert initial_state.current_stage == PipelineStage.PLANNER


@pytest.mark.unit
def test_with_current_stage_updates_new_state(initial_state: PipelineState):
    new_state = initial_state.with_current_stage(PipelineStage.CODE_AUTHOR)
    assert new_state.current_stage == PipelineStage.CODE_AUTHOR


@pytest.mark.unit
def test_with_output_returns_new_instance(initial_state: PipelineState, sample_output: StageOutput):
    new_state = initial_state.with_output(sample_output)
    assert new_state is not initial_state


@pytest.mark.unit
def test_with_output_does_not_mutate_original_list(
    initial_state: PipelineState, sample_output: StageOutput
):
    initial_state.with_output(sample_output)
    assert initial_state.outputs == []


@pytest.mark.unit
def test_with_output_appends_to_outputs(
    initial_state: PipelineState, sample_output: StageOutput
):
    new_state = initial_state.with_output(sample_output)
    assert len(new_state.outputs) == 1
    assert new_state.outputs[0] == sample_output


@pytest.mark.unit
def test_with_output_accumulates_multiple_outputs(
    initial_state: PipelineState,
):
    out1 = StageOutput(stage=PipelineStage.PLANNER, artifact_name="plan.md", iteration=0)
    out2 = StageOutput(stage=PipelineStage.CODE_AUTHOR, artifact_name="nb.ipynb", iteration=0)

    state = initial_state.with_output(out1).with_output(out2)

    assert len(state.outputs) == 2
    assert state.outputs[0] == out1
    assert state.outputs[1] == out2


@pytest.mark.unit
def test_with_routing_decision_returns_new_instance(
    initial_state: PipelineState, sample_routing_decision: RoutingDecision
):
    new_state = initial_state.with_routing_decision(sample_routing_decision)
    assert new_state is not initial_state


@pytest.mark.unit
def test_with_routing_decision_appends_to_routing_log(
    initial_state: PipelineState, sample_routing_decision: RoutingDecision
):
    new_state = initial_state.with_routing_decision(sample_routing_decision)
    assert len(new_state.routing_log) == 1
    assert new_state.routing_log[0] == sample_routing_decision


@pytest.mark.unit
def test_with_routing_decision_increments_iteration(
    initial_state: PipelineState, sample_routing_decision: RoutingDecision
):
    assert initial_state.iteration == 0
    new_state = initial_state.with_routing_decision(sample_routing_decision)
    assert new_state.iteration == 1


@pytest.mark.unit
def test_with_routing_decision_does_not_mutate_original_log(
    initial_state: PipelineState, sample_routing_decision: RoutingDecision
):
    initial_state.with_routing_decision(sample_routing_decision)
    assert initial_state.routing_log == []


@pytest.mark.unit
def test_with_attempt_increments_counter(initial_state: PipelineState):
    new_state = initial_state.with_attempt(PipelineStage.CODE_AUTHOR)
    assert new_state.get_stage_attempt_count(PipelineStage.CODE_AUTHOR) == 1


@pytest.mark.unit
def test_with_attempt_accumulates_for_same_stage(initial_state: PipelineState):
    state = initial_state.with_attempt(PipelineStage.CODE_AUTHOR)
    state = state.with_attempt(PipelineStage.CODE_AUTHOR)
    assert state.get_stage_attempt_count(PipelineStage.CODE_AUTHOR) == 2


@pytest.mark.unit
def test_with_attempt_does_not_mutate_original_dict(initial_state: PipelineState):
    initial_state.with_attempt(PipelineStage.CODE_AUTHOR)
    assert initial_state.stage_attempts == {}


@pytest.mark.unit
def test_with_attempt_tracks_different_stages_independently(initial_state: PipelineState):
    state = initial_state.with_attempt(PipelineStage.PLANNER)
    state = state.with_attempt(PipelineStage.CODE_AUTHOR)
    state = state.with_attempt(PipelineStage.CODE_AUTHOR)

    assert state.get_stage_attempt_count(PipelineStage.PLANNER) == 1
    assert state.get_stage_attempt_count(PipelineStage.CODE_AUTHOR) == 2


@pytest.mark.unit
def test_with_terminal_marks_state_as_terminal(initial_state: PipelineState):
    new_state = initial_state.with_terminal("acceptable")
    assert new_state.is_terminal is True


@pytest.mark.unit
def test_with_terminal_records_reason(initial_state: PipelineState):
    new_state = initial_state.with_terminal("budget_exhausted")
    assert new_state.terminal_reason == "budget_exhausted"


@pytest.mark.unit
def test_with_terminal_does_not_mutate_original(initial_state: PipelineState):
    initial_state.with_terminal("acceptable")
    assert initial_state.is_terminal is False
    assert initial_state.terminal_reason is None


@pytest.mark.unit
def test_with_terminal_returns_new_instance(initial_state: PipelineState):
    new_state = initial_state.with_terminal("unclassifiable")
    assert new_state is not initial_state


# ── Validation ────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_location_cell_requires_index():
    with pytest.raises(ValueError, match="CELL location must have cell_index"):
        Location(type=LocationType.CELL)


@pytest.mark.unit
def test_location_cell_with_index_is_valid():
    loc = Location(type=LocationType.CELL, cell_index=0)
    assert loc.cell_index == 0


@pytest.mark.unit
def test_location_non_cell_rejects_index():
    with pytest.raises(ValueError, match="should not have cell_index"):
        Location(type=LocationType.GLOBAL, cell_index=5)


@pytest.mark.unit
def test_location_section_without_index_is_valid():
    loc = Location(type=LocationType.SECTION, label="Introduction")
    assert loc.cell_index is None


@pytest.mark.unit
def test_location_lesson_structure_without_index_is_valid():
    loc = Location(type=LocationType.LESSON_STRUCTURE)
    assert loc.type == LocationType.LESSON_STRUCTURE


@pytest.mark.unit
def test_state_rejects_negative_iteration():
    with pytest.raises(ValueError, match="iteration must be >= 0"):
        PipelineState(
            run_id="test",
            current_stage=PipelineStage.PLANNER,
            iteration=-1,
        )


@pytest.mark.unit
def test_state_rejects_invalid_current_stage_type():
    with pytest.raises(TypeError, match="current_stage must be PipelineStage"):
        PipelineState(
            run_id="test",
            current_stage="planner",  # type: ignore[arg-type]
            iteration=0,
        )


@pytest.mark.unit
def test_state_accepts_zero_iteration():
    state = PipelineState(
        run_id="test",
        current_stage=PipelineStage.PLANNER,
        iteration=0,
    )
    assert state.iteration == 0


# ── Query methods ─────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_get_stage_attempt_count_returns_zero_for_unvisited_stage(initial_state: PipelineState):
    assert initial_state.get_stage_attempt_count(PipelineStage.PLANNER) == 0


@pytest.mark.unit
def test_get_stage_attempt_count_returns_correct_count(initial_state: PipelineState):
    state = initial_state.with_attempt(PipelineStage.PLANNER)
    assert state.get_stage_attempt_count(PipelineStage.PLANNER) == 1


@pytest.mark.unit
def test_last_routing_to_stage_returns_none_when_no_routing(initial_state: PipelineState):
    assert initial_state.last_routing_to_stage(PipelineStage.CODE_AUTHOR) is None


@pytest.mark.unit
def test_last_routing_to_stage_returns_most_recent_decision(
    initial_state: PipelineState,
    sample_evidence: Evidence,
):
    decision1 = RoutingDecision(
        iteration=0,
        from_stage=PipelineStage.REVISER,
        to_stage=PipelineStage.CODE_AUTHOR,
        classification="code_quality",
        reason="First failure",
        evidence=[sample_evidence],
    )
    decision2 = RoutingDecision(
        iteration=1,
        from_stage=PipelineStage.REVISER,
        to_stage=PipelineStage.CODE_AUTHOR,
        classification="code_quality",
        reason="Second failure",
        evidence=[],
    )

    state = initial_state.with_routing_decision(decision1).with_routing_decision(decision2)

    result = state.last_routing_to_stage(PipelineStage.CODE_AUTHOR)
    assert result == decision2
    assert result.reason == "Second failure"


@pytest.mark.unit
def test_last_routing_to_stage_ignores_decisions_for_other_stages(
    initial_state: PipelineState,
):
    decision = RoutingDecision(
        iteration=0,
        from_stage=PipelineStage.REVISER,
        to_stage=PipelineStage.PLANNER,
        classification="blocker_structure",
        reason="Structure problem",
        evidence=[],
    )

    state = initial_state.with_routing_decision(decision)

    assert state.last_routing_to_stage(PipelineStage.CODE_AUTHOR) is None
    assert state.last_routing_to_stage(PipelineStage.PLANNER) == decision


# ── RoutingDecision: unique timestamps ────────────────────────────────────────


@pytest.mark.unit
def test_routing_decision_timestamp_is_unique():
    d1 = RoutingDecision(
        iteration=0,
        from_stage=PipelineStage.REVISER,
        to_stage=PipelineStage.PLANNER,
        classification="blocker_structure",
        reason="r1",
    )
    d2 = RoutingDecision(
        iteration=1,
        from_stage=PipelineStage.REVISER,
        to_stage=PipelineStage.CODE_AUTHOR,
        classification="code_quality",
        reason="r2",
    )
    assert d1.timestamp != d2.timestamp


# ── Frozen dataclass checks ────────────────────────────────────────────────────


@pytest.mark.unit
def test_location_is_immutable(cell_location: Location):
    with pytest.raises((TypeError, AttributeError)):
        cell_location.cell_index = 99  # type: ignore[misc]


@pytest.mark.unit
def test_evidence_is_immutable(sample_evidence: Evidence, cell_location: Location):
    with pytest.raises((TypeError, AttributeError)):
        sample_evidence.text = "modified"  # type: ignore[misc]


@pytest.mark.unit
def test_stage_output_is_immutable(sample_output: StageOutput):
    with pytest.raises((TypeError, AttributeError)):
        sample_output.artifact_name = "hacked.md"  # type: ignore[misc]


@pytest.mark.unit
def test_routing_decision_is_immutable(sample_routing_decision: RoutingDecision):
    with pytest.raises((TypeError, AttributeError)):
        sample_routing_decision.reason = "mutated"  # type: ignore[misc]
