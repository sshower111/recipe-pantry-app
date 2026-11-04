"""Background ingest jobs for the API: links shared from the iPhone are downloaded and parsed
on this machine, one at a time, while the app polls for progress.

The queue lives in memory: restarting uvicorn drops queued jobs (share the link again).
Each job runs ``ingest(url)``, which ``api/app.py`` wires to ``pipeline.ingest.ingest_url``
(with ``skip_existing``, so an already-stored post is answered at once without a download).
"""

from __future__ import annotations

import logging
import queue
import threading
import uuid
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal

log = logging.getLogger(__name__)

JobStatus = Literal["queued", "running", "done", "failed"]


@dataclass
class IngestJob:
    id: str
    url: str
    status: JobStatus = "queued"
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds"))
    finished_at: str | None = None
    recipe_id: int | None = None
    title: str | None = None
    # added | updated | skipped (already stored), as `main.py ingest` reports it
    result: str | None = None
    # ready | needs_recipe | not_recipe: whether the post had an ingredient list
    recipe_status: str | None = None
    message: str | None = None
    # "Check again": re-download a post already stored instead of answering "skipped"
    refresh: bool = False

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


class IngestQueue:
    """One worker thread; jobs run in the order they were shared."""

    def __init__(self, ingest: Callable[[str, bool], Any], key: Callable[[str], str] = lambda url: url,
                 keep: int = 50) -> None:
        self._ingest = ingest
        self._key = key  # canonical URL, so share-link variants count as the same post
        self._keep = keep
        self._jobs: dict[str, IngestJob] = {}
        self._pending: queue.Queue[IngestJob] = queue.Queue()
        self._lock = threading.Lock()
        self._worker: threading.Thread | None = None

    def submit(self, url: str, refresh: bool = False) -> IngestJob:
        """Queue a link, or return the job already queued or running for the same post."""
        key = self._key(url)
        with self._lock:
            for job in self._jobs.values():
                if job.status in ("queued", "running") and self._key(job.url) == key:
                    return job
            job = IngestJob(id=uuid.uuid4().hex[:12], url=url, refresh=refresh)
            self._jobs[job.id] = job
            self._trim()
            if self._worker is None or not self._worker.is_alive():
                self._worker = threading.Thread(target=self._run, name="ingest-worker", daemon=True)
                self._worker.start()
        self._pending.put(job)
        return job

    def get(self, job_id: str) -> IngestJob | None:
        return self._jobs.get(job_id)

    def recent(self) -> list[IngestJob]:
        """Newest first."""
        return sorted(self._jobs.values(), key=lambda job: job.created_at, reverse=True)

    def _trim(self) -> None:
        finished = [j for j in self.recent() if j.status in ("done", "failed")]
        for job in finished[self._keep:]:
            del self._jobs[job.id]

    def _run(self) -> None:
        while True:
            job = self._pending.get()
            job.status = "running"
            try:
                result = self._ingest(job.url, job.refresh)
                job.recipe_id = result.recipe_id
                job.result = result.status
                job.title = result.title or (result.recipe.title if result.recipe else None)
                job.recipe_status = result.recipe_status
                job.message = result.status_note
                job.status = "done"
            except Exception as exc:  # report it to the app; keep the worker alive
                log.warning("Ingest of %s failed: %s", job.url, exc, exc_info=True)
                job.message = str(exc) or type(exc).__name__
                job.status = "failed"
            finally:
                job.finished_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
                self._pending.task_done()
