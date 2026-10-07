"""Background jobs with progress events and cancellation.

One worker thread, so model jobs never run at the same time and fight for VRAM.
"""

from __future__ import annotations

import logging
import threading
import uuid
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from typing import Any

log = logging.getLogger(__name__)

Event = dict[str, Any]
FINAL_STATES = frozenset({"done", "error", "cancelled"})


class JobCancelled(Exception):
    """Raised inside a job when the user cancelled it."""


class Job:
    def __init__(self, kind: str) -> None:
        self.id = uuid.uuid4().hex[:12]
        self.kind = kind
        self.state = "queued"
        self.result: dict[str, Any] | None = None
        self.error: str | None = None
        self._events: list[Event] = []
        self._changed = threading.Condition()
        self._cancel = threading.Event()

    def report(self, stage: str, progress: float, message: str = "", **extra: Any) -> None:
        """Record a progress event. `progress` is 0..1 within the whole job."""
        self._push({"type": "progress", "stage": stage, "progress": progress,
                    "message": message, **extra})

    def check_cancel(self) -> None:
        if self._cancel.is_set():
            raise JobCancelled()

    def cancel(self) -> None:
        self._cancel.set()

    def _push(self, event: Event) -> None:
        with self._changed:
            self._events.append(event)
            self._changed.notify_all()

    def _finish(self, state: str, **fields: Any) -> None:
        self.state = state
        self._push({"type": state, **fields})

    def snapshot(self) -> Event:
        return {"id": self.id, "kind": self.kind, "state": self.state,
                "result": self.result, "error": self.error}

    def stream(self, poll_seconds: float = 15.0) -> Iterator[Event]:
        """Yield every event from the start, then new ones until the job ends.

        Yields a keep-alive event when nothing happens for `poll_seconds`.
        """
        index = 0
        while True:
            with self._changed:
                if index >= len(self._events) and self.state not in FINAL_STATES:
                    self._changed.wait(poll_seconds)
                pending = self._events[index:]
            index += len(pending)
            yield from pending
            if not pending:
                if self.state in FINAL_STATES:
                    return
                yield {"type": "keepalive"}
            elif pending[-1]["type"] in FINAL_STATES:
                return


class JobManager:
    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="job")

    def submit(self, kind: str, work: Callable[[Job], dict[str, Any]]) -> Job:
        job = Job(kind)
        self._jobs[job.id] = job
        self._executor.submit(self._run, job, work)
        return job

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    def _run(self, job: Job, work: Callable[[Job], dict[str, Any]]) -> None:
        job.state = "running"
        try:
            job.check_cancel()
            job.result = work(job)
            job._finish("done", result=job.result)
        except JobCancelled:
            log.info("job %s (%s) cancelled", job.id, job.kind)
            job._finish("cancelled")
        except Exception as exc:  # report every failure to the UI
            log.exception("job %s (%s) failed", job.id, job.kind)
            job.error = f"{type(exc).__name__}: {exc}"
            job._finish("error", error=job.error)
