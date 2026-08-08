"""`setup_logging` must be safe to call more than once per process.

The course orchestrator calls it once per module (doc 18 crash diagnostics), so a
run of N modules called it N times. Each call added a console handler and a file
handler to the root logger and removed nothing, which meant:

  - every earlier module's `pipeline.log` kept receiving later modules' records
    (visible in `runs/20260730-224009_.../module_0_.../pipeline.log`, which holds
    module 1's provisioning failure);
  - console output was duplicated once per module;
  - every module's log file stayed open for the life of the process.

The next paid run exists to be *read*, so contaminated logs cost real money.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from forged.logging_config import setup_logging


@pytest.fixture(autouse=True)
def _isolate_root_logger():
    """Give each test a clean root logger and put the original back afterwards.

    Without this, handlers installed here leak into every later test in the
    session — the same accumulation bug this module is about.
    """
    root = logging.getLogger()
    saved_handlers, saved_level = list(root.handlers), root.level
    root.handlers = []
    yield
    for handler in list(root.handlers):
        root.removeHandler(handler)
        handler.close()
    root.handlers = saved_handlers
    root.setLevel(saved_level)


def _file_handlers() -> list[logging.FileHandler]:
    return [h for h in logging.getLogger().handlers if isinstance(h, logging.FileHandler)]


@pytest.mark.unit
def test_repeated_calls_do_not_stack_handlers(tmp_path: Path) -> None:
    """Handler count must not grow with the number of calls.

    Asserted as "does not grow" rather than an absolute count because pytest's
    own log-capture handlers also live on the root logger; the contract here is
    about *our* handlers not accumulating, not about owning the root logger.
    """
    setup_logging(log_file=tmp_path / "one.log")
    after_first = len(logging.getLogger().handlers)

    setup_logging(log_file=tmp_path / "two.log")

    assert len(logging.getLogger().handlers) == after_first


@pytest.mark.unit
def test_an_earlier_modules_log_stops_receiving_records(tmp_path: Path) -> None:
    """The actual doc-18 defect: module 0's log recorded module 1's failure."""
    module_0, module_1 = tmp_path / "module_0.log", tmp_path / "module_1.log"

    setup_logging(log_file=module_0)
    logging.getLogger("forged.test").info("module 0 is running")
    setup_logging(log_file=module_1)
    logging.getLogger("forged.test").info("module 1 blew up")

    assert "module 0 is running" in module_0.read_text(encoding="utf-8")
    assert "module 1 blew up" not in module_0.read_text(encoding="utf-8")
    assert "module 1 blew up" in module_1.read_text(encoding="utf-8")


@pytest.mark.unit
def test_only_one_log_file_stays_open(tmp_path: Path) -> None:
    setup_logging(log_file=tmp_path / "one.log")
    setup_logging(log_file=tmp_path / "two.log")

    assert len(_file_handlers()) == 1


@pytest.mark.unit
def test_the_replaced_file_handler_is_closed(tmp_path: Path) -> None:
    """A run of N modules must not leave N log files open."""
    setup_logging(log_file=tmp_path / "one.log")
    # Grab the underlying file object first: Handler.close() sets .stream to None,
    # so the handler itself can no longer tell us whether the file was closed.
    first_stream = _file_handlers()[0].stream

    setup_logging(log_file=tmp_path / "two.log")

    assert first_stream.closed


@pytest.mark.unit
def test_handlers_installed_by_others_are_left_alone(tmp_path: Path) -> None:
    """Only our own handlers are swept — pytest's capture and any host
    application's logging config must survive a call."""
    foreign = logging.StreamHandler()
    logging.getLogger().addHandler(foreign)

    setup_logging(log_file=tmp_path / "one.log")
    setup_logging(log_file=tmp_path / "two.log")

    assert foreign in logging.getLogger().handlers
