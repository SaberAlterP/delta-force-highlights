"""视频压缩：把任意一段视频（整局原片 / 高光 / 手动剪辑 / 上传的 / 电脑上选的 / 集锦成片）
重新编码成小文件，方便发给别人。"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse

from .. import config
from ..services import compressor, desktop, projects
from ..services.jobs import Job, jobs
from ..services.media import video_response
from ..services.video import probe
from ..services.workflow import workflow

router = APIRouter(prefix='/api/compress')

OUTPUT_FOLDER = '压缩视频'
# 只有从本机选择窗口里选出来的文件才能按路径压缩
_picked: set[str] = set()


def output_dir() -> Path:
    root = workflow.settings.output_root
    if root and Path(root).is_dir():
        return Path(root) / OUTPUT_FOLDER
    return config.STORAGE_DIR / 'compressed'


def resolve(source: dict) -> Path:
    """把前端给的来源说明换成本机文件路径；不认识或越界的一律拒绝。"""
    kind = source.get('kind')
    record_id = str(source.get('record_id') or '')
    if kind in ('highlight', 'original', 'manual'):
        row = workflow.recording(record_id)
        if not row:
            raise LookupError('这局录像不存在')
        if kind == 'highlight':
            files = (row.get('result') or {}).get('files', [])
            index = source.get('index')
            if not isinstance(index, int) or not 0 <= index < len(files):
                raise LookupError('高光不存在')
            path = Path(files[index]['path'])
        elif kind == 'original':
            if row['status'] == 'deleted':
                raise LookupError('整局原片已删除')
            path = workflow._source_path(row)
        else:
            entry = next((e for e in projects.manual_exports(row) if e['id'] == source.get('export_id')), None)
            item = next((f for f in entry['files'] if f['name'] == source.get('name')), None) if entry else None
            if not item:
                raise LookupError('手动剪辑不存在')
            base = projects.directory(row).resolve()
            path = base / item['path']
            if path.is_symlink() or not path.resolve().is_relative_to(base):
                raise LookupError('手动剪辑不存在')
    elif kind == 'upload':
        from .routes import _find_upload_path
        path = _find_upload_path(str(source.get('upload_id') or ''))
        if not path:
            raise LookupError('上传的视频已被清理')
    elif kind == 'montage':
        from ..services import montage_studio
        try:
            path = montage_studio.allowed(str(source.get('path') or ''))
        except PermissionError as exc:
            raise LookupError(str(exc))
    elif kind == 'picked':
        raw = str(source.get('path') or '')
        if raw not in _picked:
            raise LookupError('请先用「选择视频」挑一个文件')
        path = Path(raw)
    else:
        raise LookupError('不认识的视频来源')
    if not path.is_file():
        raise LookupError('视频文件已不存在')
    return path


def _describe(path: Path) -> dict:
    info = probe(path)
    return dict(name=path.name, path=str(path), size=path.stat().st_size,
                duration=info.get('duration'), width=info.get('width'),
                height=info.get('height'), fps=round(info.get('fps') or 0, 2))


@router.get('/presets')
def presets():
    return dict(presets=compressor.presets(), output_dir=str(output_dir()))


@router.post('/pick-file')
def pick_file(values: dict):
    """在本机弹出系统「打开文件」窗口（服务只监听 127.0.0.1）。"""
    exts = ' '.join(f'*{e}' for e in sorted(compressor.VIDEO_EXTS))
    script = ('import sys,tkinter as tk\nfrom tkinter import filedialog\n'
              'r=tk.Tk();r.withdraw();r.attributes("-topmost",True)\n'
              'print(filedialog.askopenfilename(initialdir=sys.argv[1] or None,title="选择要压缩的视频",'
              'filetypes=[("视频",sys.argv[2]),("全部文件","*.*")]) or "")')
    initial = str(values.get('initial') or workflow.settings.output_root or '')
    try:
        out = subprocess.run([sys.executable, '-c', script, initial, exts],
                             capture_output=True, text=True, encoding='utf-8', timeout=600)
    except (OSError, subprocess.SubprocessError) as exc:
        raise HTTPException(422, f'无法打开选择窗口：{exc}')
    raw = out.stdout.strip()
    if not raw:
        return dict(path='')
    path = Path(raw)
    if not path.is_file():
        raise HTTPException(404, '文件不存在')
    _picked.add(str(path))
    return dict(path=str(path), info=_describe(path))


@router.post('/probe')
def probe_source(source: dict):
    try:
        return _describe(resolve(source))
    except LookupError as exc:
        raise HTTPException(404, str(exc))


@router.post('')
def start(values: dict):
    preset = values.get('preset') or 'share'
    if preset not in compressor.PRESETS:
        raise HTTPException(422, '未知的压缩档位')
    try:
        target_mb = float(values.get('target_mb') or 0)
    except (TypeError, ValueError):
        raise HTTPException(422, '目标大小要填数字')
    try:
        src = resolve(values.get('source') or {})
    except LookupError as exc:
        raise HTTPException(404, str(exc))
    if preset == 'target':
        info = probe(src)
        try:
            compressor.target_plan(float(info.get('duration') or 0), target_mb,
                                   int(info.get('height') or 0), float(info.get('fps') or 0))
        except ValueError as exc:
            raise HTTPException(422, str(exc))
    out = output_dir()
    # 上传的录像在缓存里叫一串编号，用前端给的原文件名命名输出
    name = str(values.get('name') or '') if (values.get('source') or {}).get('kind') == 'upload' else ''

    def task(job: Job):
        job.update(message='准备压缩…')
        return compressor.compress(src, out, preset, target_mb=target_mb,
                                   progress_cb=lambda p, m: job.update(progress=p, message=m),
                                   cancel_cb=job.is_cancelled, name=name)

    job = jobs.submit('compress', task)
    return dict(job_id=job.job_id)


def _job(job_id: str) -> Job:
    job = jobs.get(job_id)
    if not job or job.kind != 'compress':
        raise HTTPException(404, '任务不存在')
    return job


@router.get('/{job_id}')
def status(job_id: str):
    snap = _job(job_id).snapshot()
    result = snap.get('result')
    if result:
        result = result | dict(folder=str(Path(result['path']).parent))
    return dict(state=snap['state'], progress=snap['progress'], message=snap['message'],
                error=snap['error'], result=result)


@router.post('/{job_id}/cancel')
def cancel(job_id: str):
    _job(job_id).cancel()
    return dict(ok=True)


def _result_path(job_id: str) -> Path:
    result = _job(job_id).snapshot().get('result') or {}
    path = Path(result.get('path') or '')
    if not result or not path.is_file():
        raise HTTPException(404, '压缩后的文件不存在')
    return path


@router.get('/{job_id}/file')
def file(job_id: str, request: Request, download: int = 0):
    path = _result_path(job_id)
    if download:
        return FileResponse(path, media_type='video/mp4', filename=path.name)
    return video_response(path, request, filename=path.name)


@router.post('/{job_id}/open-folder')
def open_folder(job_id: str):
    path = _result_path(job_id)
    desktop.open_folder(path.parent)
    return dict(path=str(path.parent))
