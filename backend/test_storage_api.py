"""Focused tests for cache browsing and precise deletion."""
import asyncio
from starlette.requests import Request
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from fastapi import HTTPException

from app.api import routes
from app.models import CleanupRequest, StorageDeleteRequest, StorageRestoreRequest


class StorageApiTests(TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        root = Path(self.temp.name)
        self.uploads = root / "uploads"
        self.clips = root / "clips"
        self.chunks = root / "chunks"
        self.tmp = root / "tmp"
        for directory in (self.uploads, self.clips, self.chunks, self.tmp):
            directory.mkdir()
        self.dirs = {
            "uploads": self.uploads,
            "clips": self.clips,
            "chunks": self.chunks,
            "tmp": self.tmp,
        }
        self.patch = patch.dict(routes._STORAGE_DIRS, self.dirs, clear=True)
        self.patch.start()
        routes.UPLOADS.clear()

    def tearDown(self):
        routes.UPLOADS.clear()
        self.patch.stop()
        self.temp.cleanup()

    def test_lists_uploads_with_original_name(self):
        path = self.uploads / "abc123.mp4"
        path.write_bytes(b"video")
        routes.UPLOADS["abc123"] = {"filename": "match-final.mp4"}

        result = routes.storage_files("uploads")

        self.assertEqual(len(result["files"]), 1)
        item = result["files"][0]
        self.assertEqual(item["name"], "match-final.mp4")
        self.assertEqual(item["path"], "abc123.mp4")
        self.assertEqual(item["upload_id"], "abc123")
        self.assertTrue(item["previewable"])

    def test_video_stream_uses_native_range_response_and_closes_file(self):
        path = self.uploads / "range-test.mp4"
        path.write_bytes(b"0123456789")
        routes.UPLOADS["range-test"] = {"path": path, "filename": "range-test.mp4"}
        scope = {
            "type": "http", "method": "GET", "path": "/api/video/range-test",
            "headers": [(b"range", b"bytes=2-5")],
        }
        response = routes.stream_video("range-test", Request(scope))
        messages = []

        async def send(message):
            messages.append(message)

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        asyncio.run(response(scope, receive, send))

        start = messages[0]
        body = b"".join(message.get("body", b"") for message in messages[1:])
        headers = dict(start["headers"])
        self.assertEqual(start["status"], 206)
        self.assertEqual(body, b"2345")
        self.assertEqual(headers[b"content-range"], b"bytes 2-5/10")
        # TestClient 已关闭响应；Windows 下能独占打开说明服务端没有遗留句柄。
        with path.open("r+b") as handle:
            handle.seek(0, 2)

    def test_deletes_only_selected_export_and_prunes_empty_job_dir(self):
        job = self.clips / "job-1"
        job.mkdir()
        keep = job / "keep.mp4"
        remove = job / "remove.mp4"
        keep.write_bytes(b"keep")
        remove.write_bytes(b"remove")

        result = routes.delete_storage_file(
            StorageDeleteRequest(target="clips", path="job-1/remove.mp4")
        )

        self.assertFalse(remove.exists())
        self.assertTrue(keep.exists())
        self.assertEqual(result["removed"]["files"], 1)
        self.assertEqual(result["removed"]["bytes"], 6)

    def test_rejects_directory_traversal(self):
        outside = Path(self.temp.name) / "outside.mp4"
        outside.write_bytes(b"secret")

        with self.assertRaises(HTTPException) as ctx:
            routes._resolve_storage_file("uploads", "../outside.mp4")

        self.assertEqual(ctx.exception.status_code, 400)
        self.assertTrue(outside.exists())

    def test_restores_cached_upload_without_copying_file(self):
        path = self.uploads / "abc123.mp4"
        path.write_bytes(b"cached-video")
        probed = {
            "duration": 125.5,
            "width": 1440,
            "height": 1080,
            "fps": 60.0,
            "size_bytes": len(b"cached-video"),
        }

        with patch.object(routes.video, "probe", return_value=probed):
            result = routes.restore_cached_upload(
                StorageRestoreRequest(path="abc123.mp4", filename="比赛录像.mp4")
            )

        self.assertEqual(result.upload_id, "abc123")
        self.assertEqual(result.filename, "比赛录像.mp4")
        self.assertEqual(result.duration, 125.5)
        self.assertEqual(routes.UPLOADS["abc123"]["path"], path)
        self.assertEqual(path.read_bytes(), b"cached-video")

    def test_force_cleanup_cancels_jobs_and_reports_actual_removed_files(self):
        upload = self.uploads / "locked-before-release.mp4"
        upload.write_bytes(b"video-data")
        export_dir = self.clips / "job-1"
        export_dir.mkdir()
        (export_dir / "clip.mp4").write_bytes(b"clip")

        with patch.object(
            routes.jobs, "cancel_all", return_value={"requested": 2, "remaining": 0}
        ) as cancel:
            result = routes.storage_cleanup(CleanupRequest(
                targets=["uploads", "clips", "chunks", "tmp"], force=True
            ))

        cancel.assert_called_once_with(wait_seconds=6.0)
        self.assertEqual(result["removed"]["files"], 2)
        self.assertEqual(result["removed"]["bytes"], len(b"video-data") + len(b"clip"))
        self.assertEqual(result["removed"]["failed"], 0)
        self.assertEqual(result["cancelled_jobs"]["requested"], 2)
        self.assertFalse(upload.exists())
        self.assertFalse(export_dir.exists())

    def test_cleanup_rejects_unknown_target(self):
        with self.assertRaises(HTTPException) as ctx:
            routes.storage_cleanup(CleanupRequest(targets=["uploads", "outside"]))
        self.assertEqual(ctx.exception.status_code, 400)


if __name__ == "__main__":
    import unittest
    unittest.main()
