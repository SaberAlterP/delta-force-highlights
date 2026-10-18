from pathlib import Path
from unittest import TestCase, skipUnless
from unittest.mock import patch
import cv2
import numpy as np
from app.services import killfeed,ocr

FIXTURES=Path(__file__).parent/'tests/fixtures/killfeed'

def load(name):
    return cv2.imdecode(np.fromfile(str(FIXTURES/(name+'.png')),dtype=np.uint8),cv2.IMREAD_COLOR)


@skipUnless(FIXTURES.is_dir(), '缺少真实截图 tests/fixtures/killfeed，跳过')
class RealKillfeedFixtures(TestCase):
    def test_same_target_across_fade_background_and_row_movement(self):
        for name in ('front','gu','shi','mouse'):
            with self.subTest(name=name):
                a=killfeed.glyph_signature(load(name+'-a'))
                b=killfeed.glyph_signature(load(name+'-b'))
                self.assertTrue(killfeed.glyphs_match(a,b))

    def test_distinct_targets_do_not_merge_after_image_resizing(self):
        signatures={name:killfeed.glyph_signature(load(name+'-a')) for name in ('front','gu','shi','mouse')}
        for a in signatures:
            for b in signatures:
                if a!=b:
                    with self.subTest(a=a,b=b):
                        self.assertFalse(killfeed.glyphs_match(signatures[a],signatures[b]))

    def test_real_friendly_revival_is_rejected_before_ocr(self):
        with patch.object(ocr,'recognize_line') as recognize:
            self.assertEqual(killfeed.read_rows(load('friendly-revive'),'测试玩家',.7),[])
            recognize.assert_not_called()
