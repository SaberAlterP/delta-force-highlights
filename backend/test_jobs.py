"""Cancellation tests for cache force-cleanup job coordination."""
from concurrent.futures import CancelledError
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
from unittest import TestCase

from app.services.jobs import JobManager
from app.services.workers import failure_reason


class JobCancellationTests(TestCase):
    def test_cancel_all_waits_until_running_job_releases_resources(self):
        manager = JobManager(max_workers=1)
        started = Event()

        def task(job):
            started.set()
            while not job.is_cancelled():
                job._cancel_event.wait(0.01)
            raise CancelledError()

        job = manager.submit("analyze", task)
        self.assertTrue(started.wait(1.0))

        result = manager.cancel_all(wait_seconds=1.0)

        self.assertEqual(result, {"requested": 1, "remaining": 0})
        self.assertEqual(job.snapshot()["state"], "cancelled")
        manager._executor.shutdown(wait=True)


if __name__ == "__main__":
    import unittest
    unittest.main()


class WorkerFailureReasonTests(TestCase):
    def test_missing_ocr_dependency_gets_install_hint(self):
        with TemporaryDirectory() as tmp:
            log = Path(tmp) / 'worker.log'
            log.write_text('Traceback (most recent call last):\n  ...\nModuleNotFoundError: No module named \'easyocr\'\n\n', encoding='utf-8')
            self.assertIn('easyocr', failure_reason(log))
            self.assertIn('README', failure_reason(log))
            log.write_text('Traceback\nRuntimeError: 视频无法打开\n', encoding='utf-8')
            self.assertEqual(failure_reason(log), 'RuntimeError: 视频无法打开')
            self.assertEqual(failure_reason(Path(tmp) / 'missing.log'), '')
