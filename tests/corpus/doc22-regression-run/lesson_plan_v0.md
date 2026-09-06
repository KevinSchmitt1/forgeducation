```lesson-mode
artifact
```

## Assumed knowledge
- Python (reading/writing files, running scripts) — builds directly on Prior knowledge: Python and basic data structures.
- Basic git usage (clone, commit, push) — profile lists "git configured" in prerequisites; notebook will call git commands, not teach git workflows.
- Markdown familiarity (headings, code fences, emphasis) — profile lists "Basic familiarity with Markdown" in prerequisites.

## Required background & gaps
1. Concepts required:
   - Markdown structure (headings, code fences, lists) — KNOWN (profile prerequisite).
   - Repository layout conventions for Python projects (src/, package-name/, tests/) — GAP.
   - CI hooks and simple validation integration (what a GitHub Action can check) — GAP.
   - What a Copilot/AI-assistant instruction file is intended to control (scope, guardrails) — GAP (profile has LLM CLI + prompt engineering but not repo-level agent governance).
   - Agent persona / workflow definition basics (persona, allowed actions, boundaries) — GAP.
   - Simple programmatic Markdown checks (searching headings, code-block detection, forbidden-pattern scanning) — KNOWN (Python skills) / small GAPS (text parsing patterns).

Must teach from scratch (every GAP above must be introduced in the lesson):
- Short primer on Python repo conventions (what src/, package root, and tests/ mean; how to reference test commands).
- Short explanation of CI validation hooks and why adding a validation script is recommended.
- What a Copilot instructions file controls and concrete examples of allowed vs forbidden agent actions.
- How to structure AGENTS.md entries (persona header, responsibilities, allowed commands, templates and boundaries).
- Minimal technique for programmatic Markdown validation (regex/headings search, code-fence detection, forbidden-token checks).

Readiness verdict
- Gaps are focused and foundational but small; they can be taught briefly alongside the artifact work. Proceed.

## Prerequisites
- Jupyter Notebook running locally and a local clone of the target repository with write access and git configured.
- Python 3.8+ (standard library used only).
- Notebook will call git via subprocess; ensure git is on PATH.

requirements
```requirements

```

## Learning objectives
- Produce .github/copilot-instructions.md containing purpose, scope, coding conventions, examples, security constraints, and escalation guidance tailored to a Python repo.
- Produce AGENTS.md with agent personas, responsibilities, allowed/forbidden actions, task templates, sample interactions, and explicit sensitive-data boundaries.
- Encode repository-specific conventions (package layout, import style, typing expectations, test commands, CI hooks) into these documents with before/after examples.
- Implement and run a small Python validation script in the repo that programmatically checks file existence, required headings, examples, forbidden patterns, and basic Markdown sanity; iterate until validation passes and commit changes.

## Concept sequence
1. Why repository-level agent/instruction files exist (intuitively):
   - Intuition: They turn high-level team norms into machine-readable guidance for code-suggestion agents.
   - Connect to Prior knowledge: relates to prompt-engineering discipline the learner already practices.
   - Explanation beat (standard): Show one short example of an ambiguous prompt vs. a precise repo-level instruction that eliminates risky suggestions.
2. Python repo layout and conventions to codify:
   - Intuition: Agents must know where code, tests, and packages live to produce correct suggestions.
   - Connect: Builds on Python familiarity.
   - Explanation beat (standard): List the canonical tokens to mention (src/, package_name/, tests/, pytest command), and why explicit test commands and lint commands are required.
3. Anatomy of .github/copilot-instructions.md and AGENTS.md:
   - Intuition: Both files are structured documents—one controls coding style & safety, the other defines operational personas and action boundaries.
   - Connect: Uses Markdown familiarity and prompt-engineering ideas.
   - Explanation beat (rich): Provide the required sections for each file and rules for examples (before/after code blocks, explicit allowed/forbidden action lists).
4. Validation design:
   - Intuition: Automated checks catch omissions and unsafe patterns before PRs land.
   - Connect: Uses Python scripting skills.
   - Explanation beat (standard): Define checks to implement: existence, required headings (case-insensitive), presence of at least one triple-backtick code block in examples, forbidden-pattern detection (secrets, exec-of-remote), min-length per section, and a simple markdown-structure sanity check.

## Code demonstration (artifact / deliverable sequence)
1. Artifact: .github/copilot-instructions.md
   - What it is and where it lives: file at .github/copilot-instructions.md in repo root.
   - How a cell validates it: check file exists; search for required headings (Purpose, Scope, Coding conventions, Examples, Security constraints, Escalation); confirm at least one before/after code block pair (look for "Before:" and "After:" heading text or code-block pairs); confirm mention of repo tokens (one of "src/", "tests/", "pytest", "mypy"); ensure no forbidden tokens (AWS keys, PASSWORD, ssh -i, curl http://internal).
   - Built-and-validated: created in notebook and validated for real.
2. Artifact: AGENTS.md
   - What it is and where it lives: AGENTS.md at repo root or docs/AGENTS.md (lesson uses repo root).
   - How a cell validates it: check file exists; for each agent block (H2/H3 starting "Agent:" or "## <Name> — Persona"), ensure subheadings: Responsibilities, Allowed actions, Task templates, Sample interactions, Boundaries and sensitive-data rules; verify at least one task template contains a parameterized template placeholder (e.g., {{issue_number}}) and at least one sample interaction shows a request and an agent reply code block.
   - Built-and-validated: created and validated for real.
3. Artifact: tools/validate_agent_docs.py (validation script)
   - What it is and where it lives: Python script at tools/validate_agent_docs.py that runs all checks and prints JSON + human-readable summary and exit code 0 on pass.
   - How a cell validates it: run the script in the notebook subprocess; the notebook captures stdout/stderr and asserts exit code == 0. Script implements file checks, heading detection via regex, code-block detection, forbidden-pattern scanning, per-section min-length thresholds, and returns a structured report.
   - Built-and-validated: created and executed in the notebook — this is the required built-and-validated artifact anchoring the lesson.
4. Artifact: Notebook cells showing iterative workflow and commit
   - What it is and where it lives: cells in the lesson notebook that: (a) open/create the two markdown files, (b) run the validation script, (c) if errors, print failures for edit, (d) re-run until passing, and (e) run git add/commit/push via subprocess (using provided branch).
   - How a cell validates it: the cell asserts the validation script exit code and prints the JSON report; after pass, the notebook runs git commands and shows commit hash.
   - Built-and-validated: executed in the lesson notebook and demonstrates commit; the notebook will not push to remote unless user consents — by default it commits locally to the current branch.

## Pitfalls to avoid
- Saying "agent rules should be vague" — vague instructions produce unsafe and inconsistent code; the lesson must show precise allowed/forbidden phrasing.
- Requiring a single rigid schema for AGENTS.md (avoid insisting on a fixed YAML schema) — instead require clear headings and templates; over-formalization will break adoption.
- Linting vs. policy confusion — validation checks should assert presence and structure, not attempt to be a full static analyzer or replace human review.

