"""LangGraph assembly for the agentic pipeline.

Wires the five agents (Planner, CodeAuthor, Executor, Student, Reviser) into a
StateGraph with a linear path to the Reviser and a conditional edge from the
Reviser that routes back to an earlier stage or terminates.

Dependency order (acyclic):
    state → failure → router → agents → graph

Nodes receive PipelineState directly; the conditional edge function also
receives PipelineState, so no special unwrapping is needed inside the graph.
LangGraph returns a plain dict from ainvoke(); run_pipeline() reconstructs
the PipelineState from that dict before returning it.
"""

from __future__ import annotations

from pathlib import Path

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from forged.artifacts import ArtifactStore
from forged.pipeline.agents.code_author import CodeAuthorAgent
from forged.pipeline.agents.executor import ExecutorAgent
from forged.pipeline.agents.planner import PlannerAgent
from forged.pipeline.agents.reviser import RevisorAgent
from forged.pipeline.agents.student import StudentAgent
from forged.pipeline.state import PipelineState


def _continue_unless_terminal(next_node: str):
    """Edge function: proceed to next_node, or END once the state is terminal."""

    def route(state: PipelineState) -> str:
        return END if state.is_terminal else next_node

    return route


def revisor_route(state: PipelineState) -> str:
    """Determine which node follows the Reviser based on state.

    Returns:
        "planner", "code_author", "reviser", or END (LangGraph sentinel).

    Logic:
        1. If state is terminal → END
        2. If routing_log is empty → END (no decision recorded)
        3. If last decision has no to_stage → END
        4. Otherwise → last decision's to_stage value (node name)
    """
    if state.is_terminal:
        return END

    if not state.routing_log:
        return END

    last_decision = state.routing_log[-1]

    if last_decision.to_stage is None:
        return END

    return last_decision.to_stage.value


def build_pipeline_graph(
    store: ArtifactStore,
    personas_dir: Path | None = None,
) -> CompiledStateGraph:
    """Assemble and compile the LangGraph pipeline.

    Initialises all five agents, wires their nodes into a StateGraph, and
    attaches a conditional edge from the Reviser that routes based on the
    last RoutingDecision recorded in state.routing_log.

    Args:
        store: ArtifactStore for reading and writing artifacts during the run.
        personas_dir: Directory containing persona .md files. Defaults to
            Path("personas") relative to the caller's working directory.

    Returns:
        A compiled LangGraph (CompiledStateGraph) ready for ainvoke().
    """
    if personas_dir is None:
        personas_dir = Path("personas")

    planner = PlannerAgent(personas_dir=personas_dir)
    code_author = CodeAuthorAgent(personas_dir=personas_dir)
    executor = ExecutorAgent(personas_dir=personas_dir)
    student = StudentAgent(personas_dir=personas_dir)
    revisor = RevisorAgent(personas_dir=personas_dir)

    graph = StateGraph(PipelineState)

    async def planner_node(state: PipelineState) -> PipelineState:
        return await planner.run(state, store)

    async def code_author_node(state: PipelineState) -> PipelineState:
        return await code_author.run(state, store)

    async def executor_node(state: PipelineState) -> PipelineState:
        return await executor.run(state, store)

    async def student_node(state: PipelineState) -> PipelineState:
        return await student.run(state, store)

    async def revisor_node(state: PipelineState) -> PipelineState:
        return await revisor.run(state, store)

    graph.add_node("planner", planner_node)
    graph.add_node("code_author", code_author_node)
    graph.add_node("executor", executor_node)
    graph.add_node("student", student_node)
    graph.add_node("revisor", revisor_node)

    graph.add_edge(START, "planner")
    # Every forward edge is conditional on the state not being terminal: an
    # agent that fails hard (e.g. executor crash) marks the state terminal,
    # and the pipeline must stop instead of spending LLM calls on a dead run.
    for node, next_node in (
        ("planner", "code_author"),
        ("code_author", "executor"),
        ("executor", "student"),
        ("student", "revisor"),
    ):
        graph.add_conditional_edges(
            node,
            _continue_unless_terminal(next_node),
            {next_node: next_node, END: END},
        )

    graph.add_conditional_edges(
        "revisor",
        revisor_route,
        {
            "planner": "planner",
            "code_author": "code_author",
            "reviser": "revisor",
            END: END,
        },
    )

    return graph.compile()


async def run_pipeline(
    initial_state: PipelineState,
    store: ArtifactStore,
    personas_dir: Path | None = None,
) -> PipelineState:
    """Build and execute the pipeline, returning the final PipelineState.

    LangGraph's ainvoke() returns a plain dict rather than the typed
    PipelineState object. This function reconstructs the PipelineState
    from that dict so callers always receive a typed result.

    Args:
        initial_state: The PipelineState to start from.
        store: ArtifactStore for artifact I/O throughout the run.
        personas_dir: Directory containing persona .md files.

    Returns:
        The final PipelineState after the pipeline reaches a terminal node.
    """
    graph = build_pipeline_graph(store=store, personas_dir=personas_dir)
    result = await graph.ainvoke(initial_state)

    if isinstance(result, PipelineState):
        return result

    return PipelineState(**result)
