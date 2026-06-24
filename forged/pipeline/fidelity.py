"""Deterministic topic-fidelity check: does the executed notebook still cover
every capability the topic asked for?

The R1 defect was that the revision loop could *silently* drop a capability the
`--topic` explicitly requested (e.g. shipping a "setup local LLMs" notebook for a
"setup AND train" topic). This module makes that visible. It reads the executed
notebook text and the requested capabilities (the topic's learning objectives /
title / focus areas, persisted as `topic_spec.json`) and reports which
capabilities are no longer covered.

Like `structure.py`, this is the deterministic backstop: no LLM, no randomness,
same inputs → same output. It does not judge teaching quality — it only asks "is
this capability present at all?". It is a tripwire that flips a silent drop into a
recorded one, NOT a perfect judge; pair it with the critic personas' flagging.

Coverage heuristic. Each capability is reduced to its salient terms (content words).
A capability is "covered" when the notebook contains at least HALF of its
**distinctive** terms — salient terms that do not also appear in another requested
capability. Two ideas combine here:
  - Distinctive terms drop words shared across capabilities ("local"/"llm" in both
    "setup a local LLM" and "fine-tune the LLM"), so they cannot certify the wrong
    capability.
  - The half-of-terms bar stops a single term that happens to appear elsewhere in
    the notebook (e.g. "model", named only in the training objective but written in
    the setup code) from masking a real drop — one stray match is not coverage.
Together they let a full drop surface (the training terms "lora"/"fine"/"tune"
vanish) while staying conservative about *claiming a capability missing* — the
costly false positive.

Dependency: nbformat + stdlib only. No imports from other pipeline modules, so
state.py / reviser.py can use it freely.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass

import nbformat

# Salient terms must be at least this long; shorter tokens carry little signal.
MIN_TERM_LENGTH = 3

# A capability is covered when at least this fraction of its distinctive terms
# appear in the notebook. Half stops a single stray term match from certifying a
# capability that was actually dropped (see module docstring).
COVERAGE_THRESHOLD = 0.5

# Filler words that never make a capability distinctive. Deliberately small —
# teaching verbs ("build", "train") ARE distinctive and must NOT be stripped.
_STOPWORDS = frozenset(
    {
        "the", "and", "for", "with", "into", "from", "your", "you",
        "use", "using", "able", "will", "that", "this", "how", "what", "why",
        "an", "of", "to", "in", "on", "or", "is", "are", "be", "as", "it",
        "its", "their", "them", "they", "can", "via", "per", "out",
    }
)

_TOKEN_RE = re.compile(r"[a-z0-9]+")


# ── Result ─────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class TopicFidelityReport:
    """Deterministic verdict on whether the notebook still covers the topic.

    covered/missing partition the requested capabilities. `missing` non-empty ⇒ a
    requested capability was dropped — the signal the curriculum planner consumes.
    """

    covered: tuple[str, ...]
    missing: tuple[str, ...]

    @property
    def is_faithful(self) -> bool:
        """True when no requested capability was dropped."""
        return not self.missing


# ── Internals ──────────────────────────────────────────────────────────────────


def _terms(text: str) -> set[str]:
    """Salient content terms of a string: long-enough, non-stopword tokens."""
    return {
        tok
        for tok in _TOKEN_RE.findall(text.lower())
        if len(tok) >= MIN_TERM_LENGTH and tok not in _STOPWORDS
    }


def _distinctive_terms(capabilities: list[str]) -> list[set[str]]:
    """For each capability, the salient terms that no OTHER capability shares.

    A term shared across capabilities (e.g. "model", "llm") is generic and cannot
    witness a specific capability's presence. When a capability has no distinctive
    terms (all of its words are shared), fall back to its full salient set so it can
    still be matched rather than being unverifiable.
    """
    per_cap = [_terms(c) for c in capabilities]
    term_counts: Counter[str] = Counter()
    for terms in per_cap:
        term_counts.update(terms)

    distinctive: list[set[str]] = []
    for terms in per_cap:
        unique = {t for t in terms if term_counts[t] == 1}
        distinctive.append(unique or terms)
    return distinctive


# ── Assessment ─────────────────────────────────────────────────────────────────


def assess_capability_coverage(
    haystack_text: str, capabilities: list[str]
) -> TopicFidelityReport:
    """Report which capabilities the given text covers, via distinctive-term coverage.

    The reusable core shared by the per-notebook check (`assess_topic_fidelity`) and
    the course-level union check (`forged.curriculum.fidelity`): a capability is
    *covered* when at least `COVERAGE_THRESHOLD` of its distinctive terms appear in
    `haystack_text`. Distinctiveness is computed among the requested capabilities, so a
    term shared across them cannot certify the wrong one.

    Args:
        haystack_text: free text to search (notebook cell sources, or the union of a
            course's module capabilities).
        capabilities: the requested capabilities; empty/blank entries are ignored.

    Returns:
        A TopicFidelityReport partitioning the (non-blank) capabilities into covered
        and missing. With no capabilities requested, both are empty and is_faithful.
    """
    requested = [c for c in capabilities if c and c.strip()]
    if not requested:
        return TopicFidelityReport(covered=(), missing=())

    haystack_terms = _terms(haystack_text)
    distinctive = _distinctive_terms(requested)
    covered: list[str] = []
    missing: list[str] = []
    for capability, terms in zip(requested, distinctive, strict=True):
        present = len(terms & haystack_terms)
        if terms and present >= COVERAGE_THRESHOLD * len(terms):
            covered.append(capability)
        else:
            missing.append(capability)

    return TopicFidelityReport(covered=tuple(covered), missing=tuple(missing))


def assess_topic_fidelity(
    notebook_content: str, capabilities: list[str]
) -> TopicFidelityReport:
    """Report which requested capabilities the executed notebook no longer covers.

    Args:
        notebook_content: nbformat JSON of the notebook. Coverage is judged from the
            cell sources (code + markdown), where capability terms like `LoraConfig`
            or `trainer.train()` live — not from runtime output.
        capabilities: the requested capabilities — typically the topic's learning
            objectives, title, and focus areas. Empty/blank entries are ignored.

    Returns:
        A TopicFidelityReport partitioning the (non-blank) capabilities into covered
        and missing. With no capabilities requested, both are empty and is_faithful.
    """
    requested = [c for c in capabilities if c and c.strip()]
    if not requested:
        return TopicFidelityReport(covered=(), missing=())

    notebook = nbformat.reads(notebook_content, as_version=4)
    haystack = "\n".join(cell.source for cell in notebook.cells if cell.get("source"))
    return assess_capability_coverage(haystack, requested)
