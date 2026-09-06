## Lesson Context

### Target learner — Kevin: Junior Data Scientist and AI Engineer
Rudimentary experience with Python and machine learning. Transitioning from data science to AI engineering, 
with a focus on deep learning and model deployment.

- Prior knowledge:
  - Python and basic data structures (lists, dicts, sets)
  - SQL and relational databases
  - REST API design
  - LLM CLI usage and prompt engineering
- Environment: jupyter_notebook
- Material density: standard
- Learning style: hands_on
- Background: Goal: Transition from data science to AI engineering.
Motivated by understanding deep learning and model deployment.
Works at a company with ~100 engineers; no big tech experience.

### Topic — Create and Validate .github/copilot-instructions.md and AGENTS.md
- Scope: implementation
- Depth: intermediate
- Learning objectives:
  - Author a repository-level .github/copilot-instructions.md that instructs Copilot agents on project conventions, coding style, test expectations, security constraints, and allowed/forbidden actions.
  - Author an AGENTS.md file that defines agent personas/workflows, task templates, named roles, and explicit boundaries so agents follow the project's process when taking actions.
  - Encode Python-repo-specific conventions (package layout, import style, typing expectations, test commands, CI hooks) into the instructions so generated code follows team norms.
  - Implement a reproducible validation procedure (small Python validation script and/or checklist) that verifies the presence, structure, required sections, and basic content sanity of both files.
  - Run the validation locally in a Jupyter Notebook, interpret validation output, iterate on the files until validation passes, and commit the files to the repository.
- Prerequisites:
  - jupyter_notebook environment (running locally or in your usual workspace)
  - A local clone of the target Python repository with git configured
  - Write access to the repository on GitHub (or a feature branch)
  - Basic familiarity with Markdown and editing files in a repo
  - Python 3 installed to run simple validation scripts
- Focus areas (priority order):
  - Structure and required sections of .github/copilot-instructions.md (purpose, scope, coding conventions, examples, security constraints, escalation)
  - Structure and required sections of AGENTS.md (agent persona, responsibilities, allowed commands/actions, task templates, sample interactions, boundaries and sensitive-data rules)
  - Mapping repository conventions to actionable instruction text (explicit rules, examples with before/after snippets, test and lint commands to run)
  - Validation checks: file existence, required headings, presence of examples, length and clarity checks, forbidden-pattern detection, and simple parse/lint of Markdown structure
  - Practical workflow: iterative editing, running validation in a notebook, committing changes, and recommending CI integration for future validation
- Constraints: 

### Lesson mode (already decided — binding)
This lesson's mode is `artifact`. Plan within it; do not re-infer it.
