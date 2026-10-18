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
        self.assertFalse(any(m['confirmed'] or m['victim_id'] for m in data['marks']))
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

    def test_identity_binding_is_one_to_one_and_preserves_database_timestamps(self):
        data=wegame.parse_record(fixture(),PATH,'player')
        observations=[dict(id='target',time=31,confirmed=True,review_required=False,
            victim_id='enemy',event_type='kill',source='feed')]
        marks=wegame.verified_marks(data,observations)
        self.assertEqual(sum(m['confirmed'] for m in marks),1)
        self.assertEqual([m['time'] for m in marks],[30,30,35])
        self.assertFalse(any(m['confirmed'] for m in data['marks']))

    def test_same_target_down_and_finish_do_not_create_two_people(self):
        data=wegame.parse_record(fixture(),PATH,'player')
        obs=[dict(id=str(t),time=t,confirmed=True,review_required=False,victim_id='same',event_type='kill')
             for t in (30,31)]
        self.assertEqual(sum(m['confirmed'] for m in wegame.verified_marks(data,obs)),1)

    def test_verification_windows_merge_and_exclude_loot(self):
        data=wegame.parse_record(fixture(),PATH,'player')
        self.assertEqual(wegame.verification_windows(data,300),[[28,35]])
        data['marks']=[m for m in data['marks'] if m['event_type']=='loot']
        self.assertEqual(wegame.verification_windows(data,300),[])

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
