"""Curriculum planner (Phase 2 / Half B) — see docs/architecture/13-curriculum-planner.md.

A new orchestration layer ABOVE the unchanged single-lesson pipeline. It decomposes an
over-large topic into an ordered course of module lessons, runs each module through the
existing `run_pipeline`, and assembles the modules into one course. It consumes R1's
`TopicFidelitySignal` (the only coupling to the lesson loop) and enforces a union-coverage
honesty invariant: the union of module capabilities must cover every requested capability.

Phase 1 (this commit) ships the plan-only slice: the course data model, the decomposition
persona/agent, and the deterministic course-fidelity check — no module orchestration yet.
"""

from __future__ import annotations

from .model import CourseSpec, ModuleSpec

__all__ = ["CourseSpec", "ModuleSpec"]
