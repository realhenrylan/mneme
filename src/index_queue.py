"""Serialized index mutations and immutable query input snapshots."""

from __future__ import annotations

from concurrent.futures import Future
from dataclasses import dataclass
from queue import Queue
from threading import Lock, Thread
from typing import Any, Callable


@dataclass(frozen=True)
class IndexSnapshot:
    """The exact index view used to prepare one query."""

    collection: Any
    bm25: Any
    documents: tuple[str, ...]
    metadatas: tuple[dict, ...]
    ids: tuple[str, ...]
    manifest_version: int | None


@dataclass
class _Job:
    function: Callable[..., Any]
    args: tuple[Any, ...]
    kwargs: dict[str, Any]
    future: Future


class IndexQueue:
    """A small single-worker queue for add/modify/delete/rebuild operations."""

    _STOP = object()

    def __init__(self) -> None:
        self._queue: Queue[_Job | object] = Queue()
        self._lock = Lock()
        self._pending = 0
        self._last_error: str | None = None
        self._worker = Thread(target=self._run, name="mneme-index-worker", daemon=True)
        self._worker.start()

    def submit(self, function: Callable[..., Any], *args: Any, **kwargs: Any) -> Future:
        future: Future = Future()
        with self._lock:
            self._pending += 1
        self._queue.put(_Job(function, args, kwargs, future))
        return future

    def run(self, function: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        """Submit a job and wait for it, preserving existing synchronous APIs."""
        return self.submit(function, *args, **kwargs).result()

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "pending": self._pending,
                "running": self._pending > self._queue.qsize(),
                "last_error": self._last_error,
            }

    def _run(self) -> None:
        while True:
            job = self._queue.get()
            if job is self._STOP:
                self._queue.task_done()
                return
            assert isinstance(job, _Job)
            try:
                job.future.set_result(job.function(*job.args, **job.kwargs))
                with self._lock:
                    self._last_error = None
            except BaseException as exc:
                job.future.set_exception(exc)
                with self._lock:
                    self._last_error = type(exc).__name__
            finally:
                with self._lock:
                    self._pending -= 1
                self._queue.task_done()

    def close(self, wait: bool = True) -> None:
        self._queue.put(self._STOP)
        if wait:
            self._worker.join(timeout=2.0)


def make_snapshot(
    collection: Any,
    bm25: Any,
    documents: list[str],
    metadatas: list[dict],
    ids: list[str],
    manifest_version: int | None,
) -> IndexSnapshot:
    """Copy query data so later mutations cannot change the selected rows."""
    return IndexSnapshot(
        collection=collection,
        bm25=bm25,
        documents=tuple(documents),
        metadatas=tuple(dict(metadata or {}) for metadata in metadatas),
        ids=tuple(ids),
        manifest_version=manifest_version,
    )
