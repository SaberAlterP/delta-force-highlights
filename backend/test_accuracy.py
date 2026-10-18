from pathlib import Path
from unittest import TestCase
from unittest.mock import patch
import cv2
import numpy as np

from app.services import detector, killfeed, ocr
from app.services.events import EventTracker, name_score, parse_prompt
from app.services.highlights import select_highlights
from test_detector_efficiency import _FakeCapture


class AccuracyTests(TestCase):
    def test_distinct_targets_inside_old_four_second_blind_spot(self):
        tracker = EventTracker()
        self.assertTrue(tracker.add(1, victim='enemyA', confirmed=True))
        self.assertTrue(tracker.add(1.4, victim='enemyB', confirmed=True))
        self.assertEqual(len(tracker.marks), 2)

    def test_knock_finish_and_lingering_prompt_are_one_person(self):
        tracker = EventTracker()
        for t, text in [(1, '击倒前村委会副主任'), (5.5, '击败前村委会副主任 灭队!'),
                        (7, '击败前村委会副主任')]:
            p = parse_prompt(text)
            tracker.add(t, victim=p.victim, kind=p.kind, prompt_text=text)
        self.assertEqual(len(tracker.marks), 1)
        self.assertEqual(tracker.marks[0]['time'], 1)

    def test_squad_notification_never_adds_an_extra_person(self):
        tracker = EventTracker()
        tracker.add(1, victim='enemy')
        tracker.add(5, kind='squad', prompt_text='灭队!')
        self.assertEqual(len(tracker.marks), 1)

    def test_minor_prompt_ocr_truncation_is_not_a_new_person(self):
        tracker = EventTracker()
        tracker.add(10, victim='斯是陋室同学', source='prompt')
        tracker.add(10.3, victim='斯是陋宝', source='prompt')
        self.assertEqual(len(tracker.marks), 1)

    def test_no_cross_pass_character_concatenation_confirms_an_id(self):
        with patch.object(ocr, 'read_texts', side_effect=[[("AB", .8)], [("CD", .8)]]):
            hit, _, score = detector._id_present(np.zeros((30,100,3),np.uint8), 'ABCD', .9)
        self.assertFalse(hit)
        self.assertLess(score, .9)

    def test_short_player_ids_require_exact_matching(self):
        self.assertEqual(name_score('AB', 'AC'), 0)

    def test_player_on_right_is_not_own_kill_and_other_rows_cannot_supply_id(self):
        boxes = [ocr.TextBox('enemy', .9, .1, .1, .35, .2),
                 ocr.TextBox('player', .9, .65, .1, .95, .2),
                 ocr.TextBox('teammate', .9, .1, .4, .4, .5),
                 ocr.TextBox('victim', .9, .65, .4, .95, .5)]
        self.assertEqual(killfeed.rows_from_boxes(boxes, 'player', .8), [])

    def test_friendly_blue_name_is_not_an_enemy_region(self):
        image = np.zeros((120,300,3),np.uint8)
        cv2.putText(image, 'PLAYER', (160,60), 0, .5, (220,140,30), 1)
        self.assertEqual(killfeed.red_name_regions(image), [])

    def test_two_independent_frames_required_for_feed_confirmation(self):
        tracker = killfeed.FeedTracker()
        row = killfeed.FeedRow('player','enemy',1,'player -> enemy')
        self.assertEqual(tracker.observe(1, [row, row]), [])
        self.assertEqual(len(tracker.observe(1.333, [row])), 1)
        self.assertEqual(tracker.observe(2, [row]), [])

    def test_a_weak_bridge_cannot_merge_two_originally_different_targets(self):
        tracker=killfeed.FeedTracker()
        a,b,c=['10x10:'+value for value in ('a','b','c')]
        def match(x,y):return x==y or c in (x,y)
        def row(signature):return killfeed.FeedRow('player',signature,1,'',signature)
        with patch.object(killfeed,'glyphs_match',side_effect=match):
            tracker.observe(0,[row(a)]);first=tracker.observe(.3,[row(a)])[0][2]
            tracker.observe(1,[row(b)]);second=tracker.observe(1.3,[row(b)])[0][2]
            tracker.observe(2,[row(c)])
        self.assertNotEqual(tracker.root(first),tracker.root(second))

    def test_clear_later_frame_can_unify_fragmented_tracks(self):
        tracker=killfeed.FeedTracker()
        a,b,c=['10x10:'+value for value in ('a','b','c')]
        strong={'value':False}
        def match(x,y):return x==y or c in (x,y) or strong['value']
        def row(signature):return killfeed.FeedRow('player',signature,1,'',signature)
        with patch.object(killfeed,'glyphs_match',side_effect=match):
            tracker.observe(0,[row(a)]);first=tracker.observe(.3,[row(a)])[0][2]
            tracker.observe(1,[row(b)]);second=tracker.observe(1.3,[row(b)])[0][2]
            strong['value']=True;tracker.observe(2,[row(c)])
        self.assertEqual(tracker.root(first),tracker.root(second))

    def test_feed_detects_without_any_center_prompt(self):
        frames = [np.zeros((120,200,3),np.uint8) for _ in range(3)]
        cap = _FakeCapture(frames, 3)
        row = killfeed.FeedRow('player','enemy',1,'player -> enemy')
        with (patch.object(detector.cv2,'VideoCapture',return_value=cap),
              patch.object(detector,'_visual_prefilter',return_value=False),
              patch.object(killfeed,'red_name_regions',return_value=[(1,1,20,10)]),
              patch.object(killfeed,'read_rows',return_value=[row])):
            marks = detector.analyze(Path('fake.mp4'), detector.DetectParams(player_id='player'))
        self.assertEqual(len(marks), 1)
        self.assertTrue(marks[0]['confirmed'])
        self.assertFalse(marks[0]['review_required'])

    def test_different_targets_are_not_lost_in_analyze_debounce(self):
        cap = _FakeCapture([np.zeros((120,200,3),np.uint8) for _ in range(6)], 3)
        prompts = [(True,'击倒 enemyA')]*2 + [(True,'击倒 enemyB')]*4
        with (patch.object(detector.cv2,'VideoCapture',return_value=cap),
              patch.object(detector,'_visual_prefilter',return_value=True),
              patch.object(killfeed,'red_name_regions',return_value=[]),
              patch.object(detector,'_prompt_present',side_effect=prompts),
              patch.object(detector,'_refine_prompt_time',side_effect=lambda p,t,*a:(t,'')),
              patch.object(detector,'_confirm_id_near_time',return_value=detector.IdEvidence(
                  confirmed=True,meaningful_text_frames=2,scanned_frames=3,confidence=.9))):
            marks = detector.analyze(Path('fake.mp4'), detector.DetectParams(player_id='player'))
        self.assertEqual([m['victim_id'] for m in marks], ['enemya','enemyb'])


class HighlightSelectionTests(TestCase):
    def mark(self, t, victim, **values):
        return dict(id=str(t), time=t, victim_id=victim, confirmed=True, review_required=False,
                    event_type='down', **values)

    def test_two_distinct_people_inside_sixty_seconds(self):
        result = select_highlights([self.mark(30,'one'),self.mark(89,'two')], 200)
        self.assertEqual(len(result),1)
        self.assertEqual((result[0]['start'],result[0]['end']),(10,94))

    def test_one_person_down_and_finish_not_a_multikill(self):
        self.assertEqual(select_highlights([self.mark(30,'enemy'),self.mark(40,'enemy')],200),[])

    def test_sixty_second_boundary_and_outside(self):
        self.assertEqual(len(select_highlights([self.mark(30,'one'),self.mark(90,'two')],200,window=60)),1)
        self.assertEqual(select_highlights([self.mark(30,'one'),self.mark(90.01,'two')],200,window=60),[])

    def test_ninety_second_default_boundary_and_outside(self):
        self.assertEqual(len(select_highlights([self.mark(30,'one'),self.mark(120,'two')],200)),1)
        self.assertEqual(select_highlights([self.mark(30,'one'),self.mark(120.01,'two')],200),[])

    def test_uncertain_candidates_do_not_make_a_multikill(self):
        second=self.mark(40,'two');second['confirmed']=False;second['review_required']=True
        self.assertEqual(select_highlights([self.mark(30,'one'),second],200),[])

    def test_overlapping_multikills_do_not_duplicate_footage(self):
        result=select_highlights([self.mark(30,'one'),self.mark(60,'two'),self.mark(80,'three')],200)
        self.assertEqual(len(result),1)
        self.assertEqual(len(result[0]['events']),3)
