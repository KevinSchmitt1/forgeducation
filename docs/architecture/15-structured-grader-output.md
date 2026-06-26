# Structured Grader Output

**Status:** Implemented 2026-06-26.

## Problem

The Student and Reviewer critics used to rely on prompt discipline: emit prose, then put a
JSON block at the very end. `gpt-5-mini` can intermittently violate that shape even when
the token budget is fine. In a paid agentic run this is expensive: planner, code_author,
executor, and provisioning may all complete before the grader output becomes unparseable.

The previous fallback was honest, not silent: Student wrote `graded=false` and Reviewer
wrote `reviewed=false`. That protected routing from fabricated scores, but it still wasted
the useful quality judgment.

## Decision

Use OpenAI structured outputs for the critic stages.

- `LLMClient.complete(...)` accepts an optional `response_format`.
- OpenAI calls forward that object to `chat.completions.create(...)`.
- Ollama/local-compatible calls omit `response_format`, because many local OpenAI-style
  servers do not implement the parameter.
- `StudentAgent` passes a strict JSON Schema for `quality_score`, nullable `rubric`,
  `verdict`, `blockers`, and scoped `findings`.
- `ReviewerAgent` passes a strict JSON Schema for `verdict`, `blockers`, and scoped
  `findings`.
- The existing parsers remain lenient for local/non-structured providers and for older
  saved artifacts.

## Consequences

OpenAI-backed grader reports should no longer fail because required keys such as
`quality_score`, `blockers`, or `findings` are missing. If the model or provider still fails,
the existing degradation path remains: unparseable Student output becomes `graded=false`;
unparseable Reviewer output becomes `reviewed=false`.

The critic personas now say "JSON object only" rather than "prose plus final fenced JSON".
Future persona edits should preserve that contract. The narrative verdict lives in the
`verdict` field, and individual issues live in `findings`.

## Verification

Regression tests cover:

- Student passes a strict `student_grade_report` schema to the LLM client.
- Reviewer passes a strict `reviewer_findings_report` schema to the LLM client.
- `LLMClient.complete(...)` forwards `response_format` for OpenAI.
- `LLMClient.complete(...)` omits `response_format` for Ollama.

Full local verification after implementation:

```bash
PYTHONPATH=. pytest
```

Result: `471 passed`.
