"""Cancellation tests for cache force-cleanup job coordination."""
from concurrent.futures import CancelledError
from threading import Event
from unittest import TestCase

from app.services.jobs import JobManager


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
