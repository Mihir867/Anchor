"""Live progress for a run, so the client can show what the engine is doing right now.

The HTTP service installs a reporter for the worker thread that runs a job (`reporting(fn)`);
pipeline code calls `report(stage, **info)` at stage boundaries. Without a reporter (CLI runs,
tests) `report` is a no-op. Reporters must never raise into the pipeline.

Stages, in order: crawling -> researching -> mining -> writing -> rendering -> saving.
`info` accumulates across stages (brand, industry, evidence counts, current post...).

Cancellation is cooperative: `reporting(fn, should_stop)` makes every `report` call raise
`Cancelled` once `should_stop()` is true, so a stopped job exits at its next stage boundary.
"""

from __future__ import annotations

import logging
import threading
from contextlib import contextmanager
from typing import Callable

log = logging.getLogger("anchor.progress")

Reporter = Callable[[str, dict], None]
_local = threading.local()


class Cancelled(BaseException):
    """The job was stopped by the user. A BaseException so broad `except Exception` handlers
    inside the pipeline do not swallow it."""


@contextmanager
def reporting(fn: Reporter, should_stop: Callable[[], bool] | None = None):
    prev = getattr(_local, "fn", None), getattr(_local, "info", None), getattr(_local, "stop", None)
    _local.fn, _local.info, _local.stop = fn, {}, should_stop
    try:
        yield
    finally:
        _local.fn, _local.info, _local.stop = prev


def report(stage: str, **info) -> None:
    stop = getattr(_local, "stop", None)
    if stop is not None and stop():
        raise Cancelled()
    fn: Reporter | None = getattr(_local, "fn", None)
    if fn is None:
        return
    _local.info.update({k: v for k, v in info.items() if v is not None})
    try:
        fn(stage, dict(_local.info))
    except Exception as exc:  # progress is cosmetic; never break a run over it
        log.debug("progress reporter failed: %s", exc)
