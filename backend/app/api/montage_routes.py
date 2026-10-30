"""集锦剪辑接口：工程、素材、歌曲、编排、出片、助手。"""
from __future__ import annotations

import mimetypes
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse

from ..services import montage_studio as studio
from ..services.jobs import JobManager
from ..services.media import video_response

router = APIRouter(prefix='/api/montage')
jobs = JobManager(max_workers=2)       # 出片很久，不占识别 / 导出的任务位


def _project(pid: str) -> dict:
    try:
        return studio.load(pid)
    except KeyError:
        raise HTTPException(404, '工程不存在')


def _err(exc: Exception):
    raise HTTPException(422, str(exc))


@router.get('/presets')
def presets():
    return studio.presets()


@router.get('/settings')
def get_settings():
    return studio.public_settings()


@router.post('/settings')
def set_settings(values: dict):
    return studio.save_settings(values)


@router.get('/default-folder')
def default_folder():
    return {'path': studio._output_root()}


@router.post('/scan')
def scan(values: dict):
    try:
        return studio.scan_folder(str(values.get('folder') or ''))
    except (ValueError, OSError) as exc:
        _err(exc)


@router.get('/file')
def media_file(path: str, request: Request):
    try:
        p = studio.allowed(path)
    except PermissionError as exc:
        raise HTTPException(403, str(exc))
    media = mimetypes.guess_type(p.name)[0] or 'video/mp4'
    return video_response(p, request, media_type=media)


@router.get('/thumb')
def thumb(path: str, t: float = 1.0):
    try:
        return FileResponse(studio.thumbnail(path, t), media_type='image/jpeg', headers={'Cache-Control': 'max-age=86400'})
    except PermissionError as exc:
        raise HTTPException(403, str(exc))
    except (FileNotFoundError, OSError) as exc:
        raise HTTPException(404, str(exc))


@router.post('/bumpers/{kind}')
def upload_bumper(kind: str, file: UploadFile = File(...)):
    try:
        return studio.save_bumper(kind, file.filename or 'video.mp4', iter(lambda: file.file.read(4 << 20), b''))
    except (ValueError, OSError) as exc:
        _err(exc)


# ------------------------------------------------------------------ 工程
@router.get('/projects')
def projects():
    return studio.list_projects()


@router.post('/projects')
def create_project(values: dict):
    return studio.public(studio.create(str(values.get('name') or ''), str(values.get('folder') or '')))


@router.get('/projects/{pid}')
def get_project(pid: str):
    return studio.public(_project(pid))


@router.patch('/projects/{pid}')
def update_project(pid: str, values: dict):
    _project(pid)
    try:
        return studio.public(studio.update(pid, values))
    except (ValueError, TypeError) as exc:
        _err(exc)


@router.delete('/projects/{pid}')
def delete_project(pid: str):
    _project(pid)
    studio.delete(pid)
    return {'ok': True}


@router.post('/projects/{pid}/song')
def upload_song(pid: str, file: UploadFile = File(...)):
    _project(pid)
    name = Path(file.filename or 'song.mp3').name
    if Path(name).suffix.lower() not in studio.AUDIO_EXT:
        raise HTTPException(422, '请选择 mp3 / flac / wav / m4a 歌曲')
    dest = studio._pdir(pid) / ('song_src' + Path(name).suffix.lower())
    with dest.open('wb') as f:
        for chunk in iter(lambda: file.file.read(4 << 20), b''):
            f.write(chunk)
    job = jobs.submit('montage_song', lambda job: studio.analyze_song(pid, dest, name, job))
    return {'job_id': job.job_id}


@router.get('/projects/{pid}/song/audio')
def song_audio(pid: str, request: Request):
    _project(pid)
    try:
        return video_response(studio.song_path(pid), request, media_type='audio/wav')
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc))


@router.post('/projects/{pid}/plan')
def plan(pid: str):
    _project(pid)
    job = jobs.submit('montage_plan', lambda job: studio.auto_plan(pid, job))
    return {'job_id': job.job_id}


@router.post('/projects/{pid}/ops')
def ops(pid: str, values: dict):
    _project(pid)
    try:
        studio.apply_ops(pid, list(values.get('ops') or []))
        return studio.public(studio.load(pid))
    except (ValueError, KeyError, TypeError) as exc:
        _err(exc)


@router.post('/projects/{pid}/render')
def render(pid: str):
    _project(pid)
    job = jobs.submit('montage_render', lambda job: studio.render(pid, job))
    return {'job_id': job.job_id}


@router.post('/jobs/{job_id}/cancel')
def cancel(job_id: str):
    job = jobs.get(job_id)
    if job:
        job.cancel()
    return {'ok': True}


@router.get('/jobs/{job_id}')
def job_status(job_id: str):
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(404, '任务不存在')
    return job.snapshot()


# ------------------------------------------------------------------ 助手
@router.post('/projects/{pid}/agent')
def agent_chat(pid: str, values: dict):
    from ..services import montage_agent
    _project(pid)
    text = str(values.get('text') or '').strip()
    if not text:
        raise HTTPException(422, '说点什么吧')
    try:
        return montage_agent.chat(pid, text)
    except PermissionError as exc:
        raise HTTPException(401, str(exc))
    except ImportError:
        raise HTTPException(422, '后端缺少 anthropic 包：在 backend 目录运行 .venv\\Scripts\\pip install anthropic')
    except (RuntimeError, ValueError) as exc:
        _err(exc)


@router.post('/projects/{pid}/agent/reset')
def agent_reset(pid: str):
    from ..services import montage_agent
    _project(pid)
    return montage_agent.reset(pid)
