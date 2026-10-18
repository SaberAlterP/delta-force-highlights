"""识别子进程调度：常驻服务不持有 EasyOCR/PyTorch/CUDA 模型。"""
from concurrent.futures import CancelledError
from dataclasses import asdict
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import uuid

from .. import config

_analysis_lock = threading.Lock()
_active_directories = set()


def active_directories():
    return tuple(_active_directories)


def analyze_isolated(source, params, progress_cb=None, cancel_cb=None):
    # 手动识别和监控队列共用单槽，避免多个 CUDA 模型挤占显存。
    while not _analysis_lock.acquire(timeout=.25):
        if cancel_cb and cancel_cb():
            raise CancelledError()
        if progress_cb:
            progress_cb(0,'等待前一段录像完成识别')
    try:
        directory = config.STORAGE_DIR/'workflow'/'workers'/uuid.uuid4().hex
        directory.mkdir(parents=True,exist_ok=True)
        _active_directories.add(directory)
        request, result, progress = [directory/name for name in ('request.json','result.json','progress.json')]
        request.write_text(json.dumps(dict(source=str(source),params=asdict(params)),ensure_ascii=False),encoding='utf-8')
        env = os.environ.copy();env['PYTHONIOENCODING']='utf-8'
        with (directory/'worker.log').open('w',encoding='utf-8') as log:
            proc = subprocess.Popen([sys.executable,'-m','app.analyze_worker',str(request),str(result),str(progress)],
                cwd=config.BASE_DIR, stdout=log, stderr=subprocess.STDOUT, env=env,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
            try:
                last = ''
                while proc.poll() is None:
                    if cancel_cb and cancel_cb():
                        raise CancelledError()
                    if progress_cb and progress.exists():
                        try:
                            text=progress.read_text(encoding='utf-8')
                            if text != last:
                                status=json.loads(text);progress_cb(status['progress'],status['message']);last=text
                        except (OSError,ValueError):
                            pass
                    threading.Event().wait(.25)
                if proc.returncode != 0 or not result.is_file():
                    raise RuntimeError(f'录像识别失败，诊断日志：{directory / "worker.log"}')
                if cancel_cb and cancel_cb():
                    raise CancelledError()
                return json.loads(result.read_text(encoding='utf-8'))
            finally:
                if proc.poll() is None:
                    if os.name == 'nt':
                        # Windows venv 的 python.exe 可能再启动真正的解释器；必须一并结束。
                        subprocess.run(['taskkill','/PID',str(proc.pid),'/T','/F'],
                            stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
                            creationflags=subprocess.CREATE_NO_WINDOW,check=False)
                    else:
                        proc.terminate()
                    try:proc.wait(timeout=3)
                    except subprocess.TimeoutExpired:proc.kill();proc.wait(timeout=3)
    finally:
        if 'directory' in locals():
            _active_directories.discard(directory)
            # 成功结果已交给队列/网页，不长期保存重复的扫描 JSON 与日志。
            if 'proc' in locals() and proc.returncode == 0:
                for name in ('request.json','result.json','progress.json','worker.log'):
                    path=directory/name
                    try:
                        if path.is_file() and not path.is_symlink():path.unlink()
                    except OSError:pass
                try:directory.rmdir()
                except OSError:pass
        _analysis_lock.release()
