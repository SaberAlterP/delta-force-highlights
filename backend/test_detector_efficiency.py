"""Regression tests for the adaptive OCR detection pipeline."""
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

import cv2
import numpy as np

from app import config
from app.services import detector


class _FakeCapture:
    def __init__(self, frames: list[np.ndarray], fps: float):
        self.frames = frames
        self.fps = fps
        self.pos = 0
        self.current = -1

    def isOpened(self):
        return True

    def get(self, prop):
        if prop == cv2.CAP_PROP_FPS:
            return self.fps
        if prop == cv2.CAP_PROP_FRAME_COUNT:
            return len(self.frames)
        return 0

    def set(self, prop, value):
        if prop == cv2.CAP_PROP_POS_FRAMES:
            self.pos = int(value)
            return True
        return False

    def grab(self):
        if self.pos >= len(self.frames):
            return False
        self.current = self.pos
        self.pos += 1
        return True

    def retrieve(self):
        if self.current < 0:
            return False, None
        return True, self.frames[self.current].copy()

    def release(self):
        pass


class DetectorEfficiencyTests(TestCase):
    def test_unicode_path_templates_are_decoded(self):
        detector._id_template_cache = None
        self.assertEqual(len(detector._load_id_templates()), 2)

    def test_default_coarse_scan_restores_stable_three_fps_baseline(self):
        self.assertEqual(config.DETECT.sample_fps, 3.0)
        self.assertGreater(config.DETECT.fine_scan_fps, config.DETECT.sample_fps)

    def test_visual_prefilter_rejects_flat_frames_but_keeps_text(self):
        blank = np.zeros((130, 216, 3), dtype=np.uint8)
        white = np.full_like(blank, 255)
        text = blank.copy()
        cv2.putText(text, "KILL", (15, 75), cv2.FONT_HERSHEY_SIMPLEX,
                    1.2, (255, 255, 255), 2, cv2.LINE_AA)

        self.assertFalse(detector._visual_prefilter(blank))
        self.assertFalse(detector._visual_prefilter(white))
        self.assertTrue(detector._visual_prefilter(text))

    def test_assist_prompt_is_not_a_kill_candidate(self):
        crop = np.zeros((40, 160, 3), dtype=np.uint8)
        with patch.object(detector.ocr, "read_texts",
                          return_value=[("协助击倒 沧溟Cang", 0.9)]):
            hit, text = detector._prompt_present(crop, ["击倒", "击败"])
        self.assertFalse(hit)
        self.assertIn("协助击倒", text)

    def test_contrast_enhanced_id_pass_recovers_dim_text(self):
        crop = np.zeros((80, 240, 3), dtype=np.uint8)
        with patch.object(
            detector.ocr,
            "read_texts",
            side_effect=[[('noise', 0.2)], [('测试玩家', 0.08)]],
        ):
            hit, text, ratio = detector._id_present(crop, "测试玩家", 0.7)
        self.assertTrue(hit)
        self.assertIn("测试玩家", text)
        self.assertEqual(ratio, 1.0)

    def test_ocr_keeps_scanning_during_same_prompt_deduplication(self):
        frames = [np.zeros((100, 100, 3), dtype=np.uint8) for _ in range(12)]
        fake = _FakeCapture(frames, fps=2.0)
        stats = {}
        prompt_results = [(True, "击败 enemyA")] * 12

        with (
            patch.object(detector.cv2, "VideoCapture", return_value=fake),
            patch.object(detector, "_visual_prefilter", return_value=True),
            patch.object(detector, "_prompt_present", side_effect=prompt_results) as prompt_mock,
            patch.object(detector, "_refine_prompt_time", return_value=(0.0, "击败")),
            patch.object(
                detector,
                "_confirm_id_near_time",
                return_value=detector.IdEvidence(
                    confirmed=True, text="player", confidence=1.0,
                    meaningful_text_frames=1, scanned_frames=3,
                ),
            ),
        ):
            kills = detector.analyze(
                Path("fake.mp4"), detector.DetectParams(player_id="player"), stats_out=stats
            )

        self.assertEqual(len(kills), 1)
        self.assertEqual(stats["debounce_skips"], 11)
        self.assertEqual(stats["prompt_ocr_calls"], 12)
        self.assertEqual(prompt_mock.call_count, 12)

    def test_prompt_candidate_is_kept_when_id_does_not_match(self):
        frames = [np.zeros((100, 100, 3), dtype=np.uint8)]
        fake = _FakeCapture(frames, fps=2.0)
        stats = {}
        with (
            patch.object(detector.cv2, "VideoCapture", return_value=fake),
            patch.object(detector, "_visual_prefilter", return_value=True),
            patch.object(detector, "_prompt_present", return_value=(True, "击败")),
            patch.object(detector, "_refine_prompt_time", return_value=(0.0, "击败")),
            patch.object(
                detector,
                "_confirm_id_near_time",
                return_value=detector.IdEvidence(
                    text="other", confidence=0.2,
                    meaningful_text_frames=1, scanned_frames=3,
                ),
            ),
        ):
            kills = detector.analyze(
                Path("fake.mp4"), detector.DetectParams(player_id="player"), stats_out=stats
            )

        self.assertEqual(len(kills), 1)
        self.assertEqual(kills[0]["confidence"], 0.55)
        self.assertEqual(stats["id_uncertain_marks"], 1)
        self.assertEqual(stats["id_blank_rejects"], 0)

    def test_prompt_candidate_is_rejected_when_id_window_is_conclusively_blank(self):
        frames = [np.zeros((100, 100, 3), dtype=np.uint8)]
        fake = _FakeCapture(frames, fps=2.0)
        stats = {}
        with (
            patch.object(detector.cv2, "VideoCapture", return_value=fake),
            patch.object(detector, "_visual_prefilter", return_value=True),
            patch.object(detector, "_prompt_present", return_value=(True, "击中头部击败 哈夫克士兵")),
            patch.object(detector, "_refine_prompt_time", return_value=(0.0, "击中头部击败 哈夫克士兵")),
            patch.object(
                detector,
                "_confirm_id_near_time",
                return_value=detector.IdEvidence(scanned_frames=3),
            ),
        ):
            kills = detector.analyze(
                Path("fake.mp4"), detector.DetectParams(player_id="player"), stats_out=stats
            )

        self.assertEqual(kills, [])
        self.assertEqual(stats["id_blank_rejects"], 1)
        self.assertEqual(stats["id_uncertain_marks"], 0)

    def test_same_rejected_prompt_is_not_confirmed_repeatedly(self):
        frames = [np.zeros((100, 100, 3), dtype=np.uint8) for _ in range(6)]
        fake = _FakeCapture(frames, fps=2.0)
        stats = {}
        blank = detector.IdEvidence(scanned_frames=3)
        with (
            patch.object(detector.cv2, "VideoCapture", return_value=fake),
            patch.object(detector, "_visual_prefilter", return_value=True),
            patch.object(
                detector, "_prompt_present",
                return_value=(True, "击中头部击败 哈夫克士兵"),
            ),
            patch.object(
                detector, "_refine_prompt_time",
                side_effect=lambda _p, t, *_args: (t, "击中头部击败 哈夫克士兵"),
            ),
            patch.object(detector, "_confirm_id_near_time", return_value=blank) as confirm,
        ):
            kills = detector.analyze(
                Path("fake.mp4"), detector.DetectParams(player_id="player"), stats_out=stats
            )

        self.assertEqual(kills, [])
        self.assertEqual(confirm.call_count, 1)
        self.assertEqual(stats["id_blank_rejects"], 1)
        self.assertEqual(stats["debounce_skips"], 5)

    def test_minor_ocr_variation_of_rejected_prompt_is_also_deduplicated(self):
        self.assertGreaterEqual(
            detector.SequenceMatcher(
                None,
                detector._normalize("击中头部击败 哈夫克士兵"),
                detector._normalize("击中头部击败 哈夫克土兵"),
            ).ratio(),
            config.DETECT.rejected_prompt_similarity,
        )

    def test_prompt_and_id_together_record_official_kill(self):
        frames = [np.zeros((100, 100, 3), dtype=np.uint8)]
        fake = _FakeCapture(frames, fps=2.0)
        with (
            patch.object(detector.cv2, "VideoCapture", return_value=fake),
            patch.object(detector, "_visual_prefilter", return_value=True),
            patch.object(detector, "_prompt_present", return_value=(True, "击败")),
            patch.object(detector, "_refine_prompt_time", return_value=(0.0, "击败")),
            patch.object(
                detector,
                "_confirm_id_near_time",
                return_value=detector.IdEvidence(
                    confirmed=True, text="player", confidence=0.85,
                    meaningful_text_frames=1, scanned_frames=3,
                ),
            ),
        ):
            kills = detector.analyze(
                Path("fake.mp4"), detector.DetectParams(player_id="player")
            )

        self.assertEqual(len(kills), 1)
        self.assertEqual(kills[0]["id_text"], "player")
        self.assertEqual(kills[0]["prompt_text"], "击败")
        self.assertEqual(kills[0]["confidence"], 0.79)
        self.assertTrue(kills[0]["review_required"])

    def test_fine_scan_returns_earliest_confirmed_prompt(self):
        frames = [np.zeros((100, 100, 3), dtype=np.uint8) for _ in range(20)]
        fake = _FakeCapture(frames, fps=12.0)
        with (
            patch.object(detector.cv2, "VideoCapture", return_value=fake),
            patch.object(detector, "_visual_prefilter", return_value=True),
            patch.object(detector, "_prompt_present",
                         side_effect=[(False, ""), (True, "击败")]),
        ):
            stats = {"fine_prompt_ocr_calls": 0}
            refined_t, text = detector._refine_prompt_time(
                Path("fake.mp4"), 1.0, 12.0,
                detector.DetectParams(player_id="player"), stats
            )

        # 3 FPS 稳定基线回看 1/3 秒：从第 8 帧开始，第二个 6 FPS 样本是第 10 帧。
        self.assertAlmostEqual(refined_t, 10 / 12, places=3)
        self.assertEqual(text, "击败")
        self.assertEqual(stats["fine_prompt_ocr_calls"], 2)

    def test_id_confirmation_always_runs_ocr_without_a_brightness_prefilter(self):
        frames = [np.zeros((100, 100, 3), dtype=np.uint8) for _ in range(40)]
        fake = _FakeCapture(frames, fps=12.0)
        stats = {"id_confirm_ocr_calls": 0}
        calls = {"count": 0}

        def id_result(*_args):
            calls["count"] += 1
            return (False, "noise", 0.2) if calls["count"] == 1 else (True, "player", 0.9)

        with (
            patch.object(detector.cv2, "VideoCapture", return_value=fake),
            patch.object(detector, "_id_present", side_effect=id_result) as id_mock,
            patch.object(detector, "_template_match_score", return_value=0.0),
            patch.object(detector, "_frame_change_score", return_value=0.0),
        ):
            evidence = detector._confirm_id_near_time(
                Path("fake.mp4"), 1.0, 12.0,
                detector.DetectParams(player_id="player"), stats
            )

        self.assertTrue(evidence.confirmed)
        self.assertEqual(evidence.text, "player")
        self.assertEqual(evidence.confidence, 0.9)
        self.assertFalse(evidence.conclusively_blank)
        self.assertEqual(stats["id_confirm_ocr_calls"], 14)
        self.assertEqual(id_mock.call_count, 14)

    def test_multi_frame_vote_combines_different_character_errors(self):
        score = detector._multi_frame_id_vote("ABCDE", ["ABCXE", "ABYDE"])
        self.assertGreaterEqual(score, 0.8)

    def test_composite_evidence_can_confirm_without_single_frame_threshold(self):
        frames = [np.zeros((100, 100, 3), dtype=np.uint8) for _ in range(40)]
        fake = _FakeCapture(frames, fps=12.0)
        stats = {"id_confirm_ocr_calls": 0}
        variants = iter(["playef", "plaxer"] * 20)
        with (
            patch.object(detector.cv2, "VideoCapture", return_value=fake),
            patch.object(detector, "_id_present",
                         side_effect=lambda *_: (False, next(variants), 0.55)),
            patch.object(detector, "_template_match_score", return_value=0.65),
            patch.object(detector, "_frame_change_score", return_value=0.8),
        ):
            evidence = detector._confirm_id_near_time(
                Path("fake.mp4"), 1.0, 12.0,
                detector.DetectParams(player_id="player"), stats
            )

        self.assertTrue(evidence.confirmed)
        self.assertGreaterEqual(
            evidence.confidence, detector.config.DETECT.id_composite_threshold
        )
        self.assertGreater(stats["best_id_vote_score"], 0.7)
        self.assertEqual(stats["best_id_template_score"], 0.65)

    def test_template_and_new_row_can_confirm_when_ocr_is_empty(self):
        frames = [np.zeros((100, 100, 3), dtype=np.uint8) for _ in range(40)]
        fake = _FakeCapture(frames, fps=12.0)
        stats = {"id_confirm_ocr_calls": 0}
        with (
            patch.object(detector.cv2, "VideoCapture", return_value=fake),
            patch.object(detector, "_id_present", return_value=(False, "", 0.0)),
            patch.object(detector, "_template_match_score", return_value=0.64),
            patch.object(detector, "_frame_change_score", return_value=0.5),
        ):
            evidence = detector._confirm_id_near_time(
                Path("fake.mp4"), 1.0, 12.0,
                detector.DetectParams(player_id="player"), stats
            )
        self.assertTrue(evidence.confirmed)
        self.assertGreaterEqual(evidence.confidence, 0.60)
        self.assertFalse(evidence.conclusively_blank)
        self.assertGreaterEqual(evidence.template_support_frames, 3)

    def test_single_frame_template_spike_is_rejected_as_background_noise(self):
        frames = [np.zeros((100, 100, 3), dtype=np.uint8) for _ in range(40)]
        fake = _FakeCapture(frames, fps=12.0)
        stats = {"id_confirm_ocr_calls": 0}
        scores = iter([0.69] + [0.30] * 30)
        with (
            patch.object(detector.cv2, "VideoCapture", return_value=fake),
            patch.object(detector, "_id_present", return_value=(False, "1 1", 0.0)),
            patch.object(detector, "_template_match_score", side_effect=lambda *_: next(scores)),
            patch.object(detector, "_frame_change_score", return_value=1.0),
        ):
            evidence = detector._confirm_id_near_time(
                Path("fake.mp4"), 1.0, 12.0,
                detector.DetectParams(player_id="测试玩家"), stats
            )

        self.assertFalse(evidence.confirmed)
        self.assertEqual(evidence.template_support_frames, 1)
        self.assertTrue(evidence.conclusively_blank)

    def test_camera_motion_alone_does_not_turn_a_blank_id_window_into_evidence(self):
        frames = [np.zeros((100, 100, 3), dtype=np.uint8) for _ in range(40)]
        fake = _FakeCapture(frames, fps=12.0)
        stats = {"id_confirm_ocr_calls": 0}
        with (
            patch.object(detector.cv2, "VideoCapture", return_value=fake),
            patch.object(detector, "_id_present", return_value=(False, "", 0.0)),
            patch.object(detector, "_template_match_score", return_value=0.0),
            patch.object(detector, "_frame_change_score", return_value=1.0),
        ):
            evidence = detector._confirm_id_near_time(
                Path("fake.mp4"), 1.0, 12.0,
                detector.DetectParams(player_id="player"), stats
            )

        self.assertFalse(evidence.confirmed)
        self.assertTrue(evidence.conclusively_blank)
        self.assertEqual(evidence.change_score, 1.0)
        self.assertGreaterEqual(evidence.scanned_frames, 3)

    def test_numeric_ocr_fragments_do_not_turn_a_blank_window_into_killfeed(self):
        frames = [np.zeros((100, 100, 3), dtype=np.uint8) for _ in range(40)]
        fake = _FakeCapture(frames, fps=12.0)
        stats = {"id_confirm_ocr_calls": 0}
        with (
            patch.object(detector.cv2, "VideoCapture", return_value=fake),
            patch.object(detector, "_id_present", return_value=(False, "1 1", 0.0)),
            patch.object(detector, "_template_match_score", return_value=0.0),
            patch.object(detector, "_frame_change_score", return_value=1.0),
        ):
            evidence = detector._confirm_id_near_time(
                Path("fake.mp4"), 1.0, 12.0,
                detector.DetectParams(player_id="测试玩家"), stats
            )

        self.assertEqual(evidence.text, "1 1")
        self.assertEqual(evidence.meaningful_text_frames, 0)
        self.assertTrue(evidence.conclusively_blank)


if __name__ == "__main__":
    import unittest
    unittest.main()
