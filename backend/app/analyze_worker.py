"""一次识别一个录像；进程退出后由操作系统回收 OCR/CUDA 占用。"""
from __future__ import annotations
import json
from pathlib import Path
import sys
import time

from . import config
from .services import detector


def main():
    request_path, result_path, progress_path = map(Path, sys.argv[1:4])
    request = json.loads(request_path.read_text(encoding='utf-8'))
    params = detector.DetectParams(**request['params'])
    config.USE_GPU = params.use_gpu  # 子进程内才加载 OCR，这里设置即可生效
    last = 0.
    def progress(value, message):
        nonlocal last
        now = time.monotonic()
        if now-last < .75 and value < 1:
            return
        last = now
        temp = progress_path.with_suffix('.writing')
        # 监控进程读取 progress.json 时 Windows 会拒绝替换；进度仅供显示，重试后放弃即可。
        for attempt in range(5):
            try:
                temp.write_text(json.dumps(dict(progress=value,message=message),ensure_ascii=False),encoding='utf-8')
                temp.replace(progress_path)
                return
            except PermissionError:
                time.sleep(.05*(attempt+1))
    marks = detector.analyze(Path(request['source']), params, progress_cb=progress)
    temp = result_path.with_suffix('.writing')
    temp.write_text(json.dumps(marks,ensure_ascii=False),encoding='utf-8')
    temp.replace(result_path)


if __name__ == '__main__':
    main()
