"""视频压缩：命令拼装、目标大小规划，以及真实 ffmpeg 压缩（装了 ffmpeg 才跑）。"""
from pathlib import Path
import shutil
import subprocess
from tempfile import TemporaryDirectory
from unittest import TestCase, skipUnless
from unittest.mock import patch

from app.services import compressor
from app.services.video import probe

INFO_1080P60 = dict(duration=60.0, width=1920, height=1080, fps=60.0)


class CommandTests(TestCase):
    def cmd(self, preset, info=INFO_1080P60, **kw):
        with patch.object(compressor, '_ffmpeg', return_value='ffmpeg'):
            return compressor.build_command(Path('in.mp4'), Path('out.mp4'), info, preset, **kw)

    def test_share_scales_to_720_and_keeps_60fps(self):
        c = self.cmd('share')
        self.assertIn('scale=-2:720:flags=lanczos', c[c.index('-vf') + 1])
        self.assertNotIn('fps=', c[c.index('-vf') + 1])
        self.assertIn('libx264', c)
        self.assertEqual(c[c.index('-crf') + 1], '26')
        self.assertIn('+faststart', c)

    def test_small_drops_to_30fps(self):
        vf = (c := self.cmd('small'))[c.index('-vf') + 1]
        self.assertIn('scale=-2:540', vf)
        self.assertIn('fps=30', vf)

    def test_never_upscales(self):
        c = self.cmd('hd', dict(duration=10, width=1280, height=720, fps=30))
        self.assertNotIn('-vf', c)

    def test_gpu_uses_nvenc(self):
        c = self.cmd('share', gpu=True)
        self.assertIn('h264_nvenc', c)
        self.assertNotIn('-crf', c)

    def test_target_uses_bitrate(self):
        c = self.cmd('target', target_mb=25)
        self.assertIn('-b:v', c)
        self.assertNotIn('-crf', c)

    def test_unknown_preset(self):
        with self.assertRaises(ValueError):
            self.cmd('nope')


class TargetPlanTests(TestCase):
    def test_fits_budget(self):
        plan = compressor.target_plan(60, 25, 1080, 60)
        total_mb = (plan['video_kbps'] + plan['audio_kbps']) * 60 / 8192
        self.assertLess(total_mb, 25)
        self.assertEqual(plan['max_height'], 720)

    def test_long_video_lowers_resolution(self):
        plan = compressor.target_plan(600, 25, 1080, 60)
        self.assertEqual(plan['max_height'], 480)
        self.assertEqual(plan['max_fps'], 30)

    def test_impossible_target_rejected(self):
        with self.assertRaises(ValueError):
            compressor.target_plan(3600, 5, 1080, 60)


@skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), '需要 ffmpeg')
class RealCompressTests(TestCase):
    def make_video(self, folder: Path) -> Path:
        src = folder / 'src.mp4'
        subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i', 'testsrc2=s=1920x1080:r=60:d=4',
                        '-f', 'lavfi', '-i', 'sine=d=4', '-c:v', 'libx264', '-crf', '12', '-preset', 'ultrafast',
                        '-c:a', 'aac', '-shortest', str(src)], check=True)
        return src

    def test_share_and_target(self):
        with TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            src = self.make_video(tmp)
            seen = []
            r = compressor.compress(src, tmp / 'out', 'share', use_gpu=False,
                                    progress_cb=lambda p, m: seen.append(p))
            self.assertTrue(Path(r['path']).is_file())
            self.assertEqual(r['height'], 720)
            self.assertLess(r['size'], r['src_size'])
            self.assertTrue(seen)
            self.assertFalse(list((tmp / 'out').glob('.pending_*')))

            r2 = compressor.compress(src, tmp / 'out', 'target', target_mb=0.5, use_gpu=False)
            self.assertLessEqual(r2['size'], 0.5 * 1024 * 1024)
            self.assertFalse(r2['over_target'])
            self.assertNotEqual(r['path'], r2['path'])
            self.assertAlmostEqual(probe(Path(r2['path']))['duration'], 4, delta=0.3)

    def test_cancel_cleans_up(self):
        from concurrent.futures import CancelledError
        with TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            src = self.make_video(tmp)
            with self.assertRaises(CancelledError):
                compressor.compress(src, tmp / 'out', 'hd', use_gpu=False, cancel_cb=lambda: True)
            self.assertFalse(list((tmp / 'out').glob('*')))
