"""A minimal terminal spinner for long, silent stages (e.g. LLM calls).

The orchestrator goes quiet for 20–30s during a model call. Without feedback the
terminal looks hung. This spinner rewrites a single line with an elapsed-seconds
counter while a stage runs, then clears it so the caller's own status line lands on
a fresh line.

It is a no-op whenever stdout is not an interactive TTY (piped output, CI, tests),
so it never pollutes captured output.
"""

from __future__ import annotations

import sys
import threading
import time
from types import TracebackType

SPINNER_FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
FRAME_INTERVAL_SECONDS = 0.1


class Spinner:
    """Context manager that animates `<label> … (Ns)` on one line until it exits.

    Inactive (a no-op) when `stream` is not a TTY, so non-interactive callers get
    clean, spinner-free output.
    """

    def __init__(self, label: str, stream=None):
        self._label = label
        self._stream = stream if stream is not None else sys.stdout
        self._active = bool(getattr(self._stream, "isatty", lambda: False)())
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> Spinner:
        if self._active and self._thread is None:
            self._thread = threading.Thread(target=self._spin, daemon=True)
            self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join()
            self._thread = None
            self._clear_line()

    def __enter__(self) -> Spinner:
        return self.start()

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.stop()

    def _spin(self) -> None:
        start = time.perf_counter()
        frame = 0
        while not self._stop.wait(FRAME_INTERVAL_SECONDS):
            elapsed = time.perf_counter() - start
            glyph = SPINNER_FRAMES[frame % len(SPINNER_FRAMES)]
            self._stream.write(f"\r  {glyph} {self._label} … ({elapsed:.0f}s)")
            self._stream.flush()
            frame += 1

    def _clear_line(self) -> None:
        self._stream.write("\r\033[K")
        self._stream.flush()
