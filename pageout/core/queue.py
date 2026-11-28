"""Export Queue: manage background export jobs with persistence."""

import json
import os
import threading
import time
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

from pageout.core.config import CONFIG_DIR


class JobStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class JobPriority(Enum):
    LOW = 0
    NORMAL = 1
    HIGH = 2


@dataclass
class ExportJob:
    """A single export job in the queue."""

    id: str
    name: str
    config: Dict[str, Any]
    status: JobStatus = JobStatus.PENDING
    priority: JobPriority = JobPriority.NORMAL
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    progress: float = 0.0  # 0.0 to 1.0
    current_page: int = 0
    total_pages: int = 0
    current_format: str = ""
    message: str = ""
    error: str = ""
    result: Optional[Dict[str, Any]] = None
    retry_count: int = 0
    max_retries: int = 0

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dict for persistence."""
        data = asdict(self)
        data["status"] = self.status.value
        data["priority"] = self.priority.value
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ExportJob":
        """Deserialize from dict."""
        data = dict(data)
        data["status"] = JobStatus(data["status"])
        data["priority"] = JobPriority(data["priority"])
        return cls(**data)


class ExportQueue:
    """Thread-safe export job queue with persistence."""

    QUEUE_FILE = os.path.join(CONFIG_DIR, "export_queue.json")
    MAX_HISTORY = 100  # Keep last 100 completed/failed jobs

    def __init__(
        self,
        progress_callback: Optional[Callable[[str, float, str], None]] = None,
        log_callback: Optional[Callable[[str, str], None]] = None,
        completion_callback: Optional[Callable[[ExportJob], None]] = None,
    ):
        self.jobs: Dict[str, ExportJob] = {}
        self._lock = threading.RLock()
        self._running_job_id: Optional[str] = None
        self._executor: Optional[ThreadPoolExecutor] = None
        self._futures: Dict[str, Future] = {}
        self._cancel_flags: Dict[str, threading.Event] = {}

        # Callbacks
        self.on_progress = progress_callback  # (job_id, progress, message)
        self.on_log = log_callback  # (job_id, message)
        self.on_complete = completion_callback  # (job)

        # Load persisted queue
        self._load()

    def _load(self):
        """Load queue from disk."""
        try:
            if os.path.exists(self.QUEUE_FILE):
                with open(self.QUEUE_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                for job_data in data.get("jobs", []):
                    job = ExportJob.from_dict(job_data)
                    # Only restore pending/paused jobs; completed/failed are history
                    if job.status in (JobStatus.PENDING, JobStatus.PAUSED, JobStatus.RUNNING):
                        job.status = JobStatus.PENDING  # Reset running to pending
                        self.jobs[job.id] = job
        except Exception:
            pass

    def _save(self):
        """Save queue to disk."""
        try:
            os.makedirs(CONFIG_DIR, exist_ok=True)
            # Save all jobs (including history)
            data = {"jobs": [job.to_dict() for job in self.jobs.values()]}
            # Limit history size
            if len(data["jobs"]) > self.MAX_HISTORY:
                # Keep pending/running first, then most recent completed/failed
                pending = [j for j in data["jobs"] if j["status"] in ("pending", "running", "paused")]
                history = [j for j in data["jobs"] if j["status"] in ("completed", "failed", "cancelled")]
                history.sort(key=lambda x: x.get("completed_at", ""), reverse=True)
                data["jobs"] = pending + history[: self.MAX_HISTORY - len(pending)]
            with open(self.QUEUE_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception:
            pass

    def add_job(
        self,
        name: str,
        config: Dict[str, Any],
        priority: JobPriority = JobPriority.NORMAL,
        max_retries: int = 0,
    ) -> str:
        """Add a new export job to the queue. Returns job ID."""
        job_id = str(uuid.uuid4())[:8]
        job = ExportJob(
            id=job_id,
            name=name,
            config=config,
            priority=priority,
            max_retries=max_retries,
        )
        with self._lock:
            self.jobs[job_id] = job
            self._save()
        return job_id

    def remove_job(self, job_id: str) -> bool:
        """Remove a job from the queue (if not running)."""
        with self._lock:
            job = self.jobs.get(job_id)
            if job and job.status not in (JobStatus.RUNNING,):
                del self.jobs[job_id]
                self._save()
                return True
            return False

    def cancel_job(self, job_id: str) -> bool:
        """Cancel a running or pending job."""
        with self._lock:
            job = self.jobs.get(job_id)
            if not job:
                return False

            if job.status == JobStatus.RUNNING:
                # Signal cancellation to the worker
                cancel_flag = self._cancel_flags.get(job_id)
                if cancel_flag:
                    cancel_flag.set()
                job.status = JobStatus.CANCELLED
                job.message = "Cancelling..."
            elif job.status in (JobStatus.PENDING, JobStatus.PAUSED):
                job.status = JobStatus.CANCELLED
            self._save()
            return True

    def pause_job(self, job_id: str) -> bool:
        """Pause a pending job (not running)."""
        with self._lock:
            job = self.jobs.get(job_id)
            if job and job.status == JobStatus.PENDING:
                job.status = JobStatus.PAUSED
                self._save()
                return True
            return False

    def resume_job(self, job_id: str) -> bool:
        """Resume a paused job."""
        with self._lock:
            job = self.jobs.get(job_id)
            if job and job.status == JobStatus.PAUSED:
                job.status = JobStatus.PENDING
                self._save()
                return True
            return False

    def retry_job(self, job_id: str) -> bool:
        """Retry a failed or cancelled job."""
        with self._lock:
            job = self.jobs.get(job_id)
            if job and job.status in (JobStatus.FAILED, JobStatus.CANCELLED):
                # Create a new job with same config
                self.add_job(
                    name=job.name + " (retry)",
                    config=job.config,
                    priority=job.priority,
                    max_retries=job.max_retries,
                )
                self._save()
                return True
            return False

    def get_job(self, job_id: str) -> Optional[ExportJob]:
        """Get a job by ID."""
        with self._lock:
            return self.jobs.get(job_id)

    def get_all_jobs(self) -> List[ExportJob]:
        """Get all jobs sorted by priority and creation time."""
        with self._lock:
            jobs = list(self.jobs.values())

            # Sort: running first, then by priority (high first), then by creation time
            def sort_key(job):
                status_order = {
                    JobStatus.RUNNING: 0,
                    JobStatus.PENDING: 1,
                    JobStatus.PAUSED: 2,
                    JobStatus.COMPLETED: 3,
                    JobStatus.FAILED: 4,
                    JobStatus.CANCELLED: 5,
                }
                return (status_order.get(job.status, 9), -job.priority.value, job.created_at)

            jobs.sort(key=sort_key)
            return jobs

    def get_pending_jobs(self) -> List[ExportJob]:
        """Get jobs that are ready to run (pending, high priority first)."""
        with self._lock:
            pending = [j for j in self.jobs.values() if j.status == JobStatus.PENDING]
            pending.sort(key=lambda j: (-j.priority.value, j.created_at))
            return pending

    def is_running(self) -> bool:
        """Check if any job is currently running."""
        with self._lock:
            return self._running_job_id is not None

    def get_running_job(self) -> Optional[ExportJob]:
        """Get the currently running job."""
        with self._lock:
            if self._running_job_id:
                return self.jobs.get(self._running_job_id)
            return None

    def start_processing(self, max_workers: int = 1):
        """Start the queue processor."""
        if self._executor is not None:
            return
        self._executor = ThreadPoolExecutor(max_workers=max_workers)
        self._executor.submit(self._process_queue)

    def stop_processing(self, wait: bool = True):
        """Stop the queue processor."""
        if self._executor:
            # Cancel running job
            if self._running_job_id:
                self.cancel_job(self._running_job_id)
            self._executor.shutdown(wait=wait, cancel_futures=True)
            self._executor = None

    def _process_queue(self):
        """Background queue processor."""
        while self._executor and not self._executor._shutdown:
            # Get next pending job
            with self._lock:
                pending = self.get_pending_jobs()
                if not pending:
                    # No jobs to run, wait a bit
                    pass
                else:
                    job = pending[0]
                    self._running_job_id = job.id
                    job.status = JobStatus.RUNNING
                    job.started_at = datetime.now().isoformat()
                    job.message = "Starting..."
                    self._save()

                    # Create cancel flag for this job
                    cancel_flag = threading.Event()
                    self._cancel_flags[job.id] = cancel_flag

                    # Submit to executor
                    future = self._executor.submit(self._run_job, job, cancel_flag)
                    self._futures[job.id] = future

            # Wait a bit before checking again
            time.sleep(0.5)

    def _run_job(self, job: ExportJob, cancel_flag: threading.Event):
        """Run a single export job."""
        try:
            # Import here to avoid circular imports
            from pageout.core.pipeline import export

            class Cancelled(Exception):
                pass

            def progress_callback(i, n):
                if cancel_flag.is_set():
                    raise Cancelled()
                if n > 0:
                    job.progress = i / n
                    job.current_page = i
                    job.total_pages = n
                    self._update_job(job)
                    if self.on_progress:
                        self.on_progress(job.id, job.progress, job.message)

            def log_callback(msg):
                job.message = msg
                if self.on_log:
                    self.on_log(job.id, msg)

            # Extract selected page IDs if present
            selected_roots = job.config.pop("_selected_page_ids", None)

            # Run export
            result = export(
                job.config,
                progress=progress_callback,
                cancel=cancel_flag,
                log=log_callback,
                selected_roots=selected_roots,
            )

            # Check for cancellation
            if cancel_flag.is_set():
                job.status = JobStatus.CANCELLED
                job.message = "Cancelled"
            elif result.failed:
                job.status = JobStatus.FAILED
                job.error = "; ".join(f"{f}: {r}" for f, r in result.failed[:5])
                job.message = f"Failed: {job.error}"
            else:
                job.status = JobStatus.COMPLETED
                job.progress = 1.0
                job.message = f"Exported {result.total - result.skipped} page(s)"
                job.result = {
                    "out_dir": result.out_dir,
                    "total": result.total,
                    "skipped": result.skipped,
                    "failed": len(result.failed),
                    "timing": result.timing.summary() if result.timing else None,
                }

            job.completed_at = datetime.now().isoformat()

        except Cancelled:
            job.status = JobStatus.CANCELLED
            job.message = "Cancelled"
            job.completed_at = datetime.now().isoformat()
        except Exception as e:
            job.status = JobStatus.FAILED
            job.error = str(e)
            job.message = f"Error: {e}"
            job.completed_at = datetime.now().isoformat()

        finally:
            # Cleanup
            with self._lock:
                self._running_job_id = None
                self._cancel_flags.pop(job.id, None)
                self._futures.pop(job.id, None)
                self._update_job(job)
                if self.on_complete:
                    self.on_complete(job)
                self._save()

    def _update_job(self, job: ExportJob):
        """Update job in dictionary and trigger save."""
        with self._lock:
            self.jobs[job.id] = job
            # Save periodically (not on every progress update to avoid I/O spam)
            # Only save on status changes or completion
            if job.progress == 1.0 or job.status in (JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED):
                self._save()

    def clear_history(self):
        """Clear completed/failed/cancelled jobs from history."""
        with self._lock:
            self.jobs = {
                k: v
                for k, v in self.jobs.items()
                if v.status in (JobStatus.PENDING, JobStatus.RUNNING, JobStatus.PAUSED)
            }
            self._save()

    def get_stats(self) -> Dict[str, int]:
        """Get queue statistics."""
        with self._lock:
            stats = {status.value: 0 for status in JobStatus}
            for job in self.jobs.values():
                stats[job.status.value] += 1
            return stats
