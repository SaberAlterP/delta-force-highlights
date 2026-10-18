"""Regression tests for the calibrated high-efficiency OCR regions."""
from unittest import TestCase

import numpy as np

from app import config
from app.services.detector import DetectParams, _crop


class DetectionConfigTests(TestCase):
    def test_detector_version_is_exposed_from_version_file(self):
        self.assertRegex(config.DETECTOR_VERSION, r"^\d{4}\.\d{2}\.\d{2}\.\d+$")

    def test_user_supplied_id_templates_are_installed(self):
        self.assertEqual(len(list(config.ID_TEMPLATE_DIR.glob("*.png"))), 2)

    def test_default_keywords_match_requested_set_and_order(self):
        self.assertEqual(
            config.DETECT.knockdown_keywords,
            ["击败", "击中头部击败", "灭队", "击倒", "击中头部击倒", "淘汰"],
        )

    def test_prompt_region_area_is_reduced_by_at_least_75_percent(self):
        legacy = (0.66 - 0.34) * (0.90 - 0.64)
        region = config.DETECT.prompt_region
        current = (region.x2 - region.x1) * (region.y2 - region.y1)
        self.assertLessEqual(current, legacy * 0.25)

    def test_id_region_area_is_reduced_by_at_least_40_percent(self):
        legacy = (0.995 - 0.66) * (0.15 - 0.02)
        region = config.DETECT.id_region
        current = (region.x2 - region.x1) * (region.y2 - region.y1)
        self.assertLessEqual(current, legacy * 0.60)

    def test_crop_dimensions_match_1440x1080_source(self):
        frame = np.zeros((1080, 1440, 3), dtype=np.uint8)
        params = DetectParams()
        prompt = _crop(frame, params.prompt_region)
        id_crop = _crop(frame, params.id_region)
        self.assertEqual(prompt.shape[:2], (130, 216))
        self.assertEqual(id_crop.shape[:2], (119, 295))


if __name__ == "__main__":
    import unittest
    unittest.main()
