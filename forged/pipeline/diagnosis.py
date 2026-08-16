"""Deterministic diagnoses added to the revision brief (doc 20, C1).

The brief already reports *what* failed — the failing cell indices and the interpreter's
error line. This module adds *why*, for failure shapes that a code author demonstrably
cannot infer from the symptom alone.

Currently one shape: the **delimiter collision**. An `artifact` lesson that authors a
document embeds that document in a Python string literal; when the document is about
code, its own examples contain docstrings, and the first one closes the literal early.
The 2026-08-13 run hit this in four consecutive iterations and never named it, spending
74K tokens rewriting around a bug nobody had described.

Everything here is a pure string/AST check on artifacts we already have. No LLM, no cost,
and nothing is skipped or short-circuited: this augments the brief, it never replaces
execution (see doc 20, "What we are deliberately NOT doing").
"""

from __future__ import annotations

import ast
import json
import re
from collections.abc import Sequence

# A triple-quote opener, allowing the usual string prefixes (r, b, f, u and pairs).
_TRIPLE_OPENER = re.compile(r"""[rRbBfFuU]{0,2}("{3}|'{3})""")
_TRIPLE_QUOTE = re.compile(r'"{3}|\'{3}')

# A well-formed triple-quoted literal contributes exactly ONE closing delimiter after its
# opener. Two or more means the content being embedded carries delimiters of its own.
_DELIMITERS_IMPLYING_NESTED_CONTENT = 2


def cell_has_delimiter_collision(source: str) -> bool:
    """True when this cell fails to parse *because* embedded content closed a literal.

    Deliberately conservative — all four conditions must hold:

    1. the cell is Python at all — IPython magics and shell escapes are excluded, see
       `_is_not_python` for why this one is load-bearing;
    2. the cell does not parse (a cell that parses failed for some other reason, e.g. the
       runtime `SystemExit` in the 2026-08-13 run's validator cell);
    3. it opens a triple-quoted literal at all;
    4. two or more triple-quote delimiters follow that opener, which a well-formed
       literal never produces.

    Precision is worth more than recall here: a diagnosis attached to every SyntaxError
    trains the reader to skip it.
    """
    if _is_not_python(source):
        return False
    try:
        ast.parse(source)
    except SyntaxError:
        pass
    except ValueError:
        # e.g. source containing null bytes — not a collision, and not our problem.
        return False
    else:
        return False

    opener = _TRIPLE_OPENER.search(source)
    if opener is None:
        return False

    following = _TRIPLE_QUOTE.findall(source[opener.end() :])
    return len(following) >= _DELIMITERS_IMPLYING_NESTED_CONTENT


def diagnose_delimiter_collision(
    notebook_json: str, failed_cells: Sequence[int]
) -> str | None:
    """Name the collision for the failed cells that show it, or None.

    Returns a single sentence for the revision brief: the mechanism plus the idiom that
    avoids it. Degrades to None on any malformed input — a missing diagnosis costs an
    iteration, a raised exception costs the run.
    """
    try:
        cells = json.loads(notebook_json).get("cells", [])
    except (json.JSONDecodeError, AttributeError, TypeError):
        return None

    colliding = [
        index
        for index in sorted(set(failed_cells))
        if 0 <= index < len(cells) and cell_has_delimiter_collision(_source_of(cells[index]))
    ]
    if not colliding:
        return None

    which = (
        f"cell {colliding[0]}"
        if len(colliding) == 1
        else "cells " + ", ".join(str(i) for i in colliding)
    )
    return (
        f"**Likely cause — delimiter collision in {which}.** The text being embedded "
        "contains the same triple-quote delimiter used to embed it (file content that is "
        "itself code carries docstrings and fenced blocks), so the literal closes early "
        "and the rest of the cell is parsed as code. Do not re-indent or re-escape it: "
        "write the file with a `%%writefile <path>` cell, which takes the rest of the "
        "cell verbatim and involves no Python string literal at all. Where the content "
        "must be computed rather than literal, build it from a list of lines instead of "
        "one large literal."
    )


def _is_not_python(source: str) -> bool:
    """True for cells the Python parser was never meant to read.

    This guard is what stops C1 from contradicting C2. `%%writefile <path>` is the idiom
    the code author is told to use precisely *because* it takes the rest of the cell
    verbatim — so its body is arbitrary text that may contain any number of triple
    quotes, and `ast.parse` rejects the `%%` line itself. Without this check the detector
    fires on every correct `%%writefile` cell whose content holds two or more docstrings,
    i.e. it reports the fix as the bug.

    Line magics (`%pip …`) and shell escapes (`!ls`) are excluded for the same reason.
    """
    for line in source.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        return stripped.startswith(("%%", "%", "!"))
    return False


def _source_of(cell: object) -> str:
    """nbformat allows `source` as a string or a list of lines."""
    if not isinstance(cell, dict):
        return ""
    source = cell.get("source", "")
    if isinstance(source, list):
        return "".join(str(part) for part in source)
    return str(source)
