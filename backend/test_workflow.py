import json
import time
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from app.services.workflow import WorkflowService, _digest, _fingerprint


class WorkflowTests(TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory()
        self.root=Path(self.temp.name)
        self.watch=self.root/'record'
        self.sources=self.watch/'account'/'record'
        self.sources.mkdir(parents=True)
        self.out=self.root/'outputs';self.out.mkdir()
        self.service=WorkflowService(self.root/'state')
        self.analysis_patch=patch.object(self.service,'_analyze_source',return_value=[])
        self.analyze=self.analysis_patch.start()
        self.service.configure(dict(watch_root=str(self.watch), output_root=str(self.out),
                                    enabled=True, player_id='tester', delete_after_retention=True,
                                    organize_originals=False,auto_clean_cache=False,notify_on_complete=False,
                                    stretch_169=False,prefer_official_events=False))
        self.old=self.sources/'record20260101-120000.mp4';self.old.write_bytes(b'old')
        edit=self.watch/'account'/'edit';edit.mkdir();(edit/'clip.mp4').write_bytes(b'edit')
        self.service.discover(now=100)

    def tearDown(self):
        self.analysis_patch.stop();self.service.stop();self.temp.cleanup()

    def new_file(self):
        path=self.sources/'record20261018-120000.mp4';path.write_bytes(b'new-video')
        self.service.discover(now=200)
        row=next(r for r in self.service.status()['records'] if r['path']==str(path))
        return path,row

    def ready(self, path, row, due=800):
        out=self.out/'clip.mp4';out.write_bytes(b'valid-clip')
        result=dict(files=[dict(path=str(out), size=out.stat().st_size,digest=_digest(out),expected=10)])
        self.service._update(row['id'],status='ready',digest=_digest(path),cleanup_after=due,
                             result=json.dumps(result))
        return out

    def test_existing_recordings_and_edit_files_never_auto_processed(self):
        records=self.service.status()['records']
        self.assertEqual(len(records),1)
        self.assertEqual(records[0]['status'],'historical')
        with patch.object(self.service,'_analyze_source') as analyze:
            self.service.process_next(now=500)
            analyze.assert_not_called()

    def test_file_growth_restarts_stability_wait_and_keeps_one_job(self):
        path,row=self.new_file();path.write_bytes(b'new-video-more')
        self.service.discover(now=290)
        records=[r for r in self.service.status()['records'] if r['path']==str(path)]
        self.assertEqual(len(records),1)
        self.assertEqual(records[0]['stable_since'],290)
        with patch.object(self.service,'_analyze_source') as analyze:
            self.service.process_next(now=400)
            analyze.assert_not_called()

    def test_recorder_open_handle_blocks_analysis(self):
        self.new_file()
        with (patch('app.services.workflow._closed_by_recorder',return_value=False),
              patch.object(self.service,'_analyze_source') as analyze):
            self.service.process_next(now=500)
            analyze.assert_not_called()

    def test_new_file_analyzed_in_place_and_no_highlights_retains_source(self):
        path,row=self.new_file()
        with (patch('app.services.workflow._closed_by_recorder',return_value=True),
              patch('app.services.workflow.video.probe',return_value=dict(duration=100,width=100,height=100)),
              patch.object(self.service,'_analyze_source',return_value=[]) as analyze):
            self.service.process_next(now=500)
        self.assertEqual(analyze.call_args.args[0],path)
        self.assertTrue(path.exists())
        self.assertEqual(next(r for r in self.service.status()['records'] if r['id']==row['id'])['status'],'no_highlights')
        self.assertEqual(list(self.out.iterdir()),[])

    def test_failed_analysis_keeps_original(self):
        path,row=self.new_file()
        with (patch('app.services.workflow._closed_by_recorder',return_value=True),
              patch('app.services.workflow.video.probe',side_effect=RuntimeError('broken'))):
            self.service.process_next(now=500)
        self.assertTrue(path.exists())
        self.assertEqual(next(r for r in self.service.status()['records'] if r['id']==row['id'])['status'],'error')

    def test_export_validation_starts_seven_days_from_success(self):
        path,row=self.new_file()
        marks=[dict(id=str(t),time=t,victim_id=name,confirmed=True,review_required=False,event_type='down')
               for t,name in [(30,'one'),(40,'two')]]
        self.analyze.return_value=marks
        def cut(src,start,end,out,**kw):out.write_bytes(b'valid-export')
        with (patch('app.services.workflow._closed_by_recorder',return_value=True),
              patch('app.services.workflow.video.probe',return_value=dict(duration=100,width=100,height=100)),
              patch('app.services.workflow.exporter.cut_clip',side_effect=cut),
              patch.object(self.service,'verify_clip') as verify):
            self.service.process_next(now=500)
        updated=next(r for r in self.service.status()['records'] if r['id']==row['id'])
        self.assertEqual(updated['status'],'ready')
        self.assertEqual(updated['cleanup_after']-updated['completed'],7*86400)
        verify.assert_called_once()
        self.assertTrue(path.exists())

    def test_missing_source_does_not_block_the_next_recording(self):
        path,row=self.new_file()
        self.service._update(row['id'],path=str(self.sources/'record20261017-110000.mp4'))
        self.service.process_next(now=500)
        updated=next(r for r in self.service.status()['records'] if r['id']==row['id'])
        self.assertEqual(updated['status'],'missing')

    def test_retention_never_uses_old_source_mtime(self):
        path,row=self.new_file();self.ready(path,row,due=10000)
        self.service.cleanup_due(now=9999)
        self.assertTrue(path.exists())

    def test_verified_expired_job_deletes_only_its_own_source(self):
        path,row=self.new_file();out=self.ready(path,row)
        with (patch.object(self.service,'verify_clip') as verify,
              patch('app.services.workflow._closed_by_recorder',return_value=True)):
            self.service.cleanup_due(now=801)
            verify.assert_called_once()
        self.assertFalse(path.exists())
        self.assertTrue(self.old.exists());self.assertTrue(out.exists())

    def test_changed_or_missing_export_prevents_source_deletion(self):
        path,row=self.new_file();out=self.ready(path,row);out.write_bytes(b'broken')
        self.service.cleanup_due(now=801)
        self.assertTrue(path.exists())
        self.assertEqual(next(r for r in self.service.status()['records'] if r['id']==row['id'])['status'],'review')

    def test_replaced_source_prevents_deletion(self):
        path,row=self.new_file();self.ready(path,row);path.write_bytes(b'replaced')
        self.service.cleanup_due(now=801)
        self.assertTrue(path.exists())

    def test_history_can_be_explicitly_queued_but_is_not_cleanup_eligible(self):
        row=self.service.status()['records'][0]
        self.service.retry(row['id'])
        updated=self.service.status()['records'][0]
        self.assertEqual(updated['status'],'waiting')
        self.assertEqual(updated['allow_cleanup'],0)

    def test_restart_does_not_reprocess_success_or_history(self):
        path,row=self.new_file();self.ready(path,row)
        service=WorkflowService(self.root/'state');service.discover(now=500)
        self.assertEqual({r['status'] for r in service.status()['records']},{'ready','historical'})

    def export_once(self, row, times=(30,40), retry=False, duration=100):
        if retry:
            self.service.retry(row['id'])
        self.analyze.return_value=[dict(id=str(t),time=t,victim_id=f'enemy{i}',
            confirmed=True,review_required=False,event_type='down') for i,t in enumerate(times)]
        def cut(src,start,end,out,**kw):
            out.write_bytes(f'valid-export:{start}:{end}'.encode())
        with (patch('app.services.workflow._closed_by_recorder',return_value=True),
              patch('app.services.workflow.video.probe',return_value=dict(duration=duration,width=100,height=100)),
              patch('app.services.workflow.exporter.cut_clip',side_effect=cut) as cut_mock,
              patch.object(self.service,'verify_clip')):
            self.service.process_next(now=time.time()+121)
        updated=next(r for r in self.service.status()['records'] if r['id']==row['id'])
        self.assertEqual(updated['status'],'ready',updated['error'])
        return updated['result'],cut_mock.call_count

    def test_retry_reuses_same_video_even_when_kill_count_changes(self):
        path,row=self.new_file()
        first,calls=self.export_once(row)
        self.assertEqual(calls,1)
        second,calls=self.export_once(row,times=(30,35,40),retry=True)
        self.assertEqual(calls,0)
        self.assertEqual(first['files'],second['files'])
        self.assertEqual(len(second['highlights'][0]['events']),3)
        self.assertEqual(len(list(self.out.rglob('*.mp4'))),1)
        self.assertEqual(len(list(self.out.rglob('识别记录.json'))),1)
        self.assertTrue(path.exists())

    def test_changed_range_exports_new_clip_and_reverting_reuses_old_clip(self):
        path,row=self.new_file()
        first,_=self.export_once(row)
        second,calls=self.export_once(row,times=(30,50),retry=True)
        self.assertEqual(calls,1)
        self.assertNotEqual(first['files'][0]['path'],second['files'][0]['path'])
        third,calls=self.export_once(row,retry=True)
        self.assertEqual(calls,0)
        self.assertEqual(first['files'],third['files'])
        self.assertEqual(len(list(self.out.rglob('*.mp4'))),2)

    def test_tampered_export_is_preserved_but_never_reused(self):
        path,row=self.new_file()
        first,_=self.export_once(row)
        old=Path(first['files'][0]['path']);original=old.read_bytes()
        old.write_bytes(b'x'+original[1:])
        second,calls=self.export_once(row,retry=True)
        self.assertEqual(calls,1)
        self.assertNotEqual(first['files'][0]['path'],second['files'][0]['path'])
        self.assertEqual(old.read_bytes(),b'x'+original[1:])

    def test_changed_source_never_reuses_old_export(self):
        path,row=self.new_file()
        first,_=self.export_once(row)
        path.write_bytes(b'changed-source')
        second,calls=self.export_once(row,retry=True)
        self.assertEqual(calls,1)
        self.assertNotEqual(first['files'][0]['path'],second['files'][0]['path'])

    def test_output_root_change_exports_in_the_new_root(self):
        path,row=self.new_file()
        first,_=self.export_once(row)
        new_root=self.root/'new-outputs'
        self.service.configure(dict(output_root=str(new_root)))
        second,calls=self.export_once(row,retry=True)
        self.assertEqual(calls,1)
        self.assertTrue(Path(second['files'][0]['path']).is_relative_to(new_root))
        self.assertTrue(Path(first['files'][0]['path']).exists())

    def test_no_highlights_result_retains_previously_verified_export_index(self):
        path,row=self.new_file()
        first,_=self.export_once(row)
        self.service.retry(row['id']);self.analyze.return_value=[]
        with (patch('app.services.workflow._closed_by_recorder',return_value=True),
              patch('app.services.workflow.video.probe',return_value=dict(duration=100,width=100,height=100))):
            self.service.process_next(now=time.time()+121)
        second,calls=self.export_once(row,retry=True)
        self.assertEqual(calls,0)
        self.assertEqual(first['files'],second['files'])

    def test_retry_after_later_export_fails_reuses_the_first_verified_clip(self):
        path,row=self.new_file()
        self.analyze.return_value=[dict(id=str(t),time=t,victim_id=f'enemy{i}',
            confirmed=True,review_required=False,event_type='down')
            for i,t in enumerate((30,40,200,210))]
        def cut(src,start,end,out,**kw):
            if start>100:
                raise RuntimeError('second export failed')
            out.write_bytes(b'first-valid-export')
        with (patch('app.services.workflow._closed_by_recorder',return_value=True),
              patch('app.services.workflow.video.probe',return_value=dict(duration=300,width=100,height=100)),
              patch('app.services.workflow.exporter.cut_clip',side_effect=cut),
              patch.object(self.service,'verify_clip')):
            self.service.process_next(now=time.time()+121)
        updated=next(r for r in self.service.status()['records'] if r['id']==row['id'])
        self.assertEqual(updated['status'],'error')
        first_path=updated['result']['files'][0]['path']
        result,calls=self.export_once(row,times=(30,40,200,210),retry=True,duration=300)
        self.assertEqual(calls,1)
        self.assertEqual(result['files'][0]['path'],first_path)
        self.assertEqual(len(list(self.out.rglob('*.mp4'))),2)
