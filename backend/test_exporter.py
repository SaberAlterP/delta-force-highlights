"""Regression tests for real 16:9 pixel stretching."""
from pathlib import Path
import shutil
import subprocess
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from app.services import exporter
from app.services.video import probe


class ExporterStretchTests(TestCase):
    def capture_command(self, *, accurate=False, stretch=False):
        commands = []
        with patch.object(exporter, "_ffmpeg", return_value="ffmpeg"), \
             patch.object(exporter, "_run", side_effect=lambda cmd, **_kwargs: commands.append(cmd)):
            exporter.cut_clip(
                Path("source.mp4"), 12.5, 20.0, Path("output.mp4"),
                accurate=accurate, stretch_169=stretch,
            )
        return commands[0]

    def test_fast_without_stretch_keeps_stream_copy(self):
        command = self.capture_command(accurate=False, stretch=False)
        self.assertIn("copy", command)
        self.assertNotIn("-vf", command)

    def test_fast_stretch_reencodes_real_pixels(self):
        command = self.capture_command(accurate=False, stretch=True)
        self.assertIn("-vf", command)
        self.assertIn("scale=trunc(ih*16/9/2)*2:trunc(ih/2)*2,setsar=1", command)
        self.assertIn("libx264", command)
        self.assertNotIn("copy", command)
        self.assertLess(command.index("-ss"), command.index("-i"))

    def test_accurate_stretch_places_seek_after_input(self):
        command = self.capture_command(accurate=True, stretch=True)
        self.assertIn("-vf", command)
        self.assertIn("libx264", command)
        self.assertGreater(command.index("-ss"), command.index("-i"))

    def test_real_export_has_sixteen_by_nine_pixels(self):
        if not shutil.which('ffmpeg'):self.skipTest('ffmpeg unavailable')
        with TemporaryDirectory() as temp:
            source=Path(temp)/'source.mp4';out=Path(temp)/'stretched.mp4'
            subprocess.run([exporter._ffmpeg(),'-v','error','-f','lavfi','-i',
                'testsrc2=size=480x360:rate=10','-t','2','-c:v','libx264','-pix_fmt','yuv420p',
                str(source)],check=True,capture_output=True)
            exporter.cut_clip(source,.2,1.2,out,stretch_169=True)
            meta=probe(out)
            self.assertEqual((meta['width'],meta['height']),(640,360))


if __name__ == "__main__":
    import unittest
    unittest.main()
