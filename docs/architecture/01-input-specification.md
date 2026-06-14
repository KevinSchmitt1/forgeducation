# Input Specification Design — forged

**Status:** Design review (Step 1 of input layer redesign)

> **Note (historical):** The *assessment approach* input described in parts of this
> and the sibling architecture docs was never wired into the pipeline and has been
> removed. The supported structured inputs are the **learner profile** and **topic
> specification** only. See git history for the removed design.

---

## Overview

forged's output quality depends entirely on input quality. This document specifies the structured inputs users should provide and includes examples showing how input precision affects notebook quality.

Currently, users provide:
- `--topic` (one-liner, no guidance)
- `--profile` (markdown file, unstructured)

**Proposed change:** Structured templates for learner profile, topic specification, and assessment approach.

---

## 1. Learner Profile Template

The learner profile describes the person who will use the notebook. This shapes:
- Vocabulary level and pacing
- Code examples (if relevant)
- Visual vs. textual explanations
- Depth of explanation

### Template

```yaml
# learner_profile.yaml

name: "Profile Name (for reference)"
description: "One sentence summary, e.g., 'Junior backend engineer new to ML'"

prior_knowledge:
  - "Comfortable with Python; written >1000 LOC"
  - "Familiar with git and command-line tools"
  - "No experience with ML, statistics, or neural networks"

environment:
  platform: "Jupyter notebook, local machine"
  # Options: jupyter_notebook, google_colab, vscode, ide, cli, book
  
material_density: "standard"
# How elaborately should mandatory content be explained?
# Options: dense (terse, minimal examples), standard (balanced), rich (elaborate with nuance)
# This does NOT reduce content; it shapes explanation richness and supplementary examples

learning_style: "hands-on with examples"
# Options: socratic (Q&A-driven), project-based, visual, hands-on, reference (structured reference material)

background_context: |
  Senior engineer transitioning into ML. Prefers concrete, runnable examples
  over lengthy theory. Will likely reference this material weeks later, so clarity
  matters more than brevity.
```

### Why Each Field Matters

| Field | Why It Matters | Agent Impact |
|-------|---------------|--------------|
| `prior_knowledge` | Determines jargon level, what can be assumed, what needs explanation | **planner**: shapes learning objectives; **code_author**: determines example complexity |
| `environment` | Constrains what tools/libraries are available; affects code style | **code_author**: chooses cell structure, output format |
| `material_density` | Determines explanation richness, example quantity, and supplementary depth (NOT content coverage) | **planner**: adjusts explanation granularity; **code_author**: code comments/walkthroughs; **student**: assessment difficulty |
| `learning_style` | Shapes narrative structure and explanation approach | **planner**: decides structure (narrative vs. reference); **code_author**: decides explanation ratio |
| `background_context` | Personalization; helps agents understand tone, priorities, edge cases | All agents: inform emphasis and framing |

---

## 2. Topic Specification Template

The topic is what the learner wants to master. This directly controls notebook scope and depth.

### Template

```yaml
# topic_specification.yaml

title: "How a Hash Map Works"
# Short, specific title. NOT "Data Structures" or "Learn Python"

scope: "implementation"
# Options:
#   - fundamentals (conceptual understanding only)
#   - implementation (understand + write from scratch)
#   - optimization (implementation + performance tuning)
#   - usage (how to use existing libraries)

learning_objectives:
  - "Understand the hash function concept and collision handling"
  - "Implement a simple hash map from scratch"
  - "Know when to use hash maps vs. other data structures"

prerequisites:
  - "Python syntax and control flow"
  - "List and dictionary basics"
  - "Basic Big O notation (optional but helpful)"

constraints: |
  Keep the implementation simple — no advanced collision strategies
  (quadratic probing, etc.). Linear probing or chaining is enough.
  Avoid heavy math; focus on intuition.

depth: "intermediate"
# How deep should this go?
# Options: beginner (overview), intermediate (working understanding), advanced (expert-level)

focus_areas:
  - "Hash functions and distribution"
  - "Collision handling (chaining)"
  - "Performance characteristics"
```

### Why Each Field Matters

| Field | Why It Matters | Agent Impact |
|-------|---|---|
| `title` | Sets scope and prevents scope creep | **planner**: anchors the lesson plan |
| `scope` | Determines breadth (how many topics) and depth (theory vs. code) | **planner**: decides if notebook is 1000 lines or 5000 lines |
| `learning_objectives` | Concrete success criteria; keeps agents focused | **planner**: structures lesson around these; **student**: evaluates against these |
| `prerequisites` | Determines what can be skipped vs. explained | **planner**: decides intro depth; **code_author**: chooses example context |
| `constraints` | Exclusions and boundaries (what NOT to cover) | All agents: respect scope limits |
| `depth` | Targets audience expertise level | **planner**: determines explanation richness; **code_author**: code complexity |
| `focus_areas` | Priorities; shapes time allocation | **planner**: emphasis weighting |

---

## 3. Assessment Approach Template

How should learners validate their understanding?

### Template

```yaml
# assessment_approach.yaml

type: "project"
# Options: project, knowledge_test, both

project:
  description: |
    Build a working hash map implementation that passes a test suite.
    Learner provides the implementation; we provide tests.
  
  starter_context: |
    Start with function signatures and docstrings; learner fills in the body.
    Test cases validate correctness.
  
  difficulty: "intermediate"
  # Should match or slightly exceed the notebook difficulty
  
  time_estimate: "30-45 minutes"

knowledge_test:
  # (if type is "knowledge_test" or "both")
  format: "exercises with solutions"
  # Options: multiple_choice, fill_in_code, conceptual_questions, exercises
  
  count: 5
  # Number of items
  
  difficulty: "intermediate"

assessment_difficulty: "matches_topic"
# Options: matches_topic, slightly_harder, significantly_harder
# "harder" encourages retention and deeper application
```

### Why This Matters

Projects > Knowledge tests for retention and real understanding. A knowledge test verifies recall; a project requires application.

---

## 4. Good vs. Bad Examples

### Example 1: Hash Map (Good Input)

**Profile:**
```yaml
name: "Backend Junior"
prior_knowledge:
  - "2 years Python; comfortable with OOP"
  - "Knows lists/dicts but never implemented one"
environment:
  platform: "jupyter_notebook"
material_density: "standard"
learning_style: "hands-on with examples"
background_context: "Building a caching system; needs to understand why hash maps are fast."
```

**Topic:**
```yaml
title: "How a Hash Map Works"
scope: "implementation"
learning_objectives:
  - "Understand hash functions and collision handling"
  - "Implement a simple hash map"
  - "Know performance trade-offs"
prerequisites:
  - "Python syntax"
  - "Lists and dicts (usage level)"
depth: "intermediate"
focus_areas:
  - "Hash functions"
  - "Collision handling"
```

**Assessment:**
```yaml
type: "project"
project:
  description: "Implement a hash map class that passes test cases"
  difficulty: "intermediate"
```

**Expected Output:**
- 45-minute notebook
- ~500 lines of code + markdown
- Runnable, tested implementation
- Clear explanation of trade-offs
- Student can extend it for their caching system

---

### Example 1b: Hash Map (Bad Input)

**Profile:**
```
"I want to learn data structures"
```

**Topic:**
```
--topic "Data Structures"
```

**Assessment:**
```
None (no guidance)
```

**Expected Output:**
- Unclear scope (just hash maps? All data structures? Algorithms too?)
- Unclear depth (overview vs. implementation?)
- Unclear audience level
- Notebook might be 2 hours or 20 minutes — nobody knows
- No validation of learning

---

### Example 2: LLM Fundamentals (Good Input)

**Profile:**
```yaml
name: "ML Practitioner"
prior_knowledge:
  - "Worked with scikit-learn and pandas"
  - "Understanding of neural networks (basic)"
  - "Familiar with transformers as black boxes"
environment:
  platform: "jupyter_notebook"
material_density: "rich"
learning_style: "visual with worked examples"
background_context: "Building a recommendation system; want to understand when to use LLMs vs. other models."
```

**Topic:**
```yaml
title: "Transformer Architecture Fundamentals"
scope: "fundamentals"
learning_objectives:
  - "Understand attention mechanism conceptually"
  - "Know how transformers differ from RNNs"
  - "Recognize when transformers are appropriate"
prerequisites:
  - "Neural networks basics (layers, backprop)"
  - "Linear algebra (matrix multiplication, dot products)"
depth: "intermediate"
focus_areas:
  - "Attention mechanism (intuition + math)"
  - "Self-attention in practice"
  - "Position encoding"
constraints: "No training loops; focus on architecture and inference."
```

**Assessment:**
```yaml
type: "project"
project:
  description: |
    Implement a simple attention head from scratch.
    Given a batch of sequences and weights, compute attention outputs.
  difficulty: "intermediate"
```

**Expected Output:**
- 90-minute notebook
- Focus on visual explanations (diagrams, matrices)
- Working code examples showing attention in action
- Clear comparison to RNNs
- Learner can then apply to their recommendation system

---

## 5. How to Present This to Users

### CLI Enhancement

```bash
# Current
forged build --topic "How a hash map works" --profile profiles/default.md

# Future — with guidance
forged build --topic "How a hash map works" \
  --profile profiles/backend-junior.yaml \
  --assessment project \
  --help-input  # Shows template + examples
```

### New Command

```bash
forged input-template
# Outputs a sample learner profile + topic + assessment to stdout
# User fills it in and passes with --profile
```

### README Addition

Add a section: **"Preparing Your Input"**

```
The quality of your notebook depends on the quality of your input.
Vague inputs → vague notebooks. Specific inputs → focused, useful notebooks.

1. Use the learner profile template to describe who will use this
2. Use the topic specification template to define scope and depth
3. Choose an assessment approach
4. Run: forged build --profile my_profile.yaml --topic "..."
```

---

## 6. Data Model for Implementation

The orchestrator would accept a structured input instead of just strings:

```python
@dataclass
class LearnerProfile:
    name: str
    prior_knowledge: list[str]
    environment: str  # jupyter_notebook, colab, etc.
    material_density: str  # dense, standard, rich
    learning_style: str  # socratic, project_based, etc.
    background_context: str

@dataclass
class TopicSpecification:
    title: str
    scope: str  # fundamentals, implementation, optimization, usage
    learning_objectives: list[str]
    prerequisites: list[str]
    constraints: str
    depth: str  # beginner, intermediate, advanced
    focus_areas: list[str]

@dataclass
class AssessmentApproach:
    type: str  # project, knowledge_test, both
    project: dict | None
    knowledge_test: dict | None
```

The agents (planner, code_author, etc.) would receive these structured inputs in their prompts, replacing the current vague briefs.

---

## Summary of Changes

| Current | Proposed |
|---------|----------|
| `--topic` (one-liner) | `--topic` + `--profile` (YAML with full context) |
| Learner profile: unstructured markdown | Learner profile: YAML template with 5 fields (prior_knowledge, environment, material_density, learning_style, background_context) |
| No topic structure | Topic specification: YAML with scope, objectives, constraints |
| No assessment guidance | Assessment template: project vs. test, difficulty |
| CLI help: minimal | CLI help: shows input templates + examples + impact on output |
| `time_budget` misunderstood | `material_density` clarifies: not about content reduction, but explanation richness |

---

## Next Steps (After Review)

If you approve this design:

1. **Step 2:** Map how these structured inputs flow through existing agents — see [02-agent-input-flow.md](02-agent-input-flow.md)
2. **Step 3:** Sketch the new assessment stage (generate project specs or tests)
3. **Step 4:** Implement in code (CLI, YAML parsing, agent prompts)
4. **Step 5:** Document with examples in README
