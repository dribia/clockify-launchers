"""Background worker helpers.

Domain/infrastructure calls stay synchronous; the UI submits them to a
bounded executor and marshals results back to the GTK main loop.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from gi.repository import GLib

log = logging.getLogger(__name__)

_EXECUTOR = ThreadPoolExecutor(max_workers=4, thread_name_prefix="cl-worker")


def run_async(
    work: Callable[[], Any],
    on_done: Callable[[Any], None],
    on_error: Callable[[Exception], None] | None = None,
) -> None:
    """Run ``work`` off the main thread; deliver the result on the main loop."""

    def _task() -> None:
        try:
            result = work()
        except Exception as exc:
            log.debug("worker error", exc_info=True)
            if on_error is not None:
                error = exc  # bind: `exc` is cleared when the except block exits
                GLib.idle_add(lambda: (on_error(error), False)[1])
            else:
                log.error("unhandled worker error: %s", exc)
            return
        GLib.idle_add(lambda: (on_done(result), False)[1])

    _EXECUTOR.submit(_task)
