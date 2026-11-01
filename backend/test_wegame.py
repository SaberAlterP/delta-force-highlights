import copy
import json
from unittest import TestCase
from app.services import wegame


PATH=r'E:\record\account\record\record20261018-201500.mp4'


def fixture():
    kill=dict(id='1000802',kills=2,realStartTime=123,
        anchors=[dict(prefix=5,id=1,time=30000),dict(prefix=5,id=2,time=30000)])
    loot=dict(id='1000811',loots=1,realStartTime=456,
        anchors=[dict(prefix=30,id=1,time=35000)],
        ext=json.dumps(dict(itemInfo=json.dumps([dict(item_name='金枝桂冠')]))))
    return dict(gameInfo=dict(user_name='player',matches_id='match',stats=dict(kills=3)),
        videos=[dict(highLightType=1,id='video',duration=300000,videoSrc=PATH,
            clips=[dict(id=1,events=[kill,loot])])])


class WeGameTests(TestCase):
    def test_names_loot_items_and_settlement_are_distinct_from_operator_count(self):
        data=wegame.parse_record(fixture(),PATH,'player')
        self.assertEqual((data['official_kills'],data['kill_points'],data['loot_points']),(3,2,1))
        self.assertEqual(data['marks'][2]['label'],'摸金1 · 金枝桂冠')
        self.assertEqual(data['marks'][2]['event_type'],'loot')
        self.assertFalse(data['marks'][2]['review_required'])
        self.assertFalse(data['marks'][2]['confirmed'])
        # 官方击杀点直接算数，不再等待画面识别核对。
        self.assertTrue(all(m['confirmed'] and not m['review_required'] for m in data['marks'][:2]))
        self.assertTrue(data['warnings'])

    def test_duplicate_clip_is_deduplicated_but_two_simultaneous_anchors_survive(self):
        row=fixture();row['videos'][0]['clips']*=2
        data=wegame.parse_record(row,PATH,'player')
        self.assertEqual(len(data['marks']),3)
        self.assertEqual(len({m['id'] for m in data['marks']}),3)

    def test_exact_full_path_required_and_player_mismatch_rejected(self):
        self.assertIsNone(wegame.parse_record(fixture(),PATH.replace('account','other'),'player'))
        self.assertIsNotNone(wegame.parse_record(fixture(),PATH.upper().replace('\\','/'),'player'))
        with self.assertRaises(ValueError):wegame.parse_record(fixture(),PATH,'someone_else')

    def test_official_kills_alone_drive_highlights(self):
        from app.services.highlights import select_highlights
        data=wegame.parse_record(fixture(),PATH,'player')
        # 同一时刻两个锚点是两次击杀；摸金不算；不需要画面识别出被击杀者名字。
        clips=select_highlights(data['marks'],300,window=90,minimum=2,pre=20,post=5)
        self.assertEqual(len(clips),1)
        self.assertEqual(len(clips[0]['events']),2)
        self.assertEqual((clips[0]['start'],clips[0]['end']),(10,35))

    def test_by_name_matches_uploaded_copy_of_the_recording(self):
        self.assertIsNone(wegame.parse_record(fixture(),r'D:\uploads\record20261018-201500.mp4','player'))
        found=wegame.parse_record(fixture(),'record20261018-201500.mp4','player',by_name=True)
        self.assertEqual(found['kill_points'],2)
        self.assertIsNone(wegame.parse_record(fixture(),'other.mp4','player',by_name=True))

    def test_unknown_event_is_named_but_not_treated_as_kill(self):
        row=fixture();row['videos'][0]['clips'][0]['events'][0]['id']='999'
        data=wegame.parse_record(row,PATH,'player')
        self.assertEqual(data['kill_points'],0)
        self.assertTrue(data['marks'][0]['label'].startswith('未知事件'))

    def test_malformed_time_does_not_generate_clip(self):
        row=fixture();row['videos'][0]['clips'][0]['events'][0]['anchors'][0]['time']=float('nan')
        data=wegame.parse_record(row,PATH,'player')
        self.assertEqual(data['kill_points'],1)
        self.assertTrue(data['warnings'])
