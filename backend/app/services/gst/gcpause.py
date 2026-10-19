"""Pause Python's cyclic garbage collector while a reconciliation builds tens of thousands of small objects.

A recompute of 10,000 records against 10,000 books allocates about half a million short-lived containers (views,
tuples, dicts, rows) and frees them all by reference counting; none of them forms a reference cycle. Left on, the
collector still walks the growing heap again and again while they are alive: about a third of the matching time on the
build machine, and more on a slow shared one (CI took 10.37 s of a 10 s budget before this).

The switch is process-wide, so it is counted: the collector comes back on only when the last section that paused it
ends, and only if it was on when the first one began. A section lasts seconds. Anything that did form a cycle meanwhile
is collected by the first collection after it, as it always would have been."""

from __future__ import annotations

import gc
import threading
from contextlib import contextmanager
from typing import Iterator

_LOCK = threading.Lock()
_DEPTH = 0
_WAS_ENABLED = False


@contextmanager
def collector_paused() -> Iterator[None]:
    global _DEPTH, _WAS_ENABLED
    with _LOCK:
        if _DEPTH == 0:
            _WAS_ENABLED = gc.isenabled()
            gc.disable()
        _DEPTH += 1
    try:
        yield
    finally:
        with _LOCK:
            _DEPTH -= 1
            if _DEPTH == 0 and _WAS_ENABLED:
                gc.enable()


__all__ = ["collector_paused"]
