# forged Templates

This directory contains templates and examples for providing rich input to forged, the AI-powered educational content generator.

## Quick Start

### Minimal Input (Easiest)
Just provide a topic and let forged use defaults:

```bash
forged build --topic "How hash maps work"
```

This uses sensible defaults for learner profile and topic specification.

### Structured Input (Recommended)
Use templates to customize the learning experience:

```bash
forged build \
  --topic "How hash maps work" \
  --learner-profile templates/examples/learner-backend-junior.yaml \
  --topic-spec templates/examples/topic-hash-maps.yaml
```

## Template Files

### Core Templates

1. **`learner_profile.template.yaml`**
   - Describes the learner's background, goals, and learning preferences
   - Fields: prior_knowledge, learning_style, environment, material_density, background_context
   - Affects: prompt enrichment, explanation depth, code examples

2. **`topic_specification.template.yaml`**
   - Defines what should be learned and how deep
   - Fields: scope, learning_objectives, prerequisites, constraints, depth, focus_areas
   - Affects: content structure, examples chosen, depth calibration

### Example Profiles

#### Learner Profiles

- **`examples/learner-beginner.yaml`** — Complete beginner; needs dense explanations, visual learning, slow pace
- **`examples/learner-backend-junior.yaml`** — Backend developer; hands-on, medium detail, practical focus
- **`examples/learner-ml-practitioner.yaml`** — ML engineer; conceptual depth, rigorous explanations, research papers

#### Topic Specifications

- **`examples/topic-hash-maps.yaml`** — Foundational data structure; practical implementation focus
- **`examples/topic-transformers.yaml`** — Advanced ML topic; rigorous math + code, GPU environment

## Key Fields Explained

> The enum fields below accept a **fixed set of values** — these are the only
> accepted strings (they map to `Literal` types in `forged/models.py`). Any other
> value is passed to the model verbatim and silently weakens the prompt, so stick
> to this list.

### `material_density` (learner profile)

How much explanation and how many examples per concept:

- **dense**: terse explanations, ~1 canonical example per concept
- **standard**: balanced explanations, 2–3 examples per concept
- **rich**: elaborate explanations, multiple examples, extension ideas (longer notebook)

### `learning_style` (learner profile)

How the learner prefers to absorb material — one of:

- **socratic** · **project_based** · **visual** · **hands_on** · **reference**

(Note the underscores: `hands_on`, `project_based`.)

### `environment` (learner profile)

Where the lesson will run — one of:

- **jupyter_notebook** · **google_colab** · **vscode** · **ide** · **cli** · **book**

### `scope` (topic spec)

The angle the lesson takes — one of:

- **fundamentals**: concepts over code
- **implementation**: working, runnable code from scratch
- **optimization**: performance, profiling, trade-offs
- **usage**: how to use existing tools/APIs effectively

### `depth` (topic spec)

Theoretical rigor — one of:

- **beginner** · **intermediate** · **advanced**

## Customizing Templates

1. **Copy a template file:**
   ```bash
   cp templates/learner_profile.template.yaml my-profile.yaml
   ```

2. **Edit the fields** (remove comments and fill in values)

3. **Use with forged:**
   ```bash
   forged build --topic "..." --learner-profile my-profile.yaml
   ```

## What Each Template Affects

### Learner Profile
→ Agent prompts include:
- Learner's background (agents adjust explanation depth)
- Material density (controls detail level and example count)
- Learning style (prompts emphasize visual / hands_on / socratic depending on style)

### Topic Specification
→ Agents use for:
- Planner: scope, objectives, depth guide content structure
- Code Author: prerequisites, constraints, focus areas guide examples
- Student: learning objectives validate notebook completeness

## Examples

### Example 1: Beginner Learning Data Structures

```bash
# Copy a learner profile
cp templates/examples/learner-beginner.yaml my-learning/beginner.yaml

# Copy a topic
cp templates/examples/topic-hash-maps.yaml my-learning/hash-maps.yaml

# Generate content
forged build \
  --topic "Hash maps and how they work" \
  --learner-profile my-learning/beginner.yaml \
  --topic-spec my-learning/hash-maps.yaml
```

Result: Dense explanations, multiple examples, visual focus, slower pacing.

### Example 2: ML Engineer Learning Transformers

```bash
forged build \
  --topic "Transformer attention mechanisms" \
  --learner-profile templates/examples/learner-ml-practitioner.yaml \
  --topic-spec templates/examples/topic-transformers.yaml
```

Result: Rigorous explanations, mathematical depth, advanced examples, research-level content.

## Tips for Best Results

1. **Be specific in `scope`** — "Hash maps" is too broad; "Hash map implementation and collision resolution" is better

2. **List actual `learning_objectives`** — Specific goals (implement, explain, debug) guide better content than vague ones

3. **Accurate `prior_knowledge`** — Agents skip explaining concepts the learner already knows; be honest

4. **Realistic `material_density`** — Dense notebooks take longer; match to available time

5. **Clear `focus_areas`** — If you emphasize "performance optimization," agents will include benchmarking and profiling

## Advanced: Creating New Profiles

Templates are just YAML files. A learner profile has exactly these seven keys —
all required, flat (no nested objects), enum fields from the lists above:

```yaml
# my-learner.yaml
name: "Data Scientist in Transition"
description: "Statistics and Python; new to software-engineering practices."
prior_knowledge:
  - "Statistics and probability"
  - "Python for analysis (pandas, numpy)"
environment: "jupyter_notebook"
material_density: "standard"
learning_style: "project_based"
background_context: "Goal: build end-to-end ML pipelines; coming from academia."
```

Then use it:
```bash
forged build --topic "..." --learner-profile templates/examples/learner-data-scientist-transition.yaml
```

## FAQ

**Q: Can I mix and match templates from different profiles?**
A: Yes! Use a learner profile from one and topic spec from another.

**Q: What if I only provide some fields?**
A: You can't — within a file, *every* field is required and unknown keys are
rejected (the loader fails fast before any API call). What's optional is the
*flag*: omit `--learner-profile` or `--topic-spec` entirely and forged uses a
sensible built-in default for that whole file.

**Q: How do I know what material_density to pick?**
A: Match it to depth/time: `dense` for terse review, `standard` for a normal
lesson, `rich` for a thorough walkthrough with extra examples.

**Q: Can I edit templates after using them?**
A: Yes. Edit the YAML file and re-run; forged will generate new content with updated parameters.

## See Also

- **Architecture Docs**: `docs/architecture/01-input-specification.md` (field design rationale)
- **Implementation Docs**: `docs/architecture/02-agent-input-flow.md` (how context flows through agents)
- **Main README**: `README.md` (general forged usage)
