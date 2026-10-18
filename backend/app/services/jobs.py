"""内存任务管理器：管理识别 / 导出等后台任务的状态与进度。

不依赖数据库；进程重启后任务状态丢失（符合「纯本地、无数据库」需求）。
"""
from __future__ import annotations

import threading
import time
import uuid
from concurrent.futures import CancelledError, ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Callable, Optional


@dataclass
class Job:
    job_id: str
    kind: str                         # "analyze" | "export"
    state: str = "pending"            # pending / running / done / error
    progress: float = 0.0
    message: str = ""
    result: Any = None
    error: Optional[str] = None
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    _cancel_event: threading.Event = field(default_factory=threading.Event, repr=False)

    def update(self, *, progress: float | None = None, message: str | None = None,
               state: str | None = None):
        with self._lock:
            if progress is not None:
                self.progress = max(0.0, min(1.0, progress))
            if message is not None:
                self.message = message
            if state is not None:
                self.state = state

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "job_id": self.job_id,
                "kind": self.kind,
                "state": self.state,
                "progress": self.progress,
                "message": self.message,
                "result": self.result,
                "error": self.error,
            }

    def cancel(self):
        self._cancel_event.set()
        with self._lock:
            if self.state in {"pending", "running"}:
                self.state = "cancelling"
                self.message = "正在释放任务占用的文件…"

    def is_cancelled(self) -> bool:
        return self._cancel_event.is_set()


class JobManager:
    def __init__(self, max_workers: int = 2):
        self._jobs: dict[str, Job] = {}
        self._executor = ThreadPoolExecutor(max_workers=max_workers)
        self._lock = threading.Lock()

    def submit(self, kind: str, fn: Callable[[Job], Any]) -> Job:
        job = Job(job_id=uuid.uuid4().hex, kind=kind)
        with self._lock:
            self._jobs[job.job_id] = job

        def _run():
            if job.is_cancelled():
                job.update(state="cancelled", message="任务已取消")
                return
            job.update(state="running")
            try:
                result = fn(job)
                with job._lock:
                    if job.is_cancelled():
                        job.state = "cancelled"
                        job.message = "任务已取消，文件占用已释放"
                    else:
                        job.result = result
                        job.progress = 1.0
                        job.state = "done"
            except CancelledError:
                job.update(state="cancelled", message="任务已取消，文件占用已释放")
            except Exception as exc:  # noqa: BLE001
                import traceback
                traceback.print_exc()
                with job._lock:
                    job.error = str(exc)
                    job.state = "error"

        self._executor.submit(_run)
        return job

    def get(self, job_id: str) -> Optional[Job]:
        with self._lock:
            return self._jobs.get(job_id)

    def has_active(self) -> bool:
        with self._lock:
            return any(j.snapshot()['state'] in {'pending','running','cancelling'}
                       for j in self._jobs.values())

    def cancel_all(self, wait_seconds: float = 5.0) -> dict:
        """请求取消所有活动任务，并等待其关闭 OpenCV/ffmpeg 文件句柄。"""
        with self._lock:
            active = [
                job for job in self._jobs.values()
                if job.state in {"pending", "running", "cancelling"}
            ]
        requested_count = len(active)
        for job in active:
            job.cancel()

        deadline = time.monotonic() + max(0.0, wait_seconds)
        while active and time.monotonic() < deadline:
            active = [
                job for job in active
                if job.snapshot()["state"] in {"pending", "running", "cancelling"}
            ]
            if active:
                time.sleep(0.05)
        return {"requested": requested_count, "remaining": len(active)}


jobs = JobManager()
