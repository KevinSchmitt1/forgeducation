"""The critique digest — findings accumulated across every revision iteration.

Every agent in the loop reads exactly ``revision_brief_v{iteration - 1}`` (verified
across code_author.py, planner.py, content_reviser.py), so each iteration's critique
supersedes the last: iteration 3's rewrite knew nothing of what iterations 0–2 found.
That is the mechanism behind quality declining after an early peak — a rewrite is a
fresh roll, not a cumulative improvement (docs/architecture/22 → D5).

This module builds the artifact that fixes it: a ``CritiqueDigest`` the Reviser
maintains **across** iterations — every finding from every iteration, deduplicated and
ordered by consequence, appended to rather than replaced. It costs nothing new; the
findings already exist. It is the artifact an informed remake reads (R7).

Purely deterministic — no LLM, no randomness. Same findings in → same digest out.

Ordering is **by consequence, not by severity alone**. The founding defect (D3) was a
root-cause finding filed LOW and buried: the self-referential ``PASSWORD`` validator
bug was reported as a style nitpick in three separate iterations and never acted on. A
finding that *recurs* across iterations is one that repeated patching failed to remove
— the C6 non-convergence signal — so recurrence leads the sort. A persistent low-
severity finding outranks a one-off high-severity one precisely because the transient
blocker is already carried by the per-iteration brief and the execution report (R2),
while the recurring root cause is the thing a remake most needs to see.

Deduplication is mechanical: the same issue is restated across critics and across
iterations in different words, and (because the notebook is rewritten each round) at
different cell indices, so it cannot be keyed on location. Findings are clustered by a
document-frequency-weighted token-overlap within the same scope — rare, distinctive
tokens (``password``, ``regex``, ``forbidden``) carry the signal; common filler does
not. The threshold is tuned on the in-repo corpus (tests/corpus/doc22-regression-run)
so the four ``PASSWORD`` restatements collapse into one cluster while unrelated findings
stay apart.
"""

from __future__ import annotations

import math
import re
from collections.abc import Sequence
from dataclasses import dataclass

from .state import Evidence, IterationFindings, Scope, Severity

# ── Tuning constants ─────────────────────────────────────────────────────────────

# Two findings in the same scope are the "same issue" when their DF-weighted token
# overlap reaches this. Calibrated on the corpus: at 0.33 the four PASSWORD
# restatements (iters 1–3, both critics) form one cluster and every other cluster
# stays single-issue. Lower risks merging distinct findings; higher splits the
# PASSWORD restatements back apart. See the module docstring.
CLUSTER_THRESHOLD = 0.33

# Only tokens this long carry topical signal; shorter ones are almost all filler.
_MIN_TOKEN_LEN = 4

# Ranked so max() picks the worst severity in a cluster, and the sort can read it.
_SEVERITY_RANK: dict[Severity, int] = {"BLOCKER": 4, "HIGH": 3, "MEDIUM": 2, "LOW": 1}

# High-frequency words that survive the length filter but carry no topical signal.
# Kept deliberately small — the DF weighting already down-weights common tokens, so
# this only removes the few frequent long words that would otherwise dilute overlap.
_STOPWORDS = frozenset({
    "the", "an", "and", "for", "with", "are", "that", "this", "from", "into",
    "using", "use", "uses", "used", "which", "may", "can", "will", "would",
    "should", "could", "not", "its", "also", "each", "other", "more", "most",
    "some", "when", "where", "what", "how", "than", "then", "such", "but", "has",
    "have", "had", "does", "done", "being", "been", "very", "only", "just",
    "still", "even", "much", "many", "any", "all", "both", "because", "there",
    "their", "they", "them", "thus", "were", "was",
})

_TOKEN_RE = re.compile(r"[a-z0-9']+")


# ── Value objects ──────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class DigestEntry:
    """One deduplicated issue, aggregated across every iteration it appeared in.

    text        — the representative wording (the cluster's worst-severity, most
                  detailed member); the author reads this, so it is a real sentence.
    severity    — the worst severity seen across the cluster.
    scope       — the shared scope of the cluster (clustering never crosses scopes).
    sources     — which critics raised it, sorted (e.g. ("reviewer", "student")).
    iterations  — the distinct iterations it was raised in, sorted ascending.
    occurrences — total findings folded into this entry (>= len(iterations)).
    """

    text: str
    severity: Severity
    scope: Scope
    sources: tuple[str, ...]
    iterations: tuple[int, ...]
    occurrences: int

    @property
    def recurrence(self) -> int:
        """How many distinct iterations raised this issue.

        The consequence signal: a recurrence above 1 means the issue survived at
        least one round of repair, which is what lifts it up the digest.
        """
        return len(self.iterations)


@dataclass(frozen=True)
class CritiqueDigest:
    """Every finding from every iteration, deduplicated and ordered by consequence."""

    entries: tuple[DigestEntry, ...] = ()

    @property
    def is_empty(self) -> bool:
        return not self.entries


# ── Internal helpers ─────────────────────────────────────────────────────────────


def _tokens(text: str) -> frozenset[str]:
    """Distinctive content tokens of a finding: lowercased, long enough, non-filler."""
    return frozenset(
        w
        for w in _TOKEN_RE.findall(text.lower())
        if len(w) >= _MIN_TOKEN_LEN and w not in _STOPWORDS
    )


def _weighted_overlap(
    a: frozenset[str], b: frozenset[str], idf: dict[str, float]
) -> float:
    """DF-weighted overlap coefficient of two token sets, in [0, 1].

    Overlap (not Jaccard) because findings vary a lot in length — the shorter one
    should not be penalised for the longer one's extra words. Each shared token is
    weighted by its inverse document frequency, so a rare, distinctive token
    (``password``) counts for far more than a common one (``code``) — which is what
    makes the clustering track the actual issue rather than shared boilerplate.
    """
    shared = a & b
    if not shared:
        return 0.0
    num = sum(idf[t] for t in shared)
    denom = min(sum(idf[t] for t in a), sum(idf[t] for t in b))
    return num / denom if denom else 0.0


class _UnionFind:
    """Minimal union-find so transitively-similar findings land in one cluster."""

    def __init__(self, n: int) -> None:
        self._parent = list(range(n))

    def find(self, x: int) -> int:
        while self._parent[x] != x:
            self._parent[x] = self._parent[self._parent[x]]
            x = self._parent[x]
        return x

    def union(self, a: int, b: int) -> None:
        self._parent[self.find(a)] = self.find(b)


def _cluster(
    flat: list[tuple[int, Evidence]], idf: dict[str, float]
) -> list[list[int]]:
    """Group finding indices into clusters of the same restated issue.

    Only findings in the same scope may cluster: "there is too much machinery"
    (content) and "this cell raises" (code) are never the same issue even if they
    share words. Within a scope, any pair over CLUSTER_THRESHOLD is unioned, so a
    chain of near-duplicates collapses into one cluster transitively.
    """
    n = len(flat)
    token_sets = [_tokens(ev.text) for _, ev in flat]
    uf = _UnionFind(n)
    for i in range(n):
        for j in range(i + 1, n):
            if flat[i][1].scope != flat[j][1].scope:
                continue
            if _weighted_overlap(token_sets[i], token_sets[j], idf) >= CLUSTER_THRESHOLD:
                uf.union(i, j)
    groups: dict[int, list[int]] = {}
    for i in range(n):
        groups.setdefault(uf.find(i), []).append(i)
    return list(groups.values())


def _entry_from_cluster(
    cluster: list[int], flat: list[tuple[int, Evidence]]
) -> DigestEntry:
    """Aggregate one cluster of findings into a single DigestEntry."""
    members = [flat[i] for i in cluster]
    severity = max((ev.severity for _, ev in members), key=lambda s: _SEVERITY_RANK[s])
    # Representative wording: the worst-severity member, and among those the most
    # detailed (longest) — a fuller sentence is more useful to the author than a terse
    # restatement. Deterministic ties: lowest iteration, then the text itself.
    representative = min(
        members,
        key=lambda m: (
            -_SEVERITY_RANK[m[1].severity],
            -len(m[1].text),
            m[0],
            m[1].text,
        ),
    )
    return DigestEntry(
        text=representative[1].text,
        severity=severity,
        scope=members[0][1].scope,
        sources=tuple(sorted({ev.source for _, ev in members if ev.source})),
        iterations=tuple(sorted({it for it, _ in members})),
        occurrences=len(members),
    )


def _order_key(entry: DigestEntry) -> tuple:
    """Sort key implementing "ordered by consequence".

    Recurrence leads: a finding that survived repeated patching is the highest-
    consequence signal a remake can receive (D3/C6). Severity breaks recurrence ties;
    then first-seen iteration (older, longer-lived issues first); then text, purely so
    the order is stable and reproducible.
    """
    return (
        -entry.recurrence,
        -_SEVERITY_RANK[entry.severity],
        entry.iterations[0] if entry.iterations else 0,
        entry.text,
    )


# ── Public API ───────────────────────────────────────────────────────────────────


def build_digest(history: Sequence[IterationFindings]) -> CritiqueDigest:
    """Build the accumulated, deduplicated, consequence-ordered critique digest.

    Pure function of the accumulated per-iteration findings: rebuilding it from the
    same history always yields the same digest, so the Reviser can recompute it each
    iteration rather than mutating a running one — no order-dependence, no drift.
    """
    flat: list[tuple[int, Evidence]] = [
        (record.iteration, ev)
        for record in history
        for ev in record.findings
        if ev.text.strip()
    ]
    if not flat:
        return CritiqueDigest()

    # Inverse document frequency across all findings, so distinctive tokens dominate
    # the overlap and shared boilerplate does not. Recomputed per build — the corpus
    # is tiny (tens of findings) and this keeps the digest a pure function of history.
    n_docs = len(flat)
    doc_freq: dict[str, int] = {}
    for _, ev in flat:
        for t in _tokens(ev.text):
            doc_freq[t] = doc_freq.get(t, 0) + 1
    # Smoothed IDF: log((N + 1) / df) is strictly positive even for a token that
    # appears in every finding (df == N). Plain log(N/df) collapses to zero there,
    # which on a tiny corpus (a couple of early findings) would make two identical
    # findings score zero overlap and refuse to cluster.
    idf = {t: math.log((n_docs + 1) / df) for t, df in doc_freq.items()}

    clusters = _cluster(flat, idf)
    entries = sorted((_entry_from_cluster(c, flat) for c in clusters), key=_order_key)
    return CritiqueDigest(entries=tuple(entries))


def render_digest(digest: CritiqueDigest, limit: int | None = None) -> str:
    """Render the digest as the markdown block the revision brief carries.

    Returns "" for an empty digest so the caller can append unconditionally. When
    `limit` is set, only the top-N (most consequential) entries are shown, with a
    line noting how many were elided — the head is what matters for a remake.
    """
    if digest.is_empty:
        return ""
    shown = digest.entries if limit is None else digest.entries[:limit]
    lines = [
        "## Accumulated critique (every iteration)\n",
        "Deduplicated across all iterations, **most persistent first**. A finding that "
        "recurs across iterations survived earlier repair — treat it as a likely root "
        "cause, not a nitpick.\n\n",
    ]
    for i, entry in enumerate(shown, start=1):
        iters = ", ".join(str(x) for x in entry.iterations)
        srcs = ", ".join(entry.sources) if entry.sources else "unknown"
        recur = (
            f"seen in iters {iters} (×{entry.occurrences})"
            if entry.recurrence > 1
            else f"iter {iters}"
        )
        lines.append(
            f"{i}. [{entry.severity} · {entry.scope} · {recur} · {srcs}] {entry.text}\n"
        )
    if limit is not None and len(digest.entries) > limit:
        lines.append(f"\n_({len(digest.entries) - limit} lower-consequence finding(s) omitted.)_\n")
    return "".join(lines)
