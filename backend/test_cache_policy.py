import os
from pathlib import Path
from tempfile import TemporaryDirectory
import time
from unittest import TestCase

from app.services.cache import CacheManager
from app.services.archive import sha256


class CachePolicyTests(TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory();self.root=Path(self.temp.name)
        self.cache=CacheManager(self.root)
        self.now=time.time()

    def tearDown(self):self.temp.cleanup()

    def file(self,name,days=0,content=b'cache'):
        path=self.root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(content)
        stamp=self.now-days*86400;os.utime(path,(stamp,stamp));return path

    def test_old_temporary_and_upload_cache_removed_but_recent_and_exports_kept(self):
        old=self.file('uploads/old.mp4',days=8)
        fresh=self.file('uploads/fresh.mp4',days=6)
        part=self.file('chunks/id/000001.part',days=2)
        exported=self.file('clips/user-export.mp4',days=30)
        result=self.cache.cleanup(now=self.now,closed=lambda _:True)
        self.assertFalse(old.exists());self.assertFalse(part.exists())
        self.assertTrue(fresh.exists());self.assertTrue(exported.exists())
        self.assertEqual(result['removed_files'],2)

    def test_active_jobs_and_locked_files_are_preserved(self):
        old=self.file('uploads/old.mp4',days=8)
        self.cache.cleanup(now=self.now,closed=lambda _:True,busy=True)
        self.assertTrue(old.exists())
        self.cache.cleanup(now=self.now,closed=lambda _:False)
        self.assertTrue(old.exists())

    def test_preview_touch_extends_cache_lifetime_without_changing_video_fingerprint(self):
        old=self.file('uploads/old.mp4',days=8)
        before=old.stat().st_mtime_ns
        self.cache.touch(old)
        self.assertEqual(old.stat().st_mtime_ns,before)
        self.cache.cleanup(now=self.now,closed=lambda _:True)
        self.assertTrue(old.exists())

    def test_only_exact_upload_duplicate_removed_and_playback_alias_persisted(self):
        original=self.file('archive/整局原录像.mp4',content=b'original')
        duplicate=self.file('uploads/abc.mp4',content=b'original')
        other=self.file('uploads/other.mp4',content=b'different')
        result=self.cache.deduplicate_uploads(original,sha256(original),closed=lambda _:True)
        self.assertEqual(result['removed_files'],1)
        self.assertFalse(duplicate.exists());self.assertTrue(other.exists());self.assertTrue(original.exists())
        restored=CacheManager(self.root)
        self.assertEqual(restored.alias('abc'),original.resolve())

    def test_duplicate_upload_is_preserved_during_active_job(self):
        original=self.file('archive/original.mp4',content=b'original')
        duplicate=self.file('uploads/abc.mp4',content=b'original')
        self.cache.deduplicate_uploads(original,sha256(original),closed=lambda _:True,busy=True)
        self.assertTrue(duplicate.exists())

    def test_worker_diagnostics_expire_but_active_and_unknown_files_are_kept(self):
        old=self.file('workflow/workers/'+'a'*32+'/worker.log',days=8)
        active=self.file('workflow/workers/'+'b'*32+'/worker.log',days=8)
        unknown=self.file('workflow/workers/'+'c'*32+'/important.txt',days=8)
        result=self.cache.cleanup(now=self.now,closed=lambda _:True,active_workers=[active.parent])
        self.assertFalse(old.exists());self.assertTrue(active.exists());self.assertTrue(unknown.exists())
        self.assertEqual(result['removed_files'],1)
