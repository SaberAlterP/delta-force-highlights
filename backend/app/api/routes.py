"""REST 接口：上传（分片）/ 识别 / 视频流（支持 Range）/ 导出 / 下载。"""
from __future__ import annotations

import mimetypes
import os
import shutil
import subprocess
import sys
import time
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse

from .. import config
from ..models import (
    AnalyzeRequest, CleanupRequest, ExportRequest, ExportResult, JobStatus,
    StorageDeleteRequest, StorageRestoreRequest, VideoMeta,
)
from ..services import archive, exporter, projects, video, workers
from ..services.media import video_response
from ..services.cache import cache
from ..services.parameters import DetectParams
from ..services.jobs import Job, jobs
from ..services.workflow import workflow

router = APIRouter(prefix="/api")


@router.get('/workflow')
def workflow_status():
    return workflow.status()


@router.post('/workflow/settings')
def workflow_settings(values: dict):
    try:
        return workflow.configure(values)
    except (ValueError, TypeError) as exc:
        raise HTTPException(422, str(exc))


_gpu_probe = {}


def _gpu_available():
    # 常驻服务不导入 torch；用一次性子进程探测并缓存结果。
    if 'value' not in _gpu_probe:
        try:
            out = subprocess.run([sys.executable, '-c', 'import torch;print(torch.cuda.is_available())'],
                                 capture_output=True, text=True, timeout=60,
                                 creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
            _gpu_probe['value'] = out.stdout.strip() == 'True'
        except (OSError, subprocess.SubprocessError):
            _gpu_probe['value'] = False
    return _gpu_probe['value']


@router.get('/workflow/environment')
def workflow_environment():
    from ..services import wegame
    settings = workflow.settings
    info = dict(wegame=wegame.describe(settings.wegame_db_dir), gpu=_gpu_available(),
                ffmpeg=bool(shutil.which('ffmpeg')))
    for name in ('watch_root', 'output_root'):
        value = getattr(settings, name)
        info[name] = dict(path=value, exists=bool(value) and Path(value).is_dir())
    return info


@router.post('/workflow/pick-folder')
def workflow_pick_folder(values: dict):
    """在本机弹出系统选择文件夹窗口（服务只监听 127.0.0.1）。"""
    script = ('import sys,tkinter as tk\nfrom tkinter import filedialog\n'
              'r=tk.Tk();r.withdraw();r.attributes("-topmost",True)\n'
              'print(filedialog.askdirectory(initialdir=sys.argv[1] or None,title=sys.argv[2]) or "")')
    try:
        out = subprocess.run([sys.executable, '-c', script, str(values.get('initial') or ''),
                              str(values.get('title') or '选择文件夹')],
                             capture_output=True, text=True, encoding='utf-8', timeout=600)
    except (OSError, subprocess.SubprocessError) as exc:
        raise HTTPException(422, f'无法打开选择窗口：{exc}')
    path = out.stdout.strip()
    return {'path': str(Path(path)) if path else ''}


@router.post('/workflow/retry/{record_id}')
def workflow_retry(record_id: str):
    try:
        workflow.retry(record_id)
        return {'ok': True}
    except (ValueError, OSError) as exc:
        raise HTTPException(422, str(exc))


@router.get('/workflow/{record_id}/file/{index}')
def workflow_file(record_id: str, index: int, request: Request):
    entry = next((r for r in workflow.status()['records'] if r['id'] == record_id), None)
    files = (entry.get('result') or {}).get('files', []) if entry else []
    if index < 0 or index >= len(files):
        raise HTTPException(404, '成片不存在')
    path = Path(files[index]['path'])
    if not path.is_file():
        raise HTTPException(404, '成片文件已不存在')
    return video_response(path, request, filename=path.name)


@router.get('/workflow/{record_id}/original')
def workflow_original(record_id: str, request: Request):
    entry=next((r for r in workflow.status()['records'] if r['id']==record_id),None)
    if not entry or not entry['original_available']:
        raise HTTPException(404,'整局原片已清理或不存在')
    path=workflow._source_path(entry)
    return video_response(path,request,filename=path.name)


@router.post('/workflow/open-folder')
def workflow_open_folder(values: dict):
    record_id=values.get('record_id')
    if record_id:
        entry=next((r for r in workflow.status()['records'] if r['id']==record_id),None)
        if not entry or not entry['archive_dir']:
            raise HTTPException(404,'这段录像尚未归档')
        path=Path(entry['archive_dir'])
        if path.resolve().parent!=Path(entry['archive_root']).resolve() or path.is_symlink():
            raise HTTPException(400,'非法归档目录')
    else:path=Path(workflow.settings.output_root)
    if not path.is_dir():raise HTTPException(404,'集锦文件夹尚未生成')
    if os.name=='nt':
        subprocess.Popen(['explorer.exe',str(path)],creationflags=subprocess.CREATE_NO_WINDOW)
    return dict(path=str(path))


@router.post('/workflow/notification-test')
def workflow_notification_test():
    from ..services import notifications
    return notifications.send('三角洲集锦通知测试','处理完成后会这样提醒你，点击即可查看本地网页。')


@router.post('/workflow/{record_id}/retain')
def workflow_retain_original(record_id: str):
    try:
        workflow.retain_original(record_id)
        return {'ok':True}
    except ValueError as exc:raise HTTPException(422,str(exc))


@router.post('/workflow/{record_id}/delete-original')
def workflow_delete_original(record_id: str):
    try:
        workflow.delete_original(record_id)
        return {'ok':True}
    except (ValueError,OSError) as exc:raise HTTPException(422,str(exc))


@router.post('/workflow/{record_id}/delete-bundle')
def workflow_delete_bundle(record_id: str):
    try:
        workflow.delete_bundle(record_id)
        return {'ok':True}
    except (ValueError,OSError) as exc:raise HTTPException(422,str(exc))


@router.post('/workflow/{record_id}/edit')
def workflow_edit(record_id: str, values: dict):
    row=workflow.recording(record_id)
    if not row:raise HTTPException(404,'归档不存在')
    try:
        project=projects.load(row)
        index=values.get('clip_index')
        marks=(row['result'] or {}).get('marks',[])
        if index is None:
            source_id='bundle_'+record_id
            filename=Path(row['path']).name
        else:
            files=(row['result'] or {}).get('files',[])
            if not isinstance(index,int) or not 0<=index<len(files):raise ValueError('高光不存在')
            item=files[index]
            source_id=f'bundle_{record_id}_clip_{item["sha256"][:12]}'
            filename=Path(item['path']).name
            marks=[dict(m,time=round(m['time']-item['start'],3)) for m in marks
                   if item['start']<=m['time']<=item['end']]
        path=workflow.resolve_project_video(source_id)
        if path is None:raise HTTPException(404,'这份素材已清理或仍在整理，无法继续剪辑')
        meta=video.probe(path)
        saved=project['sources'].get(source_id)
        return dict(video=dict(meta,upload_id=source_id,filename=filename,workflow_id=record_id),
                    kills=saved['kills'] if saved else marks,project_saved=saved is not None,
                    player_id=workflow.settings.player_id)
    except (OSError,ValueError,KeyError) as exc:raise HTTPException(422,str(exc))


@router.post('/workflow/{record_id}/project')
def workflow_save_project(record_id: str, values: dict):
    try:
        with workflow._lock:
            row=workflow.recording(record_id)
            if not row:raise ValueError('归档不存在')
            count=projects.save_marks(row,values.get('source_id',''),values.get('kills',[]))
        return dict(saved=count)
    except (OSError,ValueError,KeyError,TypeError) as exc:raise HTTPException(422,str(exc))


@router.get('/workflow/{record_id}/manual/{export_id}/{name}')
def workflow_manual_file(record_id: str,export_id: str,name: str,request: Request):
    try:
        row=workflow.recording(record_id)
        entry=next((item for item in projects.manual_exports(row) if item['id']==export_id),None)
        item=next((item for item in entry['files'] if item['name']==name),None) if entry else None
        if not item:raise ValueError('手动剪辑不存在')
        base=projects.directory(row).resolve()
        path=base/item['path']
        if path.is_symlink() or not path.resolve().is_relative_to(base) or not path.is_file():
            raise ValueError('手动剪辑不存在')
        return video_response(path,request,filename=path.name)
    except (OSError,ValueError):raise HTTPException(404,'手动剪辑不存在')


@router.post('/workflow/cache/cleanup')
def workflow_cache_cleanup():
    from ..services.workflow import _closed_by_recorder
    return cache.cleanup(closed=_closed_by_recorder,busy=jobs.has_active(),
                         active_workers=workers.active_directories())

# upload_id -> {"path": Path, "filename": str, "meta": dict}
UPLOADS: dict[str, dict] = {}


# ----------------------------------------------------------------------------
# 上传（分片）
# ----------------------------------------------------------------------------
@router.post("/upload/init")
def upload_init(filename: str = Form(...), total_chunks: int = Form(...)):
    upload_id = uuid.uuid4().hex
    chunk_dir = config.CHUNK_DIR / upload_id
    chunk_dir.mkdir(parents=True, exist_ok=True)
    UPLOADS[upload_id] = {
        "filename": filename,
        "total_chunks": total_chunks,
        "chunk_dir": chunk_dir,
        "path": None,
        "meta": None,
    }
    return {"upload_id": upload_id}


@router.post("/upload/chunk")
async def upload_chunk(
    upload_id: str = Form(...),
    index: int = Form(...),
    chunk: UploadFile = File(...),
):
    info = UPLOADS.get(upload_id)
    if not info:
        raise HTTPException(404, "upload_id 不存在，请先调用 /upload/init")
    chunk_path = info["chunk_dir"] / f"{index:06d}.part"
    with chunk_path.open("wb") as f:
        while True:
            data = await chunk.read(1024 * 1024)
            if not data:
                break
            f.write(data)
    return {"ok": True, "index": index}


@router.post("/upload/complete", response_model=VideoMeta)
def upload_complete(upload_id: str = Form(...)):
    info = UPLOADS.get(upload_id)
    if not info:
        raise HTTPException(404, "upload_id 不存在")

    chunk_dir: Path = info["chunk_dir"]
    parts = sorted(chunk_dir.glob("*.part"))
    if not parts:
        raise HTTPException(400, "没有收到任何分片")

    ext = Path(info["filename"]).suffix or ".mp4"
    final_path = config.UPLOAD_DIR / f"{upload_id}{ext}"
    with final_path.open("wb") as out:
        for part in parts:
            with part.open("rb") as pf:
                shutil.copyfileobj(pf, out, length=4 * 1024 * 1024)

    shutil.rmtree(chunk_dir, ignore_errors=True)

    meta = video.probe(final_path)
    info["path"] = final_path
    info["meta"] = meta

    return VideoMeta(
        upload_id=upload_id,
        filename=info["filename"],
        duration=meta["duration"],
        width=meta["width"],
        height=meta["height"],
        fps=meta["fps"],
        size_bytes=meta["size_bytes"],
    )


def _find_upload_path(upload_id: str) -> Path | None:
    if projects.SOURCE_ID.fullmatch(upload_id):
        try:path=workflow.resolve_project_video(upload_id)
        except (OSError,ValueError):return None
        if path:cache.touch(path)
        return path
    info = UPLOADS.get(upload_id)
    if info and info.get("path") and Path(info["path"]).exists():
        cache.touch(info['path'])
        return Path(info["path"])
    # 回退：进程重启后按文件名匹配
    matches = list(config.UPLOAD_DIR.glob(f"{upload_id}.*"))
    path=matches[0] if matches else cache.alias(upload_id)
    if path:cache.touch(path)
    return path


# ----------------------------------------------------------------------------
# 视频流（支持 Range，video.js 才能拖动进度）
# ----------------------------------------------------------------------------
@router.get("/video/{upload_id}")
def stream_video(upload_id: str, request: Request):
    path = _find_upload_path(upload_id)
    if not path:
        raise HTTPException(404, "视频不存在")
    # 分段读取后立即关闭文件，见 services/media.py。
    return video_response(path, request)


# ----------------------------------------------------------------------------
# 识别
# ----------------------------------------------------------------------------
@router.post("/analyze", response_model=ExportResult)
def start_analyze(req: AnalyzeRequest):
    path = _find_upload_path(req.upload_id)
    if not path:
        raise HTTPException(404, "视频不存在，请先上传")
    params = DetectParams(
        player_id=req.player_id or "",
        sample_fps=req.sample_fps or config.DETECT.sample_fps,
        debounce_seconds=req.debounce_seconds or config.DETECT.debounce_seconds,
        id_match_ratio=req.id_match_ratio or config.DETECT.id_match_ratio,
        id_region=(req.id_region.x1, req.id_region.y1, req.id_region.x2, req.id_region.y2)
        if req.id_region else None,
        prompt_region=(req.prompt_region.x1, req.prompt_region.y1,
                       req.prompt_region.x2, req.prompt_region.y2)
        if req.prompt_region else None,
        knockdown_keywords=req.knockdown_keywords or None,
    )

    def task(job: Job):
        def cb(p: float, msg: str):
            job.update(progress=p, message=msg)
        kills = workers.analyze_isolated(
            path, params, progress_cb=cb, cancel_cb=job.is_cancelled
        )
        return {"kills": kills}

    job = jobs.submit("analyze", task)
    return ExportResult(job_id=job.job_id)


@router.get("/analyze/{job_id}", response_model=JobStatus)
def analyze_status(job_id: str):
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(404, "任务不存在")
    snap = job.snapshot()
    kills = (snap.get("result") or {}).get("kills", []) if snap.get("result") else []
    return JobStatus(
        job_id=job_id,
        state=snap["state"],
        progress=snap["progress"],
        message=snap["message"],
        kills=kills,
        error=snap.get("error"),
    )


# ----------------------------------------------------------------------------
# 导出
# ----------------------------------------------------------------------------
@router.post("/export", response_model=ExportResult)
def start_export(req: ExportRequest):
    if not req.clips:
        raise HTTPException(400, "没有选择任何片段")

    specs = []
    for c in req.clips:
        src = _find_upload_path(c.upload_id)
        if not src:
            raise HTTPException(404, f"视频不存在: {c.upload_id}")
        d = c.model_dump()
        d["src"] = str(src)
        specs.append(d)

    def task(job: Job):
        def cb(p: float, msg: str):
            job.update(progress=p, message=msg)
        matches=[projects.SOURCE_ID.fullmatch(c.upload_id) for c in req.clips]
        record_id=matches[0][1] if matches[0] and all(m and m[1]==matches[0][1] for m in matches) else None
        row=workflow.recording(record_id) if record_id else None
        root=projects.directory(row)/'手动剪辑' if row else None
        result=exporter.export_clips(specs, merge=req.merge,accurate=req.accurate,
            stretch_169=req.stretch_169,progress_cb=cb,cancel_cb=job.is_cancelled,output_root=root)
        if row:
            files=[]
            for spec,item in zip(specs,result['files']):
                path=Path(item['path'])
                workflow._verify_export(path,spec['end']-spec['start'],req.stretch_169)
                files.append(dict(name=path.name,path=path.relative_to(projects.directory(row)).as_posix()))
            if result['merged']:
                path=Path(result['merged'])
                files.append(dict(name=path.name,path=path.relative_to(projects.directory(row)).as_posix()))
            with workflow._lock:
                project=projects.load(row)
                project['manual_exports'].append(dict(id=Path(result['dir']).name,
                    created_at=time.time(),files=files,stretch_169=req.stretch_169))
                projects.save(row,project)
        return result

    job = jobs.submit("export", task)
    return ExportResult(job_id=job.job_id)


@router.get("/export/{job_id}")
def export_status(job_id: str):
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(404, "任务不存在")
    snap = job.snapshot()
    result = snap.get("result") or {}
    files = []
    for f in result.get("files", []):
        files.append({"name": f["name"]})
    return {
        "job_id": job_id,
        "state": snap["state"],
        "progress": snap["progress"],
        "message": snap["message"],
        "error": snap.get("error"),
        "files": files,
        "has_merged": bool(result.get("merged")),
    }


def _export_dir(job_id: str) -> Path:
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(404, "任务不存在")
    result = job.snapshot().get("result") or {}
    d = result.get("dir")
    if not d:
        raise HTTPException(404, "导出尚未完成")
    return Path(d)


@router.get("/export/{job_id}/file/{name}")
def download_file(job_id: str, name: str):
    out_dir = _export_dir(job_id)
    target = (out_dir / name).resolve()
    if out_dir.resolve() not in target.parents or not target.exists():
        raise HTTPException(404, "文件不存在")
    return FileResponse(target, media_type="video/mp4", filename=name)


@router.get("/export/{job_id}/merged")
def download_merged(job_id: str):
    job = jobs.get(job_id)
    result = (job.snapshot().get("result") or {}) if job else {}
    merged = result.get("merged")
    if not merged or not Path(merged).exists():
        raise HTTPException(404, "没有合并文件")
    return FileResponse(merged, media_type="video/mp4", filename="highlight_merged.mp4")


@router.get("/export/{job_id}/zip")
def download_zip(job_id: str):
    out_dir = _export_dir(job_id)
    zip_path = out_dir / "clips.zip"
    if not zip_path.exists():
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_STORED) as zf:
            for mp4 in sorted(out_dir.glob("*.mp4")):
                zf.write(mp4, mp4.name)
    return FileResponse(zip_path, media_type="application/zip", filename="clips.zip")


# ----------------------------------------------------------------------------
# 存储 / 缓存管理
# ----------------------------------------------------------------------------
_STORAGE_DIRS = {
    "uploads": config.UPLOAD_DIR,
    "clips": config.CLIP_DIR,
    "chunks": config.CHUNK_DIR,
    "tmp": config.TMP_DIR,
}

_BROWSABLE_STORAGE = {"uploads", "clips"}


def _dir_stat(path: Path) -> dict:
    total = 0
    count = 0
    if path.exists():
        for f in path.rglob("*"):
            if f.is_file():
                try:
                    total += f.stat().st_size
                    count += 1
                except OSError:
                    pass
    return {"bytes": total, "files": count}


def _resolve_storage_file(target: str, relative_path: str) -> tuple[Path, Path]:
    """Resolve a client supplied relative path without allowing directory escape."""
    if target not in _BROWSABLE_STORAGE:
        raise HTTPException(400, "仅支持浏览上传视频和导出片段")
    base = _STORAGE_DIRS[target].resolve()
    candidate = (base / relative_path).resolve()
    try:
        candidate.relative_to(base)
    except ValueError:
        raise HTTPException(400, "非法缓存路径")
    if not candidate.is_file():
        raise HTTPException(404, "缓存文件不存在")
    return base, candidate


def _storage_entry(target: str, base: Path, path: Path) -> dict:
    stat = path.stat()
    relative = path.relative_to(base).as_posix()
    media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    upload_id = path.stem if target == "uploads" else None
    original_name = None
    if upload_id:
        original_name = (UPLOADS.get(upload_id) or {}).get("filename")
    parts = Path(relative).parts
    return {
        "target": target,
        "path": relative,
        "name": original_name or path.name,
        "stored_name": path.name,
        "size_bytes": stat.st_size,
        "modified_at": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
        "media_type": media_type,
        "previewable": media_type.startswith("video/"),
        "upload_id": upload_id,
        "job_id": parts[0] if target == "clips" and len(parts) > 1 else None,
    }


@router.get("/storage/usage")
def storage_usage():
    return {k: _dir_stat(d) for k, d in _STORAGE_DIRS.items()}


@router.get("/storage/files")
def storage_files(target: str):
    if target not in _BROWSABLE_STORAGE:
        raise HTTPException(400, "仅支持浏览上传视频和导出片段")
    base = _STORAGE_DIRS[target].resolve()
    files = []
    if base.exists():
        for path in base.rglob("*"):
            if path.is_file():
                try:
                    files.append(_storage_entry(target, base, path))
                except OSError:
                    continue
    files.sort(key=lambda item: item["modified_at"], reverse=True)
    return {"target": target, "files": files}


@router.post("/storage/restore-upload", response_model=VideoMeta)
def restore_cached_upload(req: StorageRestoreRequest):
    """把已存在的上传缓存重新注册到录像库，不复制或重新上传文件。"""
    _, path = _resolve_storage_file("uploads", req.path)
    upload_id = path.stem
    if not upload_id:
        raise HTTPException(400, "缓存文件名无效")

    try:
        meta = video.probe(path)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(422, f"无法读取缓存视频信息：{exc}")

    requested_name = Path(req.filename).name.strip() if req.filename else ""
    existing_name = (UPLOADS.get(upload_id) or {}).get("filename", "")
    filename = requested_name or existing_name or path.name
    UPLOADS[upload_id] = {
        "filename": filename,
        "total_chunks": 0,
        "chunk_dir": None,
        "path": path,
        "meta": meta,
    }
    return VideoMeta(
        upload_id=upload_id,
        filename=filename,
        duration=meta["duration"],
        width=meta["width"],
        height=meta["height"],
        fps=meta["fps"],
        size_bytes=meta["size_bytes"],
    )


@router.get("/storage/file/{target}/{relative_path:path}")
def preview_storage_file(target: str, relative_path: str):
    _, path = _resolve_storage_file(target, relative_path)
    cache.touch(path)
    media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return FileResponse(path, media_type=media_type)


@router.post("/storage/delete")
def delete_storage_file(req: StorageDeleteRequest):
    _, path = _resolve_storage_file(req.target, req.path)
    size = path.stat().st_size
    upload_id = path.stem if req.target == "uploads" else None
    try:
        path.unlink()
    except OSError as exc:
        raise HTTPException(409, f"文件正在使用，暂时无法删除：{exc}")

    # Remove empty export job directories after their final artifact is deleted.
    if req.target == "clips":
        parent = path.parent
        clip_root = _STORAGE_DIRS["clips"].resolve()
        while parent != clip_root and parent.is_relative_to(clip_root):
            try:
                parent.rmdir()
            except OSError:
                break
            parent = parent.parent
    elif upload_id:
        UPLOADS.pop(upload_id, None)

    return {
        "removed": {"bytes": size, "files": 1, "upload_id": upload_id},
        "usage": {k: _dir_stat(d) for k, d in _STORAGE_DIRS.items()},
    }


@router.post("/storage/cleanup")
def storage_cleanup(req: CleanupRequest):
    invalid = sorted(set(req.targets) - set(_STORAGE_DIRS))
    if invalid:
        raise HTTPException(400, f"未知缓存类型：{', '.join(invalid)}")

    targets = list(dict.fromkeys(req.targets))
    before = {target: _dir_stat(_STORAGE_DIRS[target]) for target in targets}
    cancelled_jobs = {"requested": 0, "remaining": 0}
    if req.force:
        cancelled_jobs = jobs.cancel_all(wait_seconds=6.0)

    attempts = 8 if req.force else 1
    for attempt in range(attempts):
        for target in targets:
            directory = _STORAGE_DIRS[target]
            if not directory.exists():
                continue
            try:
                items = list(directory.iterdir())
            except OSError:
                continue
            for item in items:
                try:
                    if item.is_dir():
                        shutil.rmtree(item)
                    else:
                        item.unlink()
                except OSError:
                    # Windows 文件句柄释放存在一个很短的延迟；强制模式会重试。
                    continue
        if all(_dir_stat(_STORAGE_DIRS[target])["files"] == 0 for target in targets):
            break
        if attempt + 1 < attempts:
            time.sleep(0.2)

    after = {target: _dir_stat(_STORAGE_DIRS[target]) for target in targets}
    removed_bytes = sum(before[t]["bytes"] - after[t]["bytes"] for t in targets)
    removed_files = sum(before[t]["files"] - after[t]["files"] for t in targets)
    failed = sum(after[t]["files"] for t in targets)

    if "uploads" in targets:
        UPLOADS.clear()

    return {
        "removed": {"bytes": removed_bytes, "files": removed_files, "failed": failed},
        "cancelled_jobs": cancelled_jobs,
        "usage": {k: _dir_stat(d) for k, d in _STORAGE_DIRS.items()},
    }
