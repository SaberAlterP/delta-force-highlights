from concurrent.futures import CancelledError
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import time
from unittest import TestCase
from unittest.mock import patch

from app.services import archive
from app.services.workflow import WorkflowService


class ArchiveWorkflowTests(TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory();self.root=Path(self.temp.name)
        self.watch=self.root/'record';self.watch.mkdir()
        self.out=self.root/'集锦'
        self.service=WorkflowService(self.root/'state')
        self.service.configure(dict(enabled=True,player_id='tester',watch_root=str(self.watch),output_root=str(self.out),
            organize_originals=True,window_seconds=90,delete_after_retention=True,
            auto_clean_cache=False,notify_on_complete=False,stretch_169=False,prefer_official_events=False))
        self.service.discover(now=100)
        self.source=self.watch/'record20261018-201500.mp4';self.source.write_bytes(b'original-movie')
        self.service.discover(now=200)
        self.row=self.service.status()['records'][0]

    def tearDown(self):self.service.stop();self.temp.cleanup()

    def current(self):return self.service.status()['records'][0]

    def run_job(self,times=(30,110),retry=False,review=False):
        if retry:self.service.retry(self.row['id'])
        marks=[dict(id=str(t),time=t,victim_id=f'enemy{i}',event_type='down',confirmed=True,
                    review_required=False) for i,t in enumerate(times)]
        if review:marks.append(dict(id='unknown',time=150,victim_id='',confirmed=False,review_required=True))
        def cut(src,start,end,out,**kwargs):
            self.assertTrue(src.exists());out.write_bytes(f'clip:{start}-{end}'.encode())
        with (patch.object(self.service,'_analyze_source',return_value=marks),
              patch('app.services.workflow.video.probe',return_value=dict(duration=300,
                    width=160 if self.service.settings.stretch_169 else 100,
                    height=90 if self.service.settings.stretch_169 else 100)),
              patch('app.services.workflow._closed_by_recorder',return_value=True),
              patch('app.services.workflow.exporter.cut_clip',side_effect=cut) as cut_mock,
              patch.object(self.service,'verify_clip')):
            self.service.process_next(now=time.time()+121)
        row=self.current()
        self.assertIn(row['status'],{'ready','review','no_highlights'},row['error'])
        return row,cut_mock.call_count

    def test_archive_contains_original_and_ninety_second_highlight_without_source_copy(self):
        row,calls=self.run_job()
        self.assertEqual(calls,1)
        directory=Path(row['archive_dir'])
        self.assertIn('2026-10-18_20-15-00_全局识别2杀_有集锦',directory.name)
        self.assertFalse(self.source.exists())
        self.assertEqual((directory/'整局原录像.mp4').read_bytes(),b'original-movie')
        self.assertEqual(len(list(directory.glob('*.mp4'))),2)
        self.assertEqual(row['cleanup_after']-row['retained_since'],7*86400)
        self.assertTrue((directory/'录像说明.txt').exists())

    def test_official_event_names_timestamps_and_total_flow_into_archive(self):
        from app.services import wegame
        self.service.configure(dict(prefer_official_events=True))
        native=dict(marks=[dict(id='wg1',time=30,event_name='击杀',event_type='kill',label='击杀1',
            confirmed=False,review_required=True,victim_id='',source='wegame'),
            dict(id='wg2',time=110,event_name='击杀',event_type='kill',label='击杀2',
            confirmed=False,review_required=True,victim_id='',source='wegame'),
            dict(id='wg3',time=60,event_name='摸金',event_type='loot',label='摸金1 · 桂冠',
            confirmed=False,review_required=False,victim_id='',source='wegame')],
            official_kills=7,kill_points=2,loot_points=1,duration=300,
            signature='test',version=wegame.VERSION,warnings=[])
        with patch('app.services.workflow.wegame.index.find',return_value=native):
            row,calls=self.run_job()
        self.assertEqual(calls,1)
        self.assertIn('全局7杀_有集锦',Path(row['archive_dir']).name)
        self.assertEqual(row['result']['summary']['confirmed_kills'],2)
        self.assertEqual(row['result']['summary']['loot_points'],1)
        self.assertEqual(row['result']['highlights'][0]['end'],115)
        self.assertIn('摸金1 · 桂冠',[m['label'] for m in row['result']['marks']])

    def test_no_highlights_archive_is_labelled_and_original_expires_after_seven_days(self):
        row,_=self.run_job(times=())
        self.assertEqual(row['status'],'no_highlights')
        self.assertIn('全局识别0杀_无集锦',Path(row['archive_dir']).name)
        original=Path(row['archive_path'])
        self.service.cleanup_due(now=row['cleanup_after']-1);self.assertTrue(original.exists())
        with patch('app.services.workflow._closed_by_recorder',return_value=True):
            self.service.cleanup_due(now=row['cleanup_after']+1)
        self.assertFalse(original.exists());self.assertEqual(self.current()['status'],'deleted')
        self.assertTrue((Path(row['archive_dir'])/'录像说明.txt').exists())

    def test_retention_removes_only_original_and_keeps_verified_highlight(self):
        row,_=self.run_job();clip=Path(row['result']['files'][0]['path'])
        with (patch('app.services.workflow._closed_by_recorder',return_value=True),
              patch.object(self.service,'verify_clip')):
            self.service.cleanup_due(now=row['cleanup_after']+1)
        self.assertFalse(Path(row['archive_path']).exists());self.assertTrue(clip.exists())
        self.assertTrue(self.current()['result']['original']['removed'])

    def test_changed_highlight_or_missing_owner_marker_prevents_cleanup(self):
        row,_=self.run_job();clip=Path(row['result']['files'][0]['path'])
        clip.write_bytes(b'x'+clip.read_bytes()[1:])
        self.service.cleanup_due(now=row['cleanup_after']+1)
        self.assertTrue(Path(row['archive_path']).exists())
        self.assertEqual(self.current()['status'],'review')

    def test_uncertain_candidates_are_excluded_but_successful_archive_still_expires(self):
        row,_=self.run_job(review=True)
        self.assertEqual(row['result']['summary']['confirmed_kills'],2)
        with (patch('app.services.workflow._closed_by_recorder',return_value=True),
              patch.object(self.service,'verify_clip')):
            self.service.cleanup_due(now=row['cleanup_after']+1)
        self.assertFalse(Path(row['archive_path']).exists())
        self.assertIsNotNone(row['result']['cleanup_after'])

    def test_user_can_exempt_one_original_from_seven_day_cleanup(self):
        row,_=self.run_job()
        self.service.retain_original(row['id'])
        self.service.cleanup_due(now=row['cleanup_after']+1)
        self.assertTrue(Path(row['archive_path']).exists())
        self.assertFalse(self.current()['allow_cleanup'])
        self.assertIsNone(self.current()['result']['cleanup_after'])

    def test_retaining_original_during_slow_export_verification_prevents_deletion(self):
        row,_=self.run_job()
        with (patch('app.services.workflow._closed_by_recorder',return_value=True),
              patch.object(self.service,'verify_clip',side_effect=lambda *_:self.service.retain_original(row['id']))):
            self.service.cleanup_due(now=row['cleanup_after']+1)
        self.assertTrue(Path(row['archive_path']).exists())

    def test_retry_updates_folder_count_reuses_clip_and_does_not_reset_retention(self):
        first,_=self.run_job()
        second,calls=self.run_job(times=(30,60,110),retry=True)
        self.assertEqual(calls,0)
        self.assertEqual(second['cleanup_after'],first['cleanup_after'])
        self.assertIn('全局识别3杀',Path(second['archive_dir']).name)
        self.assertFalse(Path(first['archive_dir']).exists())
        self.assertEqual(len(list(self.out.rglob('*.mp4'))),2)
        self.assertTrue(Path(second['archive_path']).exists())

    def test_retry_changed_range_reads_archived_original_after_folder_rename(self):
        self.run_job()
        second,calls=self.run_job(times=(30,),retry=True)
        self.assertEqual(calls,0)
        self.assertEqual(second['status'],'no_highlights')
        self.assertTrue(Path(second['archive_path']).exists())

    def test_restart_and_discovery_do_not_create_duplicate_tasks_for_moved_original(self):
        row,_=self.run_job()
        self.assertEqual(self.service.discover(now=time.time()),0)
        service=WorkflowService(self.root/'state')
        self.assertEqual(len(service.status()['records']),1)
        self.assertEqual(service.status()['records'][0]['status'],'ready')

    def test_failed_export_preserves_source_and_removes_partial_clip(self):
        marks=[dict(id=str(t),time=t,victim_id=str(t),event_type='down',confirmed=True,
                    review_required=False) for t in (30,40)]
        def fail(src,start,end,out,**kwargs):out.write_bytes(b'partial');raise RuntimeError('disk full')
        with (patch.object(self.service,'_analyze_source',return_value=marks),
              patch('app.services.workflow.video.probe',return_value=dict(duration=300,width=100,height=100)),
              patch('app.services.workflow._closed_by_recorder',return_value=True),
              patch('app.services.workflow.exporter.cut_clip',side_effect=fail)):
            self.service.process_next(now=time.time()+121)
        self.assertEqual(self.current()['status'],'error');self.assertTrue(self.source.exists())
        self.assertEqual(list(self.out.rglob('*.mp4')),[])

    def test_notification_failure_does_not_fail_archive_or_repeat_every_poll(self):
        self.service.configure(dict(notify_on_complete=True))
        with patch('app.services.workflow.notifications.send',return_value=dict(sent=False,error='disabled')) as send:
            row,_=self.run_job();self.service.notify_pending()
        self.assertEqual(send.call_count,1)
        self.assertEqual(row['status'],'ready');self.assertEqual(row['notification_error'],'disabled')

    def test_cleanup_rejects_replaced_archive_path_outside_its_bundle(self):
        row,_=self.run_job();outside=self.root/'important.mp4';outside.write_bytes(b'important')
        self.service._update(row['id'],archive_path=str(outside))
        self.service.cleanup_due(now=row['cleanup_after']+1)
        self.assertTrue(outside.exists());self.assertTrue(Path(row['archive_path']).exists())

    def test_automatic_cache_cleanup_runs_after_successful_archive(self):
        self.service.configure(dict(auto_clean_cache=True))
        with (patch('app.services.workflow.cache.deduplicate_uploads') as uploads,
              patch('app.services.workflow.cache.deduplicate_legacy_exports') as clips):
            row,_=self.run_job()
        self.assertEqual(row['status'],'ready')
        self.assertEqual(uploads.call_count,1);self.assertEqual(clips.call_count,1)

    def test_enabling_stretch_reexports_old_clip_and_keeps_no_extra_video_copy(self):
        first,_=self.run_job()
        self.service.configure(dict(stretch_169=True))
        second,calls=self.run_job(retry=True)
        self.assertEqual(calls,1)
        self.assertTrue(second['result']['files'][0]['stretch_169'])
        self.assertFalse(Path(first['result']['files'][0]['path']).exists())
        self.assertEqual(len(list(self.out.rglob('*.mp4'))),2)
        third,calls=self.run_job(retry=True)
        self.assertEqual(calls,0)

    def test_wrong_pixel_aspect_is_rejected_even_if_video_decodes(self):
        with (patch.object(self.service,'verify_clip'),
              patch('app.services.workflow.video.probe',return_value=dict(width=1440,height=1080))):
            with self.assertRaises(RuntimeError):self.service._verify_export(self.source,10,True)

    def test_project_source_resolves_to_archived_file_without_upload_copy(self):
        from app.services import projects
        row,_=self.run_job()
        source_id='bundle_'+row['id']
        before=set(self.root.rglob('*.mp4'))
        self.assertEqual(self.service.resolve_project_video(source_id),Path(row['archive_path']))
        self.assertEqual(set(self.root.rglob('*.mp4')),before)
        projects.save_marks(row,source_id,[dict(id='custom',time=12.5,label='手动调整',pre=10,post=6,selected=True)])
        again=WorkflowService(self.root/'state')
        saved=projects.load(again.recording(row['id']))
        self.assertEqual(saved['sources'][source_id]['kills'][0]['time'],12.5)
        self.assertEqual(saved['sources'][source_id]['kills'][0]['label'],'手动调整')

    def test_project_clip_source_uses_content_id_and_rejects_another_package(self):
        from app.services import projects
        row,_=self.run_job();item=row['result']['files'][0]
        source_id=f'bundle_{row["id"]}_clip_{item["sha256"][:12]}'
        self.assertEqual(self.service.resolve_project_video(source_id),Path(item['path']))
        with self.assertRaises(ValueError):projects.save_marks(row,'bundle_'+'f'*32,[])

    def test_archive_edit_api_returns_original_and_marks_without_uploading(self):
        from app.api import routes
        row,_=self.run_job()
        before=set(self.root.rglob('*.mp4'))
        with (patch.object(routes,'workflow',self.service),
              patch.object(routes.video,'probe',return_value=dict(duration=300,width=100,height=100,fps=30,size_bytes=14))):
            data=routes.workflow_edit(row['id'],{})
            self.assertEqual(data['video']['upload_id'],'bundle_'+row['id'])
            self.assertEqual(len(data['kills']),2)
        self.assertEqual(set(self.root.rglob('*.mp4')),before)

    def test_manual_delete_original_keeps_highlights_and_records(self):
        row,_=self.run_job()
        directory=Path(row['archive_dir'])
        self.service.delete_original(row['id'])
        row=self.current()
        self.assertEqual(row['status'],'deleted')
        self.assertFalse(row['original_available'])
        self.assertFalse((directory/'整局原录像.mp4').exists())
        self.assertEqual(len(list(directory.glob('*.mp4'))),1)
        self.assertIn('已手动删除',(directory/'录像说明.txt').read_text(encoding='utf-8'))
        with self.assertRaises(ValueError):self.service.delete_original(row['id'])

    def test_manual_delete_bundle_removes_only_that_folder(self):
        row,_=self.run_job()
        directory=Path(row['archive_dir'])
        sibling=self.out/'其他文件夹';sibling.mkdir();(sibling/'keep.txt').write_text('x')
        self.service.delete_bundle(row['id'])
        self.assertFalse(directory.exists())
        self.assertTrue((sibling/'keep.txt').exists())
        self.assertEqual(self.current()['status'],'removed')
        self.assertEqual(self.service.discover(now=time.time()),0)
        with self.assertRaises(ValueError):self.service.retry(row['id'])

    def test_manual_delete_refuses_mismatched_bundle_identity(self):
        row,_=self.run_job()
        directory=Path(row['archive_dir'])
        (directory/'归档标识.json').write_text(json.dumps(dict(recording_id='other')),encoding='utf-8')
        with self.assertRaises(ValueError):self.service.delete_bundle(row['id'])
        with self.assertRaises(ValueError):self.service.delete_original(row['id'])
        self.assertTrue((directory/'整局原录像.mp4').exists())


class CrossVolumeMoveTests(TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory();self.root=Path(self.temp.name)
        self.src=self.root/'source.mp4';self.src.write_bytes(b'video-data'*1000)
        self.dest=self.root/'bundle'/'整局原录像.mp4';self.dest.parent.mkdir()

    def tearDown(self):self.temp.cleanup()

    def test_cross_volume_copy_is_verified_before_source_removal(self):
        commits=[]
        def commit(*args):
            self.assertTrue(self.src.exists());self.assertTrue(self.dest.exists());commits.append(args)
        with patch('app.services.archive._same_volume',return_value=False):
            digest=archive.move_verified(self.src,self.dest,archive.fingerprint(self.src),
                closed=lambda _:True,commit=commit)
        self.assertFalse(self.src.exists());self.assertEqual(archive.sha256(self.dest),digest)
        self.assertEqual(len(commits),1)

    def test_copy_checksum_failure_preserves_source_and_cleans_partial(self):
        real_hash=archive.sha256
        with (patch('app.services.archive._same_volume',return_value=False),
              patch('app.services.archive.sha256',side_effect=lambda p:'bad' if p.suffix=='.partial' else real_hash(p))):
            with self.assertRaises(RuntimeError):
                archive.move_verified(self.src,self.dest,archive.fingerprint(self.src),
                    closed=lambda _:True,commit=lambda *_:self.fail('must not commit'))
        self.assertTrue(self.src.exists());self.assertFalse(self.dest.exists())
        self.assertEqual(list(self.dest.parent.glob('*.partial')),[])

    def test_existing_identical_target_recovers_interrupted_copy_without_duplicate(self):
        self.dest.write_bytes(self.src.read_bytes())
        archive.move_verified(self.src,self.dest,archive.fingerprint(self.src),
                              closed=lambda _:True,commit=lambda *_:None)
        self.assertFalse(self.src.exists());self.assertEqual(len(list(self.root.rglob('*.mp4'))),1)

    def test_existing_different_target_is_never_overwritten(self):
        self.dest.write_bytes(b'other-video')
        with self.assertRaises(RuntimeError):
            archive.move_verified(self.src,self.dest,archive.fingerprint(self.src),
                                  closed=lambda _:True,commit=lambda *_:None)
        self.assertTrue(self.src.exists());self.assertEqual(self.dest.read_bytes(),b'other-video')
