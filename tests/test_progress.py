"""Spinner behaviour for the CLI's progress indicator.

Recovered verbatim from `tests/test_pipeline.py` when that file was deleted along with
the linear engine (2026-08-08). `forged/progress.py` survives — it is what `forged learn`
uses to show stage progress — so its tests had to survive too; without them the module
dropped from full coverage to 37%.
"""

from __future__ import annotations

import io


class _FakeTTY(io.StringIO):
    """A writable stream that reports itself as interactive."""

    def isatty(self) -> bool:
        return True


def test_spinner_is_inactive_when_stream_is_not_a_tty():
    from forged.progress import Spinner

    stream = io.StringIO()  # StringIO.isatty() is False
    spinner = Spinner("planner", stream=stream).start()
    spinner.stop()

    assert spinner._active is False
    assert stream.getvalue() == ""  # no animation, nothing to clear


def test_spinner_animates_then_clears_on_a_tty():
    import time

    from forged.progress import FRAME_INTERVAL_SECONDS, SPINNER_FRAMES, Spinner

    stream = _FakeTTY()
    with Spinner("planner", stream=stream):
        time.sleep(FRAME_INTERVAL_SECONDS * 2)  # let at least one frame render

    output = stream.getvalue()
    assert any(frame in output for frame in SPINNER_FRAMES)  # animated
    assert output.endswith("\r\033[K")  # line cleared on exit
