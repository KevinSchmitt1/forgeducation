# Testing the Agentic Pipeline

**Status**: agentic pipeline + curriculum planner shipped; the honesty guarantees (topic
fidelity, orientation, readiness verdict, course-level coverage) are in place; ~459 tests passing
at ~92% coverage. Production-ready for personal testing.

This guide shows how to test the agentic pipeline with real OpenAI integration, monitor execution, and verify agent iteration and failure recovery.

---

## Quick Start

### Prerequisites

```bash
# Python 3.10+
python3.11 --version

# Install dependencies
pip install -e ".[dev]"

# Set up OpenAI API key
export OPENAI_API_KEY="sk-your-key-here"
```

### Run Your First Agentic Pipeline

```bash
# Simple lesson on a straightforward topic
forged agentic \
  --brief "Teach me how list comprehensions work in Python" \
  --run-dir ./test-run-1

# Check outputs
cat ./test-run-1/SUMMARY.md
cat ./test-run-1/lesson.ipynb
```

**Expected output**: 
- Exit code 0 (success)
- `lesson.ipynb` with real cell outputs
- `SUMMARY.md` showing routing log
- `pipeline.log` with execution trace

---

## Running Tests Locally

### Unit + Integration Tests (No API calls)

```bash
# All tests (292 total)
python3.11 -m pytest tests/ -q

# With coverage
python3.11 -m pytest tests/ --cov=forged --cov-report=term-missing

# Specific test suite (phases 7-9)
python3.11 -m pytest tests/pipeline/ -k "executor or reviser or agentic" -v
python3.11 -m pytest tests/test_cli_agentic.py -v
```

### Test Categories

| Test | What It Verifies |
|------|------------------|
| `test_executor_agent_detects_failing_notebook()` | Phase 7: Real executor detects failures |
| `test_real_executor_detects_code_quality_failure()` | Phase 7: CODE_QUALITY classification on failure |
| `test_reviser_writes_revision_brief()` | Phase 8: Revision brief artifact creation |
| `test_agentic_cli_runs_pipeline()` | Phase 9: CLI invokes pipeline end-to-end |
| `test_agentic_cli_writes_summary_with_routing_log()` | Phase 9: SUMMARY.md with routing log |

**Run them:**
```bash
python3.11 -m pytest tests/pipeline/test_graph_integration.py::test_executor_agent_detects_failing_notebook -xvs
python3.11 -m pytest tests/pipeline/test_graph_integration.py::test_reviser_writes_revision_brief -xvs
python3.11 -m pytest tests/test_cli_agentic.py -xvs
```

---

## Personal Testing Scenarios

### Scenario 1: Happy Path (Expected Success)

**Topic**: Simple, well-scoped concept

```bash
forged agentic \
  --brief "Explain what a Python variable is" \
  --run-dir ./test-happy-path \
  --debug
```

**Expected behavior**:
- Planner creates lesson plan
- CodeAuthor generates notebook
- Executor runs without errors → `ok: True`
- Student grades quality score ≥ 80
- Reviser classifies as ACCEPTABLE → ends

**What to check**:
- ✅ `SUMMARY.md` shows 1 iteration, ACCEPTABLE verdict
- ✅ `lesson.ipynb` is valid JSON notebook with code cells executed
- ✅ `pipeline.log` shows progression: planner → code_author → executor → student → reviser

---

### Scenario 2: Failure → Auto-Fix (Tests Phase 7-8)

**Topic**: More complex, likely to trigger code iteration

```bash
forged agentic \
  --brief "Design patterns: dependency injection with Python decorators" \
  --run-dir ./test-failure-recovery \
  --debug
```

**Expected behavior** (if CodeAuthor generates buggy code):
1. CodeAuthor generates notebook (iteration 0)
2. Executor runs → detects failure (`ok: False, failed_cells: [X]`)
3. Student grades low quality
4. Reviser classifies as CODE_QUALITY
5. **Reviser writes `revision_brief_v0.md`** with failure context
6. Router reroutes to CodeAuthor (iteration 1)
7. **CodeAuthor reads revision brief** → sees what failed, why
8. CodeAuthor generates fixed code
9. Executor runs → success (`ok: True`)
10. ... continue to completion

**What to check**:
- ✅ `SUMMARY.md` shows 2 iterations
- ✅ `revision_brief_v0.md` exists and contains failure context
- ✅ `pipeline.log` shows reroute decision and reasoning
- ✅ Second CodeAuthor call includes revised code
- ✅ Final `lesson.ipynb` has working code

**To force a failure** (for testing):
Edit one code cell in the generated notebook to introduce a syntax error, then let the executor detect it. Observe the reroute.

---

### Scenario 3: Multiple Iterations (Tests Budget)

**Topic**: Complex multi-concept topic

```bash
forged agentic \
  --brief "Build a concurrent web scraper in Python with asyncio" \
  --run-dir ./test-multiple-iterations \
  --debug
```

**Expected behavior** (if several issues):
- Multiple reroutes before reaching ACCEPTABLE
- Each iteration gets progressively better (quality score increases)
- Budget prevents infinite loops

**What to check**:
- ✅ `SUMMARY.md` shows multiple iterations (>1 route)
- ✅ Quality scores improve over iterations
- ✅ Final quality ≥ 80
- ✅ Each routing decision is logged with reason

---

### Scenario 4: Monitor LLM Costs

All API calls are logged with token counts.

```bash
forged agentic \
  --brief "Machine learning: training vs validation loss" \
  --run-dir ./test-costs \
  --debug > cost-trace.log 2>&1

# Count tokens (approximate)
grep -i "token\|usage\|api" cost-trace.log
```

**What to look for**:
- Total token usage per agent
- Cost estimate (if using claude-opus-4-8)
- Whether multiple iterations increase cost significantly

---

## Monitoring & Debugging

### Enable Debug Logging

```bash
forged agentic \
  --brief "..." \
  --run-dir ./run \
  --debug  # ← Shows DEBUG + INFO level logs
```

**Sample debug output:**
```
2026-06-09 15:35:09 INFO     forged.cli: Agentic pipeline starting (run_dir=./run)
2026-06-09 15:35:09 INFO     forged.cli: Initial state created (run_id=run, iteration=0)
2026-06-09 15:35:10 DEBUG    forged.pipeline.agents.planner: Building user message from brief
2026-06-09 15:35:20 INFO     forged.pipeline.agents.planner: LLM call completed (tokens=1240)
2026-06-09 15:35:20 INFO     forged.pipeline.agents.code_author: Generated notebook (8 cells)
2026-06-09 15:35:25 INFO     forged.pipeline.agents.executor: Execution result: ok=True, 0 failed_cells
2026-06-09 15:35:35 INFO     forged.pipeline.agents.student: Quality score: 92/100
2026-06-09 15:35:37 INFO     forged.reviser_agent: Classification=ACCEPTABLE, routing=END
2026-06-09 15:35:37 INFO     forged.cli: Pipeline complete (terminal=True, elapsed=28.5s)
```

### Inspect Artifacts

```bash
# View routing log
cat ./run/SUMMARY.md

# View execution trace
cat ./run/pipeline.log

# View revision feedback (if reroutes occurred)
cat ./run/revision_brief_v0.md

# View execution report (JSON)
cat ./run/execution_report_v0.json | jq .

# View grade report (JSON)
cat ./run/student_grade_report_v0.json | jq .

# View reviewer report (JSON, when the reviewer critic ran)
cat ./run/reviewer_report_v0.json | jq .
```

### Parse Routing Log

The `SUMMARY.md` includes a structured routing log:

```markdown
## Routing Log

### Iteration 0
- **From**: reviser
- **To**: code_author
- **Classification**: code_quality
- **Reason**: Execution failed with NameError in cell 2
```

**To analyze programmatically:**
```python
import json

# Read manifest
with open("./run/pipeline.log") as f:
    for line in f:
        if "routing" in line.lower():
            print(line)
```

---

## Verifying Core Features

### ✅ Phase 7: Real Executor (Tests Code Failure Detection)

**Test that executor detects failures:**

```bash
# Create a notebook with intentional error
forged agentic \
  --brief "Create a function that divides by zero" \
  --run-dir ./test-executor

# Check execution report
cat ./test-executor/execution_report_v0.json
# Should show: "ok": false, "failed_cells": [N], "error_summary": "..."
```

**Expected JSON:**
```json
{
  "ok": false,
  "failed_cells": [1],
  "error_summary": "ZeroDivisionError: division by zero"
}
```

### ✅ Phase 8: Revision Brief (Tests Agent Feedback)

**Verify agents receive feedback:**

```bash
forged agentic \
  --brief "Something that might fail" \
  --run-dir ./test-revision \
  --debug

# Check if revision brief was written
ls -la ./test-revision/revision_brief_v*.md

# View the brief
cat ./test-revision/revision_brief_v0.md
```

**Expected content:**
```markdown
# Revision Brief

**Classification**: code_quality
**Reason**: Execution failed with NameError
**Next Stage**: code_author

## Execution Report
- **Status**: ✗ FAILED
- **Failed Cells**: 1
- **Error**: NameError: name 'X' is not defined

## Quality Report
- **Score**: 45/100
- **Key Findings**:
  - [HIGH] Missing imports in code
  - [MEDIUM] Incomplete docstring

## Action Items
- Fix the code failures listed above
- Ensure all cells execute without error
```

### ✅ Phase 9: CLI & Logging (Tests CLI Integration)

**Verify CLI works and logs are written:**

```bash
# Run with debug logging
forged agentic \
  --brief "Test CLI" \
  --run-dir ./test-cli \
  --debug

# Check all outputs exist
ls -la ./test-cli/
# Should show: lesson.ipynb, SUMMARY.md, pipeline.log

# Verify log file
tail -20 ./test-cli/pipeline.log
```

**Expected files:**
```
test-cli/
├── lesson.ipynb           # Final notebook
├── SUMMARY.md             # Routing log + verdict
├── pipeline.log           # Detailed trace
├── revision_brief_v0.md   # (if reroutes occurred)
├── execution_report_v*.json
└── student_grade_report_v*.json
```

---

## Comparison: Linear vs Agentic

### Linear Pipeline (Stable)
```bash
forged build --topic "..."  # Single pass: plan → code → run → grade → revise
```
- Always runs full sequence
- No iteration/rerouting
- Simpler, more predictable
- No routing decisions

### Agentic Pipeline (Intelligent)
```bash
forged agentic --brief "..." --run-dir ./run  # Multi-pass with routing
```
- Classifies failures
- Reroutes intelligently
- Agents see feedback on second pass
- Full audit trail of routing decisions

**To compare:**
```bash
# Run both on the same topic
forged build --topic "Teach me sets in Python" --runs ./linear-run
forged agentic --brief "Teach me sets in Python" --run-dir ./agentic-run

# Compare output quality
diff ./linear-run/*/lesson.ipynb ./agentic-run/lesson.ipynb
cat ./linear-run/*/SUMMARY.md
cat ./agentic-run/SUMMARY.md
```

---

## Troubleshooting

### CLI Command Not Found
```bash
# Verify package is installed
pip show forged

# Or run directly
python3.11 -m forged.cli agentic --help
```

### API Key Issues
```bash
# Set key before running
export OPENAI_API_KEY="sk-..."

# Verify it's set
echo $OPENAI_API_KEY

# Or use .env file
echo "OPENAI_API_KEY=sk-..." > .env
```

### Pipeline Hangs
- Check OpenAI API status (might be rate-limited or down)
- Try with a simpler brief (fewer tokens)
- Set `--debug` to see where it's stuck

### Low Quality Scores
- Try more specific brief (e.g., "teach X to Y audience")
- Check if quality_threshold is too high (default 80)
- Review `student_grade_report_v*.json` for specific findings
- On OpenAI-backed runs, Student/Reviewer reports are schema-constrained JSON. If a report
  is marked `graded=false` or `reviewed=false`, check the `error` field and `pipeline.log`;
  on Ollama/local-compatible providers the same lenient parser fallback is still used.

---

## Test Checklist

Before considering the agentic pipeline "ready," verify:

- [ ] ✅ Unit tests pass: `pytest tests/pipeline/ -q`
- [ ] ✅ CLI tests pass: `pytest tests/test_cli_agentic.py -v`
- [ ] ✅ End-to-end with simple topic succeeds (happy path)
- [ ] ✅ Complex topic triggers iteration (failure → fix)
- [ ] ✅ Revision brief is written on reroute
- [ ] ✅ SUMMARY.md shows routing log correctly
- [ ] ✅ pipeline.log contains full execution trace
- [ ] ✅ lesson.ipynb is valid, executable notebook
- [ ] ✅ Exit code is 0 only when the run ends ACCEPTABLE; errors, budget exhaustion,
      and unclassifiable runs exit 1
- [ ] ✅ --debug flag shows detailed logs

---

## Performance Expectations

### Time per Stage (Approximate)

| Stage | Time | Notes |
|-------|------|-------|
| Planner | 10-15s | LLM call |
| CodeAuthor | 20-30s | LLM call |
| Executor | 5-10s | Actual notebook execution |
| Student | 15-20s | LLM call (grading) |
| Reviser | 2-5s | Deterministic (no LLM) |

**Total per iteration**: ~60-80 seconds (primarily LLM calls)  
**Multiple iterations**: Linear scaling (each iteration adds 60-80s)

### Token Usage (Approximate)

| Agent | Tokens In | Tokens Out | Notes |
|-------|-----------|------------|-------|
| Planner | 2K-3K | 1K-2K | Brief + learner profile |
| CodeAuthor | 3K-4K | 2K-4K | Plan + learner context |
| Student | 3K-4K | 1K-2K | Notebook + objective |
| **Total** | **~10K** | **~5K** | **Per iteration** |

---

## Next Steps

1. **Run the happy path test** (Scenario 1) to verify setup works
2. **Run with --debug** to see agent progression
3. **Try a complex topic** that might trigger iteration (Scenario 2)
4. **Inspect artifacts** (SUMMARY.md, pipeline.log, revision_brief_v*.md)
5. **Compare costs** between linear and agentic pipelines
6. **Integrate with your workflow** — use `forged agentic` for lesson generation

---

## Getting Help

- Check `./run/pipeline.log` for error details
- Run with `--debug` for verbose output
- Review docs: [DEVELOPMENT.md](DEVELOPMENT.md), [docs/architecture/](docs/architecture/)
- Run unit tests: `pytest tests/test_cli_agentic.py -xvs`

---

## Reference: CLI Options

```bash
forged agentic [OPTIONS]

Options:
  --brief TEXT            Lesson topic/brief (required)
  --run-dir PATH          Output directory (required)
  --debug                 Enable DEBUG logging (optional)
  --help                  Show this help message
```

**Example:**
```bash
forged agentic \
  --brief "Teach me coroutines in Python" \
  --run-dir ./my-lesson \
  --debug
```
