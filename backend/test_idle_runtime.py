from pathlib import Path
import subprocess
import sys
from unittest import TestCase


class IdleRuntimeTests(TestCase):
    def test_web_and_watch_service_do_not_import_ocr_or_video_runtime(self):
        command = "import app.main,sys; assert not ({'torch','easyocr','cv2','numpy'} & sys.modules.keys())"
        subprocess.run([sys.executable,'-c',command],cwd=Path(__file__).parent,
                       check=True,capture_output=True,timeout=15)
