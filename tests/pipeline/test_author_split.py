"""Author-identity split: two personas, one author node (doc 23, recommendation B).

One `code_author` identity used to serve every lesson mode, opening with "implement the
plan's code demo" — the wrong job description for an `artifact` lesson (build and validate
a deliverable) or a `conceptual` one (nothing runs). The fix splits the *persona*, not the
graph: the single author agent reads the mode off the plan and picks its persona.

What these tests hold:

  * the persona is chosen per mode, and the choice actually reaches the model;
  * the executable path is unchanged — same file, same user message — pinned;
  * a code-scope repair on an artifact lesson still routes to the one author node, which
    re-derives the mode on the repair pass (no router change);
  * the shared machinery stays verbatim-identical between the two files, and the check
    for that is shown to be able to fail (R1's lesson: a check that cannot fail proves
    nothing).
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from pathlib import Path

import pytest

from forged.artifacts import Artifact, ArtifactStore
from forged.notebook import build_notebook
from forged.pipeline.agents.code_author import CodeAuthorAgent, persona_filename
from forged.pipeline.failure import Classification, FailureCategory
from forged.pipeline.router import Router, RoutingRequest
from forged.pipeline.state import (
    PipelineStage,
    PipelineState,
    StageOutput,
    create_initial_state,
)

PERSONAS = Path(__file__).resolve().parents[2] / "personas"
CODE_PERSONA = "code_author.md"
ARTIFACT_PERSONA = "artifact_author.md"

# The sections both authors share. They must stay byte-identical between the two files
# (doc 23 Part V): each file differs only in its identity and its mode-specific rules.
SHARED_HEADINGS = (
    "## Hard rules that hold in every lesson",
    "## Files the lesson writes, and stand-ins",
    "## Learner orientation — the first markdown cell",
    "## Code maps & cell briefs — make dense code followable",
    "## Explanation cells — theory carries equal weight",
    "## Output format",
)

CELLS = [{"type": "markdown", "source": "# Start Here"}, {"type": "code", "source": "1"}]


class _StubClient:
    def __init__(self, response: str) -> None:
        self._response = response
        self.system_prompts: list[str] = []
        self.user_prompts: list[str] = []

    def complete(self, system_prompt: str, user_prompt: str, **kwargs: object) -> str:
        self.system_prompts.append(system_prompt)
        self.user_prompts.append(user_prompt)
        return self._response


def _plan(mode: str | None) -> str:
    fence = f"```lesson-mode\n{mode}\n```\n\n" if mode is not None else ""
    return f"{fence}# Lesson: Agents\n\n## Code demonstration\n- build AGENTS.md"


def _store(tmp_path: Path) -> ArtifactStore:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    return ArtifactStore(run_dir)


def _first_pass(store: ArtifactStore, plan: str) -> PipelineState:
    store.put(Artifact(name="lesson_plan_v0", kind="text", content=plan))
    state = create_initial_state(run_id="author-split")
    return state.with_output(
        StageOutput(stage=PipelineStage.PLANNER, artifact_name="lesson_plan_v0", iteration=0)
    )


def _repair_pass(store: ArtifactStore, plan: str) -> PipelineState:
    """Iteration 1 after a code-scope failure: a notebook and a brief exist."""
    state = _first_pass(store, plan)
    store.put(
        Artifact(name="lesson_notebook_v0", kind="notebook", content=build_notebook(CELLS))
    )
    store.put(Artifact(name="revision_brief_v0", kind="text", content="Cells [1] raised."))
    state = state.with_output(
        StageOutput(
            stage=PipelineStage.CODE_AUTHOR, artifact_name="lesson_notebook_v0", iteration=0
        )
    )
    return replace(state, iteration=1)


def _run(agent: CodeAuthorAgent, state: PipelineState, store: ArtifactStore) -> PipelineState:
    # A private loop: asyncio.run() would clear the thread's current loop and break
    # later tests that still call asyncio.get_event_loop().
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(agent.run(state, store))
    finally:
        loop.close()


def _read(name: str) -> str:
    return (PERSONAS / name).read_text(encoding="utf-8")


def _sections(text: str) -> dict[str, str]:
    """Split a persona into its `## ` sections, keyed by heading line.

    A section runs from its heading to the next `## ` heading (`###` subsections stay
    inside their parent) or to the end of the file.
    """
    sections: dict[str, str] = {}
    heading: str | None = None
    body: list[str] = []
    for line in text.splitlines():
        if line.startswith("## "):
            if heading is not None:
                sections[heading] = "\n".join(body).strip()
            heading, body = line, []
        elif heading is not None:
            body.append(line)
    if heading is not None:
        sections[heading] = "\n".join(body).strip()
    return sections


def _shared_drift(code_text: str, artifact_text: str) -> list[str]:
    """Headings whose shared section is missing from, or differs between, the two files."""
    code, artifact = _sections(code_text), _sections(artifact_text)
    return [
        h
        for h in SHARED_HEADINGS
        if h not in code or h not in artifact or code[h] != artifact[h]
    ]


# ── persona selection per mode ────────────────────────────────────────────────────


@pytest.mark.unit
@pytest.mark.parametrize(
    ("mode", "expected"),
    [
        ("executable", CODE_PERSONA),
        ("artifact", ARTIFACT_PERSONA),
        ("conceptual", ARTIFACT_PERSONA),
    ],
)
def test_each_mode_selects_its_persona_file(mode: str, expected: str) -> None:
    assert persona_filename(mode) == expected  # type: ignore[arg-type]


@pytest.mark.unit
@pytest.mark.parametrize("mode", ["artifact", "conceptual"])
def test_non_executable_plan_hands_the_model_the_artifact_persona(
    tmp_path: Path, mode: str
) -> None:
    store = _store(tmp_path)
    client = _StubClient(json.dumps(CELLS))

    agent = CodeAuthorAgent(personas_dir=PERSONAS, llm_client=client)
    _run(agent, _first_pass(store, _plan(mode)), store)

    assert client.system_prompts == [_read(ARTIFACT_PERSONA)]


@pytest.mark.unit
@pytest.mark.parametrize("mode", ["executable", None, "hands-on"])
def test_executable_absent_or_unknown_mode_hands_the_model_the_code_persona(
    tmp_path: Path, mode: str | None
) -> None:
    """Unknown/absent falls back to executable, matching extract_lesson_mode's default."""
    store = _store(tmp_path)
    client = _StubClient(json.dumps(CELLS))

    agent = CodeAuthorAgent(personas_dir=PERSONAS, llm_client=client)
    _run(agent, _first_pass(store, _plan(mode)), store)

    assert client.system_prompts == [_read(CODE_PERSONA)]


# ── the executable path does not move (pinned) ────────────────────────────────────


@pytest.mark.unit
def test_executable_prompt_input_is_pinned(tmp_path: Path) -> None:
    """System prompt is the agent's init-loaded persona; user message is unchanged.

    The executable path must be byte-identical to before the split: the persona the
    base class loaded at construction (`self.persona`) and the same plan-only message.
    """
    store = _store(tmp_path)
    client = _StubClient(json.dumps(CELLS))
    agent = CodeAuthorAgent(personas_dir=PERSONAS, llm_client=client)
    plan = _plan("executable")

    _run(agent, _first_pass(store, plan), store)

    assert client.system_prompts == [agent.persona]
    assert client.user_prompts == [f"Lesson Plan:\n{plan}"]


@pytest.mark.unit
def test_executable_run_never_reads_the_artifact_persona(tmp_path: Path) -> None:
    """A personas dir without artifact_author.md still serves executable lessons."""
    personas = tmp_path / "personas"
    personas.mkdir()
    (personas / CODE_PERSONA).write_text("You are the Code Author.", encoding="utf-8")
    store = _store(tmp_path)
    client = _StubClient(json.dumps(CELLS))

    agent = CodeAuthorAgent(personas_dir=personas, llm_client=client)
    _run(agent, _first_pass(store, _plan(None)), store)

    assert client.system_prompts == ["You are the Code Author."]


# ── routing: one node, mode re-derived on the repair pass ────────────────────────


@pytest.mark.unit
@pytest.mark.parametrize("category", [FailureCategory.TEST_FAILURE, FailureCategory.CODE_QUALITY])
def test_code_scope_repair_on_an_artifact_lesson_lands_on_the_mode_correct_author(
    tmp_path: Path, category: FailureCategory
) -> None:
    store = _store(tmp_path)
    state = _repair_pass(store, _plan("artifact"))

    routed = Router().route(
        RoutingRequest(
            state=state,
            classification=Classification(category=category, reason="r", matched_signals=["s"]),
            evidence=[],
        )
    )
    assert routed.next_stage == PipelineStage.CODE_AUTHOR  # the one node, unchanged

    client = _StubClient(json.dumps({"patch": [{"index": 1, "type": "code", "source": "2"}]}))
    _run(CodeAuthorAgent(personas_dir=PERSONAS, llm_client=client), state, store)

    assert client.system_prompts == [_read(ARTIFACT_PERSONA)]


# ── the two persona files: identities, and the shared sections cannot drift ──────


@pytest.mark.unit
def test_each_persona_opens_with_its_own_identity() -> None:
    assert _read(CODE_PERSONA).startswith("You are the **Code Author**")
    assert _read(ARTIFACT_PERSONA).startswith("You are the **Artifact Author**")


@pytest.mark.unit
def test_code_author_no_longer_carries_the_other_modes_branches() -> None:
    text = _read(CODE_PERSONA)

    assert "`artifact` mode" not in text
    assert "`conceptual`" not in text


@pytest.mark.unit
def test_artifact_author_makes_conceptual_first_class_and_honest() -> None:
    """Doc 23 Part V: conceptual is not a footnote to artifact authoring."""
    sections = _sections(_read(ARTIFACT_PERSONA))

    conceptual = [h for h in sections if "conceptual" in h.lower()]
    assert conceptual, "artifact_author.md needs its own conceptual-lesson section"
    assert "no code runs" in " ".join(sections[conceptual[0]].split())


@pytest.mark.unit
def test_artifact_author_requires_write_then_validate() -> None:
    text = _read(ARTIFACT_PERSONA)

    assert "write" in text and "validate" in text
    assert "never a hardcoded claim of success" in " ".join(text.split())


@pytest.mark.unit
def test_shared_sections_are_verbatim_identical_between_the_two_authors() -> None:
    assert _shared_drift(_read(CODE_PERSONA), _read(ARTIFACT_PERSONA)) == []


@pytest.mark.unit
@pytest.mark.parametrize("heading", SHARED_HEADINGS)
def test_the_drift_check_fails_when_one_copy_is_edited(heading: str) -> None:
    """Proves the drift check can fail: edit one shared section of one copy only."""
    artifact = _read(ARTIFACT_PERSONA)
    drifted = artifact.replace(heading + "\n", heading + "\nA sentence only one file has.\n", 1)
    assert drifted != artifact

    assert _shared_drift(_read(CODE_PERSONA), drifted) == [heading]


@pytest.mark.unit
def test_the_drift_check_fails_when_a_shared_section_is_dropped() -> None:
    code = _read(CODE_PERSONA)
    dropped = code.replace("## Output format", "## Output shape", 1)

    assert _shared_drift(dropped, _read(ARTIFACT_PERSONA)) == ["## Output format"]


@pytest.mark.unit
@pytest.mark.parametrize("name", [CODE_PERSONA, ARTIFACT_PERSONA])
def test_both_authors_carry_the_load_bearing_invariants(name: str) -> None:
    text = _read(name)

    assert "Return ONLY a JSON array of cells" in text  # output contract
    assert "only the cells you are changing" in text  # patch protocol (doc 21)
    assert "%%writefile" in text  # the delimiter-collision trap
    assert "Stand-ins must announce themselves" in text
    assert "Remake decision" in text  # R7
    assert "Accumulated critique" in text  # R6


# ── the base class carries the per-call persona; the agent is never mutated ──────


@pytest.mark.unit
@pytest.mark.parametrize(("override", "expected"), [(None, "BASE"), ("OVERRIDE", "OVERRIDE")])
def test_complete_llm_sends_the_override_persona_only_when_given(
    tmp_path: Path, override: str | None, expected: str
) -> None:
    store = _store(tmp_path)
    client = _StubClient("[]")
    agent = CodeAuthorAgent(personas_dir=PERSONAS, llm_client=client)
    agent.persona = "BASE"

    agent._complete_llm(
        stage_name=PipelineStage.CODE_AUTHOR,
        state=create_initial_state(run_id="override"),
        store=store,
        user_msg="u",
        input_artifacts=(),
        output_artifact="x",
        persona=override,
    )

    assert client.system_prompts == [expected]


@pytest.mark.unit
def test_an_artifact_run_leaves_the_agents_own_persona_untouched(tmp_path: Path) -> None:
    store = _store(tmp_path)
    agent = CodeAuthorAgent(personas_dir=PERSONAS, llm_client=_StubClient(json.dumps(CELLS)))

    _run(agent, _first_pass(store, _plan("artifact")), store)

    assert agent.persona == _read(CODE_PERSONA)
