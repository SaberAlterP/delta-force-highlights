"""本地新录像队列。原位分析，不上传/复制整局；只有验证过的成片才能触发保留期。"""
from __future__ import annotations

from concurrent.futures import CancelledError
from contextlib import contextmanager
from dataclasses import asdict, dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import threading
import time
import uuid

from .. import config
from . import archive, exporter, video, workers, notifications, projects, wegame
from .cache import cache
from .jobs import jobs
from .parameters import DetectParams
from .highlights import confirmed_events, select_highlights


@dataclass
class WorkflowSettings:
    enabled: bool = False
    watch_root: str = ''
    output_root: str = ''
    player_id: str = ''
    window_seconds: float = 90
    min_operators: int = 2
    pre_seconds: float = 20
    post_seconds: float = 5
    stable_seconds: float = 120
    poll_seconds: float = 15
    retention_days: float = 7
    delete_after_retention: bool = False
    organize_originals: bool = True
    auto_clean_cache: bool = True
    notify_on_complete: bool = False
    stretch_169: bool = True
    prefer_official_events: bool = True
    use_gpu: bool = True
    # 什么时候处理新录像：idle = 没在玩游戏时（默认）；auto = 录完立即；manual = 只在网页里点开始
    process_mode: str = 'idle'
    pause_on_fullscreen: bool = True     # 任何全屏程序（浏览器除外）也算在玩
    extra_game_processes: str = ''       # 额外的游戏进程名，逗号分隔
    idle_wait_minutes: float = 3         # 游戏关掉后再等几分钟才开始
    wegame_db_dir: str = ''          # 留空 = 自动使用 %APPDATA%\icreate-pc-df\wonderfulDb

    @property
    def configured(self):
        return bool(self.player_id.strip() and self.watch_root and self.output_root)

    def validate(self):
        # 首次使用允许留空；开启自动监控前三项必须填好。
        if self.enabled and not self.player_id.strip():
            raise ValueError('开启自动监控前请先填写游戏 ID')
        if self.enabled and not (self.watch_root and self.output_root):
            raise ValueError('开启自动监控前请先填写录像目录和集锦目录')
        for name in ('watch_root', 'output_root', 'wegame_db_dir'):
            if getattr(self, name) and not Path(getattr(self, name)).is_absolute():
                raise ValueError('目录必须填写完整路径，例如 D:\\集锦')
        if self.watch_root and self.output_root:
            root, output = Path(self.watch_root).resolve(), Path(self.output_root).resolve()
            if root == output or output.is_relative_to(root) or root.is_relative_to(output):
                raise ValueError('集锦目录和录像目录不能相同，也不能互相包含')
        if self.process_mode not in ('idle', 'auto', 'manual'):
            raise ValueError('处理时机只能是 idle / auto / manual')
        if not 0 <= self.idle_wait_minutes <= 120:
            raise ValueError('游戏结束后的等待时间应在 0 到 120 分钟之间')
        if not (1 <= self.window_seconds <= 600 and 2 <= self.min_operators <= 20):
            raise ValueError('多杀时间窗或人数无效')
        if not (0 <= self.pre_seconds <= 300 and 0 <= self.post_seconds <= 300):
            raise ValueError('片段前后时长无效')
        if self.stable_seconds < 60 or self.poll_seconds < 5 or self.retention_days < 1:
            raise ValueError('等待写入完成至少 60 秒，保留整局至少 1 天')
        return self


def _fingerprint(path: Path) -> str:
    stat = path.stat()
    return f'{stat.st_size}:{stat.st_mtime_ns}'


def _digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as stream:
        h.update(stream.read(65536))
        stream.seek(max(0, path.stat().st_size-65536))
        h.update(stream.read(65536))
    return h.hexdigest()


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def _closed_by_recorder(path: Path) -> bool:
    """Windows 独占读探测：仍被录制器持有的文件不进入识别/清理。"""
    if os.name != 'nt':
        return True
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                  wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD,
                                  wintypes.HANDLE]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.CreateFileW(str(path), 0x80000000, 0, None, 3, 0x80, None)
    if handle == wintypes.HANDLE(-1).value:
        return False
    kernel.CloseHandle(handle)
    return True


class WorkflowService:
    def __init__(self, state_dir: Path | None = None):
        self.state_dir = state_dir or config.STORAGE_DIR / 'workflow'
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.settings_path = self.state_dir / 'settings.json'
        self.db_path = self.state_dir / 'queue.sqlite3'
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread = None
        self._active = None
        self.last_error = ''
        self.paused = ''          # 非空时说明为什么暂停处理（例如正在玩游戏）
        self._last_game = 0.      # 最近一次检测到游戏的时间
        self._yielded = False     # 本次识别是否因游戏开始而中断
        self._last_cache_cleanup = 0
        self.settings = WorkflowSettings()
        if self.settings_path.exists():
            self.settings = WorkflowSettings(**json.loads(
                self.settings_path.read_text(encoding='utf-8-sig'))).validate()
        with self._db() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS recordings (
                id TEXT PRIMARY KEY, path TEXT NOT NULL, fingerprint TEXT NOT NULL,
                status TEXT NOT NULL, discovered REAL NOT NULL, stable_since REAL NOT NULL,
                completed REAL, cleanup_after REAL, digest TEXT, result TEXT, error TEXT,
                allow_cleanup INTEGER NOT NULL DEFAULT 1,
                UNIQUE(path, fingerprint))''')
            db.execute('CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT)')
            columns={r['name'] for r in db.execute('PRAGMA table_info(recordings)')}
            for name,kind in dict(archive_dir='TEXT',archive_root='TEXT',archive_path='TEXT',
                archive_sha256='TEXT',archive_fingerprint='TEXT',retained_since='REAL',
                notified='REAL',notification_error='TEXT').items():
                if name not in columns:
                    db.execute(f'ALTER TABLE recordings ADD COLUMN {name} {kind}')

    @contextmanager
    def _db(self):
        db = sqlite3.connect(self.db_path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def configure(self, values: dict):
        with self._lock:
            updated = WorkflowSettings(**(asdict(self.settings) | values)).validate()
            self.settings_path.write_text(json.dumps(asdict(updated), ensure_ascii=False,
                                                     indent=2), encoding='utf-8')
            self.settings = updated
        return asdict(updated)

    def _sources(self):
        if not self.settings.watch_root:
            raise FileNotFoundError('尚未设置录像目录')
        root = Path(self.settings.watch_root).resolve()
        if not root.is_dir():
            raise FileNotFoundError(f'监控目录不存在：{root}')
        # 实测官方目录：根目录/账号目录/record/record日期-时间.mp4。
        # 不递归猜测数字资源目录，更不把 edit/缩略图/模板纳入队列。
        paths = list(root.glob('record*.mp4'))
        paths += list(root.glob('*/record/record*.mp4'))
        for path in sorted(set(paths)):
            if (re.fullmatch(r'record\d{8}-\d{6}\.mp4', path.name, re.I)
                and path.resolve().is_relative_to(root) and not path.is_symlink()):
                yield path.resolve()

    def discover(self, now: float | None = None) -> int:
        now = time.time() if now is None else now
        with self._lock, self._db() as db:
            sources = list(self._sources())
            key = 'initialized:' + str(Path(self.settings.watch_root).resolve())
            first = db.execute('SELECT 1 FROM metadata WHERE key=?', (key,)).fetchone() is None
            count = 0
            for path in sources:
                try:
                    fp = _fingerprint(path)
                except OSError:
                    continue
                exists = db.execute('SELECT 1 FROM recordings WHERE path=? AND fingerprint=?',
                                    (str(path), fp)).fetchone()
                if exists:
                    continue
                # 正在写入的同名新录像更新就绪计时，而不是每次写入创建一个任务。
                previous = db.execute("SELECT id FROM recordings WHERE path=? AND status='waiting'",
                                      (str(path),)).fetchone()
                if previous:
                    db.execute('UPDATE recordings SET fingerprint=?, stable_since=? WHERE id=?',
                               (fp, now, previous['id']))
                else:
                    db.execute('INSERT INTO recordings (id,path,fingerprint,status,discovered,stable_since) '
                               'VALUES (?,?,?,?,?,?)',
                               (uuid.uuid4().hex, str(path), fp,
                                'historical' if first else ('manual' if self.settings.process_mode == 'manual' else 'waiting'), now, now))
                count += 1
            if first:
                db.execute('INSERT INTO metadata VALUES (?,?)', (key, str(now)))
            return count

    def _update(self, record_id: str, **values):
        with self._db() as db:
            db.execute('UPDATE recordings SET ' + ','.join(f'{k}=?' for k in values) + ' WHERE id=?',
                       (*values.values(), record_id))

    def status(self):
        with self._db() as db:
            records = [dict(r) for r in db.execute(
                'SELECT * FROM recordings ORDER BY discovered DESC LIMIT 100')]
        for item in records:
            item['result'] = json.loads(item['result']) if item['result'] else None
            item['original_available'] = self._source_path(item).is_file() and item['status'] != 'deleted'
            item['manual_exports']=[]
            if item['archive_dir']:
                try:item['manual_exports']=projects.manual_exports(item)
                except (OSError,ValueError):pass
        return dict(settings=asdict(self.settings), records=records,
                    active=self._active, paused=self.paused, running=bool(self._thread and self._thread.is_alive()),
                    error=self.last_error, cache=cache.last)

    def recording(self,record_id):
        with self._db() as db:
            row=db.execute('SELECT * FROM recordings WHERE id=?',(record_id,)).fetchone()
        if not row:return None
        item=dict(row)
        item['result']=json.loads(item['result']) if item['result'] else None
        return item

    def resolve_project_video(self,source_id):
        match=projects.SOURCE_ID.fullmatch(source_id)
        if not match:return None
        row=self.recording(match[1])
        if not row:return None
        base=projects.directory(row).resolve()
        if match[2]:
            files=(row['result'] or {}).get('files',[])
            item=next((item for item in files if item.get('sha256','').startswith(match[2])),None)
            if not item:return None
            path=Path(item['path'])
        else:
            if not row['archive_path']:return None
            path=Path(row['archive_path'])
        if path.is_file() and not path.is_symlink() and path.resolve().is_relative_to(base):return path
        return None

    @staticmethod
    def _source_path(row):
        # 中断可能发生在跨盘复制完成之后；E 仍在时优先完成移除来源的步骤。
        path=Path(row['path'])
        return path if path.exists() or not row['archive_path'] else Path(row['archive_path'])

    def process_next(self, now: float | None = None):
        now = time.time() if now is None else now
        with self._lock, self._db() as db:
            row = None
            for candidate in db.execute("SELECT * FROM recordings WHERE status='waiting' AND stable_since<=? "
                                        'ORDER BY discovered', (now-self.settings.stable_seconds,)).fetchall():
                path = self._source_path(candidate)
                if not path.exists():
                    db.execute("UPDATE recordings SET status='missing',error='原片已不在原路径' WHERE id=?",
                               (candidate['id'],))
                    continue
                expected=(candidate['archive_fingerprint'] if str(path)==candidate['archive_path']
                          else candidate['fingerprint'])
                if _fingerprint(path) == expected and _closed_by_recorder(path):
                    row = dict(candidate)
                    break
            if row is None:
                return
            source = self._source_path(row)
            source_fp=_fingerprint(source)
            settings = WorkflowSettings(**asdict(self.settings))
            db.execute("UPDATE recordings SET status='processing' WHERE id=? AND status='waiting'",
                       (row['id'],))
            self._active = dict(id=row['id'], path=str(source), progress=0., message='读取录像信息')
            self._yielded = False
        try:
            meta = video.probe(source)
            if meta['duration'] <= 0 or meta['width'] <= 0 or meta['height'] <= 0:
                raise ValueError('录像尚未完成或没有视频轨')
            before_digest = _digest(source)
            previous = json.loads(row['result']) if row['result'] else {}
            source_identity = dict(path=str(Path(row['path']).resolve()), fingerprint=row['fingerprint'])
            source_identity['digest']=before_digest
            analysis_params=dict(player_id=settings.player_id,detector_version=config.DETECTOR_VERSION)
            native=(wegame.index_for(settings.wegame_db_dir).find(row['path'],settings.player_id)
                    if settings.prefer_official_events else None)
            if native:
                if abs(native['duration']-meta['duration'])>3:
                    raise ValueError('官方事件与当前录像时长不匹配，保留原片等待复核')
                analysis_params['official_signature']=native['signature']
                analysis_params['official_version']=wegame.VERSION
            if previous.get('source')==source_identity and previous.get('analysis_params')==analysis_params:
                marks=previous['marks']
                self._progress(.94,'复用已完成的识别，应用当前集锦规则')
            else:
                if native:
                    self._progress(.01,'已读取官方时刻名称与时间，仅核对击杀点附近的干员身份')
                    observations=self._analyze_source(source,settings,
                        scan_windows=wegame.verification_windows(native,meta['duration'])) if native['kill_points'] else []
                    marks=wegame.verified_marks(native,observations)
                else:
                    marks = self._analyze_source(source, settings)
            if self._stop.is_set():
                raise CancelledError()
            if _fingerprint(source) != source_fp or _digest(source) != before_digest:
                raise RuntimeError('识别期间原片发生变化，保留原片并等待人工检查')
            highlights = select_highlights(marks, meta['duration'],
                window=settings.window_seconds, minimum=settings.min_operators,
                pre=settings.pre_seconds, post=settings.post_seconds)
            reusable = (previous.get('exports', previous.get('files', []))
                        if previous.get('source') == source_identity else [])
            result = dict(detector_version=config.DETECTOR_VERSION, source=source_identity, marks=marks,
                          analysis_params=analysis_params, highlights=highlights, files=[],
                          export_profile=dict(stretch_169=settings.stretch_169),
                          exports=reusable, meta=meta,
                          summary=dict(confirmed_kills=len(confirmed_events(marks)),
                                       has_highlights=bool(highlights),window_seconds=settings.window_seconds,
                                       review_candidates=sum(bool(m.get('review_required',True)) for m in marks)))
            if native:
                result['official_events']={k:v for k,v in native.items() if k!='marks'}
                result['summary'].update(official_kills=native['official_kills'],
                    kill_points=native['kill_points'],loot_points=native['loot_points'])
            if not highlights and not settings.organize_originals:
                self._update(row['id'], status='no_highlights', result=json.dumps(result, ensure_ascii=False),
                             completed=time.time(), error='没有确认的多杀片段，原片保留')
                return
            out_dir = (self._prepare_bundle(row,result,settings) if settings.organize_originals else
                Path(settings.output_root) / f'{source.stem}_{row["id"][:8]}_{uuid.uuid4().hex[:6]}')
            if not source.exists() and row.get('archive_path'):
                source=Path(row['archive_path']);source_fp=_fingerprint(source)
            self._update(row['id'],result=json.dumps(result,ensure_ascii=False))
            exported_new = False
            export_cache = {item['path']: item for item in reusable}
            for i, clip in enumerate(highlights):
                self._progress(.95, f'导出并验证高光 {i+1}/{len(highlights)}')
                reused = self._reuse_export(reusable, clip, Path(settings.output_root),
                                             legacy=settings.organize_originals,stretch=settings.stretch_169)
                if reused:
                    if settings.organize_originals and Path(reused['path']).parent != out_dir:
                        old_path=reused['path']
                        reused=self._rehome_export(reused,out_dir,i)
                        export_cache.pop(old_path,None)
                    result['files'].append(reused)
                else:
                    out_dir.mkdir(parents=True, exist_ok=True)
                    # 人数写入识别记录；复核人数改变时文件名不会留下旧计数。
                    out = out_dir / f'{i+1:02d}_高光_{clip["start"]:.3f}-{clip["end"]:.3f}s.mp4'
                    if out.exists():
                        out=out.with_stem(out.stem+'_'+uuid.uuid4().hex[:6])
                    pending=out_dir/f'.pending_{uuid.uuid4().hex}.mp4'
                    # 原画流拷贝，直接读取原片；不产生第二份整局录像。
                    try:
                        exporter.cut_clip(source, clip['start'], clip['end'], pending,
                                          stretch_169=settings.stretch_169,cancel_cb=self._stop.is_set)
                        self._verify_export(pending, clip['end']-clip['start'],settings.stretch_169)
                        pending.rename(out)
                    finally:
                        if pending.exists() and not pending.is_symlink():pending.unlink()
                    result['files'].append(dict(path=str(out.resolve()), size=out.stat().st_size,
                        digest=_digest(out), sha256=_sha256(out), start=clip['start'], end=clip['end'],
                        stretch_169=settings.stretch_169,
                        expected=clip['end']-clip['start']))
                    exported_new = True
                export_cache[result['files'][-1]['path']] = result['files'][-1]
                result['exports'] = list(export_cache.values())
                # 后续片段失败/重启时，已验证的片段仍可复用。
                self._update(row['id'], result=json.dumps(result, ensure_ascii=False))
            # 相同时间范围的重试只更新识别记录，不另建一份相同视频。
            # 保留旧范围索引，设置改回原范围时也可复用已验证成片。
            if not exported_new and not settings.organize_originals:
                out_dir = Path(result['files'][0]['path']).parent
            manifest = out_dir / '识别记录.json'
            if settings.organize_originals:
                self._archive_original(row,source,source_fp,result,settings)
                self._prune_superseded(row,result)
            completed = time.time()
            # 低置信度候选保留在记录中供七天内复核，不贡献击杀数或多杀片段。
            # 完整处理与校验已成功时仍执行用户指定的七天保留策略。
            needs_review = any(m.get('review_required', True) for m in marks)
            status='ready' if highlights else 'no_highlights'
            retained=row.get('retained_since') or completed
            cleanup_after=retained+settings.retention_days*86400
            result['completed_at']=completed
            result['cleanup_after']=cleanup_after if row['allow_cleanup'] else None
            if settings.organize_originals:
                self._write_bundle(row,result,status)
            else:
                archive.atomic_json(manifest,result)
            self._update(row['id'], status=status,
                result=json.dumps(result, ensure_ascii=False), completed=completed,
                retained_since=retained,cleanup_after=cleanup_after, digest=before_digest,
                error='存在低置信度候选，未计入击杀数或集锦；可在原片保留期内检查' if needs_review else None)
            if settings.organize_originals and settings.auto_clean_cache:
                cache.deduplicate_uploads(Path(result['original']['path']),row['archive_sha256'],
                    closed=_closed_by_recorder,busy=jobs.has_active())
                cache.deduplicate_legacy_exports(result['files'],closed=_closed_by_recorder)
        except CancelledError:
            if self._yielded:
                self._update(row['id'], status='waiting', error='开始玩游戏了，识别已暂停，玩完后自动重新开始')
            else:
                self._update(row['id'], status='waiting', error='服务停止，下次启动继续')
        except wegame.DatabaseBusy as exc:
            self._update(row['id'],status='waiting',stable_since=time.time(),error=str(exc))
        except Exception as exc:
            self._update(row['id'], status='error', error=str(exc))
        finally:
            self._active = None
            self.notify_pending()

    def game_reason(self):
        from .activity import detector
        s = self.settings
        return detector.reason(s.extra_game_processes, s.pause_on_fullscreen)

    def _may_process(self, now=None):
        """idle 模式下：正在玩游戏或刚玩完不久就先不处理。"""
        now = time.time() if now is None else now
        if self.settings.process_mode != 'idle':
            self.paused = ''
            return True
        reason = self.game_reason()
        if reason:
            self._last_game = now
            self.paused = reason + '，玩完再处理'
            return False
        wait = self.settings.idle_wait_minutes * 60 - (now - self._last_game)
        if self._last_game and wait > 0:
            self.paused = f'游戏刚结束，{max(1, round(wait / 60))} 分钟后开始处理'
            return False
        self.paused = ''
        return True

    def _should_yield(self):
        # 识别中途开了游戏：中断这次识别，放回队列，玩完再从头处理
        if self._stop.is_set():
            return True
        if self.settings.process_mode == 'idle' and self.game_reason():
            self._yielded = True
            self._last_game = time.time()
            return True
        return False

    def start_now(self, record_ids=None):
        """手动开始：把「等你开始」的录像放进队列（保留期规则与自动处理相同）。"""
        with self._lock, self._db() as db:
            if record_ids is None:
                rows = db.execute("SELECT id FROM recordings WHERE status='manual'").fetchall()
                record_ids = [r['id'] for r in rows]
            for rid in record_ids:
                db.execute("UPDATE recordings SET status='waiting', error=NULL WHERE id=? AND status='manual'", (rid,))
        return len(record_ids)

    def _progress(self, p, message):
        if self._active:
            self._active = self._active | dict(progress=p, message=message)

    def _analyze_source(self, source, settings, scan_windows=None):
        return workers.analyze_isolated(source, DetectParams(player_id=settings.player_id,scan_windows=scan_windows,use_gpu=settings.use_gpu),
                                        progress_cb=self._progress,cancel_cb=self._should_yield)

    def _prepare_bundle(self,row,result,settings):
        root=Path(settings.output_root).resolve()
        root.mkdir(parents=True,exist_ok=True)
        summary=result['summary']
        official=summary.get('official_kills')
        target=root/archive.bundle_name(row['path'],row['id'],
            official if official is not None else summary['confirmed_kills'],
            summary['has_highlights'],official=official is not None)
        old=Path(row['archive_dir']) if row.get('archive_dir') else None
        if old and old!=target and old.exists():
            marker=old/'归档标识.json'
            if (old.is_symlink() or old.resolve().parent!=Path(row['archive_root']).resolve()
                    or json.loads(marker.read_text(encoding='utf-8')).get('recording_id')!=row['id']):
                raise RuntimeError('旧归档目录身份不符，停止移动')
            if target.exists():
                raise RuntimeError('新的分类目录已经存在，保留现有文件等待复核')
            old.rename(target)
            cache.relocate_aliases(old,target)
        target.mkdir(exist_ok=True)
        marker=target/'归档标识.json'
        if marker.exists():
            if json.loads(marker.read_text(encoding='utf-8')).get('recording_id')!=row['id']:
                raise RuntimeError('归档目录属于另一项任务')
        elif any(target.iterdir()):
            raise RuntimeError('归档目标是已有的非托管文件夹，拒绝覆盖')
        else:
            archive.atomic_json(marker,dict(recording_id=row['id'],source=row['path']))
        for partial in target.glob('.pending_*.mp4'):
            if (re.fullmatch(r'\.pending_[0-9a-f]{32}\.mp4',partial.name)
                    and not partial.is_symlink() and _closed_by_recorder(partial)):
                partial.unlink()
        if old and old!=target:
            for item in result['exports']:
                path=Path(item['path'])
                if path.is_relative_to(old):item['path']=str(target/path.relative_to(old))
            if row.get('archive_path'):
                row['archive_path']=str(target/Path(row['archive_path']).name)
        row.update(archive_dir=str(target),archive_root=str(root))
        self._update(row['id'],archive_dir=str(target),archive_root=str(root),
                     archive_path=row.get('archive_path'))
        result['bundle']=dict(path=str(target),recording_id=row['id'],
            recorded_at=archive.recording_time(row['path']),name=target.name)
        return target

    def _rehome_export(self,item,out_dir,index):
        old=Path(item['path'])
        dest=out_dir/f'{index+1:02d}_高光.mp4'
        # 若同一编号已经用于另一范围，使用范围后缀，避免覆盖旧片段。
        if dest.exists() and archive.sha256(dest)!=item['sha256']:
            dest=out_dir/f'{index+1:02d}_高光_{item["start"]:.3f}-{item["end"]:.3f}.mp4'
        archive.move_verified(old,dest,_fingerprint(old),closed=_closed_by_recorder,
                              commit=lambda *_:None,cancelled=self._stop.is_set)
        return dict(item,path=str(dest.resolve()))

    def _archive_original(self,row,source,expected_fp,result,settings):
        dest=Path(row['archive_dir'])/'整局原录像.mp4'
        # 已归档重试改了文件夹标签，source 的旧目录名也随之变化。
        if not source.exists() and row.get('archive_path'):
            source=Path(row['archive_path']);expected_fp=_fingerprint(source)
        origin=Path(row['path'])
        if (not origin.resolve().is_relative_to(Path(settings.watch_root).resolve())
                or not re.fullmatch(r'record\d{8}-\d{6}\.mp4',origin.name,re.I)):
            raise RuntimeError('整局来源不属于已授权的录像目录')
        self._update(row['id'],archive_path=str(dest))
        row['archive_path']=str(dest)
        def commit(digest,fp):
            self._update(row['id'],archive_sha256=digest,archive_fingerprint=fp)
            row.update(archive_sha256=digest,archive_fingerprint=fp)
        self._progress(.98,'归档整局原录像，校验后释放来源空间')
        archive.move_verified(source,dest,expected_fp,closed=_closed_by_recorder,
                              commit=commit,cancelled=self._stop.is_set)
        result['original']=dict(path=str(dest),size=dest.stat().st_size,
            sha256=row['archive_sha256'],fingerprint=row['archive_fingerprint'],removed=False)

    def _write_bundle(self,row,result,status):
        directory=Path(row['archive_dir'])
        archive.atomic_json(directory/'识别记录.json',result)
        summary=result['summary']
        due=result.get('cleanup_after')
        due_text=(archive.datetime.fromtimestamp(due,archive.LOCAL_TIME).strftime('%Y-%m-%d %H:%M:%S')
                  if due else '保留，不自动清理')
        text=(f'录制时间：{result["bundle"]["recorded_at"]}\n'
              f'全局识别：{summary["confirmed_kills"]} 杀（同一目标击倒与补杀合并；不是官方战绩）\n'
              f'集锦条件：{summary["window_seconds"]:g} 秒内至少 2 名不同干员\n'
              f'是否有集锦：{"有" if summary["has_highlights"] else "无"}\n'
              f'高光片段：{len(result["files"])} 段\n'
              f'高光画幅：{"16:9 真实像素拉伸" if result.get("export_profile",{}).get("stretch_169") else "原始画幅"}；整局原片保持原始画幅。\n'
              f'原片状态：{("已手动删除" if result.get("original",{}).get("removed_by")=="user" else "已按保留期清理") if status=="deleted" else "归档在本文件夹"}\n'
              f'原片清理时间：{due_text}（UTC+08:00）\n'
              f'低置信度候选：{summary["review_candidates"]}；未计入人数或集锦，可在七天内复核。\n'
              '导出或文件校验失败时暂停清理。需要长期保留时可在网页点击“保留这局原片”。\n'
              '高光成片长期保留。自动流程不上传，不再保存另一份整局缓存。\n')
        if result.get('official_events'):
            info=result['official_events']
            text=(f'官方结算：{info["official_kills"]} 杀（不等同于已核对的不同干员人数）\n'
                  f'官方事件：{info["kill_points"]} 个击杀点，{info["loot_points"]} 个摸金点；摸金不计入多杀。\n'
                  '时间与时刻名称直接读取本地 DB；仅在击杀点附近通过画面核对不同干员。\n'
                  +'\n'.join(info['warnings'])+'\n'+text)
        (directory/'录像说明.txt').write_text(text,encoding='utf-8')
        if not (directory/'剪辑工程.json').exists():projects.save(row,projects.load(row))

    def _prune_superseded(self,row,result):
        keep={item['path'] for item in result['files']}
        remaining=[]
        directory=Path(row['archive_dir']).resolve()
        for item in result['exports']:
            path=Path(item['path'])
            if item['path'] in keep:
                remaining.append(item);continue
            try:
                if (path.exists() and not path.is_symlink() and path.resolve().parent==directory
                        and item.get('sha256') and archive.sha256(path)==item['sha256']
                        and _closed_by_recorder(path)):
                    path.unlink()
                elif path.exists():remaining.append(item)
            except OSError:remaining.append(item)
        result['exports']=remaining

    def notify_pending(self):
        if not self.settings.notify_on_complete:return
        with self._db() as db:
            rows=[dict(r) for r in db.execute("SELECT * FROM recordings WHERE notified IS NULL "
                "AND status IN ('ready','no_highlights','review','error') ORDER BY completed")]
        if not rows:return
        done=[r for r in rows if r['status'] in {'ready','no_highlights'}]
        problems=len(rows)-len(done)
        if len(rows)==1 and done:
            entry=json.loads(done[0]['result'])
            summary=entry.get('summary',{})
            stamp=archive.recording_time(done[0]['path'])[5:16].replace('T',' ')
            body=f'{stamp}：识别 {summary.get("confirmed_kills",0)} 杀，生成 {len(entry.get("files",[]))} 段高光'
        else:
            body=f'{len(done)} 段录像处理完成'
            if problems:body+=f'，{problems} 段需要检查'
        body+=f'。已保存到 {self.settings.output_root}，点击可查看本地网页。' if done else '。原片保留，请打开网页查看原因。'
        result=notifications.send('三角洲录像处理完成，可以查看了' if done else '三角洲录像需要检查',body)
        for row in rows:
            # 即使系统禁用了通知，也不每 15 秒重复打扰；错误在网页保留。
            self._update(row['id'],notified=time.time(),notification_error=result['error'] or None)

    def cleanup_cache(self,now=None):
        if not self.settings.auto_clean_cache:return
        now=time.time() if now is None else now
        if now-self._last_cache_cleanup<3600:return
        cache.cleanup(now=now,closed=_closed_by_recorder,busy=jobs.has_active(),
                      active_workers=workers.active_directories())
        self._last_cache_cleanup=now

    def _reuse_export(self, candidates, clip, output_root, legacy=False,stretch=False):
        for item in candidates:
            if (item.get('start') != clip['start'] or item.get('end') != clip['end']
                    or not item.get('sha256') or bool(item.get('stretch_169',False))!=stretch):
                continue
            path = Path(item['path'])
            try:
                allowed=path.resolve().is_relative_to(output_root.resolve())
                if legacy:
                    allowed|=path.resolve().is_relative_to((config.BASE_DIR.parent/'outputs'/'highlights').resolve())
                if (path.is_symlink() or not allowed
                        or path.stat().st_size != item['size'] or _sha256(path) != item['sha256']):
                    continue
                self._verify_export(path, clip['end']-clip['start'],stretch)
                return dict(item)
            except (OSError, RuntimeError, ValueError):
                continue
        return None

    def _verify_export(self,path,expected,stretch):
        self.verify_clip(path,expected)
        if stretch:
            meta=video.probe(path)
            if meta['height']<=0 or abs(meta['width']/meta['height']-16/9)>.005:
                raise RuntimeError('高光没有真正导出为 16:9 像素画面')

    @staticmethod
    def verify_clip(path: Path, expected: float):
        meta = video.probe(path)
        if (meta['size_bytes'] <= 0 or meta['width'] <= 0 or meta['duration'] <= 0 or
            abs(meta['duration']-expected) > max(3., expected*.1)):
            raise RuntimeError(f'成片时长或视频轨验证失败：{path}')
        # 全片解码验证；不能仅凭“ffmpeg 返回 0 / 文件存在”删除原片。
        exporter._run([exporter._ffmpeg(), '-v', 'error', '-xerror', '-i', str(path),
                       '-map', '0:v:0', '-f', 'null', '-'])

    def cleanup_due(self, now: float | None = None):
        if not self.settings.delete_after_retention:
            return
        now = time.time() if now is None else now
        root = Path(self.settings.watch_root).resolve()
        with self._db() as db:
            rows = list(db.execute("SELECT * FROM recordings WHERE status IN ('ready','no_highlights') AND "
                                   'allow_cleanup=1 AND cleanup_after<=?', (now,)))
        for row in rows:
            if row['archive_path']:
                self._cleanup_archived(dict(row),now)
                continue
            if row['status']!='ready':continue
            source = Path(row['path'])
            try:
                # 仅本服务成功处理、保留期已过的精确单文件；绝不递归清理目录。
                if (source.is_symlink() or not source.resolve().is_relative_to(root) or
                    source.resolve() not in set(self._sources())):
                    raise RuntimeError('原片路径不再属于已授权的整局录像目录')
                if _fingerprint(source) != row['fingerprint'] or _digest(source) != row['digest']:
                    raise RuntimeError('原片已改变，取消自动删除')
                result = json.loads(row['result'])
                if not result.get('files'):
                    raise RuntimeError('缺少已验证的成片')
                for item in result['files']:
                    out = Path(item['path'])
                    if out.stat().st_size != item['size'] or _digest(out) != item['digest']:
                        raise RuntimeError('成片不存在或发生变化，原片保留')
                    if item.get('sha256') and _sha256(out) != item['sha256']:
                        raise RuntimeError('成片内容发生变化，原片保留')
                    self.verify_clip(out, item['expected'])
                if not _closed_by_recorder(source):
                    continue
                if self._stop.is_set():
                    return
                if _fingerprint(source) != row['fingerprint'] or _digest(source) != row['digest']:
                    raise RuntimeError('验证成片期间原片发生变化，取消自动删除')
                source.unlink()
                self._update(row['id'], status='deleted', error=None)
            except Exception as exc:
                self._update(row['id'], status='review', error=f'清理已暂停：{exc}')

    def _cleanup_archived(self,row,now):
        if jobs.has_active():return
        try:
            directory=Path(row['archive_dir'])
            source=Path(row['archive_path'])
            if (directory.is_symlink() or source.is_symlink()
                    or directory.resolve().parent!=Path(row['archive_root']).resolve()
                    or source.resolve().parent!=directory.resolve()
                    or source.name!='整局原录像.mp4'):
                raise RuntimeError('归档原片路径不符，取消清理')
            marker=json.loads((directory/'归档标识.json').read_text(encoding='utf-8'))
            if marker.get('recording_id')!=row['id']:
                raise RuntimeError('归档身份不符')
            if (_fingerprint(source)!=row['archive_fingerprint']
                    or archive.sha256(source)!=row['archive_sha256']):
                raise RuntimeError('归档原片已经改变，取消清理')
            result=json.loads(row['result'])
            if (not result.get('completed_at')
                    or (result['summary']['has_highlights'] and not result['files'] and not result.get('user_removed_clips'))):
                raise RuntimeError('识别或导出未完整完成，保留原片')
            for item in result['files']:
                out=Path(item['path'])
                if (out.is_symlink() or out.resolve().parent!=directory.resolve()
                        or out.stat().st_size!=item['size'] or archive.sha256(out)!=item['sha256']):
                    raise RuntimeError('高光文件丢失或改变，原片保留')
                self.verify_clip(out,item['expected'])
            with self._lock:
                with self._db() as db:
                    current=db.execute('SELECT * FROM recordings WHERE id=?',(row['id'],)).fetchone()
                if (not current['allow_cleanup'] or current['status'] not in {'ready','no_highlights'}
                        or current['cleanup_after']>now):return
                if not _closed_by_recorder(source) or self._stop.is_set():return
                if _fingerprint(source)!=row['archive_fingerprint']:
                    raise RuntimeError('验证期间原片发生变化')
                source.unlink()
                result['original'].update(removed=True,removed_at=now)
                self._update(row['id'],status='deleted',result=json.dumps(result,ensure_ascii=False),error=None)
            self._write_bundle(row,result,'deleted')
        except Exception as exc:
            if 'result' in locals() and result.get('original',{}).get('removed'):
                self._update(row['id'],error=f'原片已清理，说明文件更新失败：{exc}')
            else:
                self._update(row['id'],status='review',error=f'清理已暂停：{exc}')

    def retain_original(self,record_id):
        with self._lock,self._db() as db:
            row=db.execute('SELECT * FROM recordings WHERE id=?',(record_id,)).fetchone()
            if not row or row['status'] in {'deleted','processing'}:
                raise ValueError('录像已清理或仍在处理，请稍后操作')
            result=json.loads(row['result']) if row['result'] else None
            if result:result['cleanup_after']=None
            db.execute('UPDATE recordings SET allow_cleanup=0,result=? WHERE id=?',
                (json.dumps(result,ensure_ascii=False) if result else None,record_id))
        if result and row['archive_dir']:self._write_bundle(dict(row),result,row['status'])

    def _owned_bundle(self,record_id):
        """手动删除只作用于本服务建立、身份校验通过的归档目录。"""
        row=self.recording(record_id)
        if not row:raise ValueError('归档不存在')
        if row['status'] in {'waiting','processing','removed'}:
            raise ValueError('这段录像正在排队或处理，完成后再删除')
        if not row['archive_dir'] or not row['archive_root']:raise ValueError('这段录像没有归档文件夹')
        directory=Path(row['archive_dir'])
        root=Path(row['archive_root']).resolve()
        if (directory.is_symlink() or not directory.is_dir() or directory.resolve().parent!=root
                or directory.resolve()==root):
            raise ValueError('归档文件夹路径不符，取消删除')
        marker=json.loads((directory/'归档标识.json').read_text(encoding='utf-8'))
        if marker.get('recording_id')!=row['id']:raise ValueError('归档身份不符，取消删除')
        return row,directory

    @staticmethod
    def _retry_locked(action):
        # 浏览器刚关闭播放时，Windows 可能还要片刻才释放文件句柄。
        for attempt in range(6):
            try:return action()
            except PermissionError:
                if attempt==5:raise ValueError('文件正被占用（可能还在播放），关闭播放后再试')
                time.sleep(.3)

    def delete_original(self,record_id):
        with self._lock:
            row,directory=self._owned_bundle(record_id)
            if row['status']=='deleted':raise ValueError('整局原片已经删除')
            source=Path(row['archive_path'] or '')
            if (not row['archive_path'] or source.is_symlink() or source.name!='整局原录像.mp4'
                    or source.resolve().parent!=directory.resolve()):
                raise ValueError('整局原片不在归档文件夹内，取消删除')
            if source.exists():self._retry_locked(source.unlink)
            result=row['result'] or {}
            result.setdefault('original',{}).update(removed=True,removed_at=time.time(),removed_by='user')
            result['cleanup_after']=None
            self._update(row['id'],status='deleted',result=json.dumps(result,ensure_ascii=False),error=None)
        self._write_bundle(row,result,'deleted')

    @staticmethod
    def _inside(path,directory):
        # 只允许删集锦包里的成片，绝不碰整局原片或包外文件
        return (not path.is_symlink() and path.name!='整局原录像.mp4' and path.suffix.lower()=='.mp4'
                and path.resolve().is_relative_to(directory.resolve()) and path.resolve()!=directory.resolve())

    def delete_highlight(self,record_id,index):
        with self._lock:
            row,directory=self._owned_bundle(record_id)
            result=row['result'] or {}
            files=result.get('files',[])
            if not isinstance(index,int) or not 0<=index<len(files):raise ValueError('这段高光不存在')
            item=files[index]
            path=Path(item['path'])
            if not self._inside(path,directory):raise ValueError('高光文件不在这局的集锦文件夹里，取消删除')
            if path.exists():self._retry_locked(path.unlink)
            files.pop(index)
            result['exports']=[e for e in result.get('exports',[]) if e.get('path')!=item['path']]
            # 用户删过高光：之后即使一段不剩，也不当作「导出未完成」而暂停原片清理
            result['user_removed_clips']=result.get('user_removed_clips',0)+1
            self._update(row['id'],result=json.dumps(result,ensure_ascii=False))
            project=projects.load(row)
            project['sources'].pop(f'bundle_{row["id"]}_clip_{item.get("sha256","")[:12]}',None)
            projects.save(row,project)
        self._write_bundle(row,result,row['status'])

    def delete_manual_export(self,record_id,export_id,name):
        with self._lock:
            row,directory=self._owned_bundle(record_id)
            project=projects.load(row)
            entry=next((e for e in project.get('manual_exports',[]) if e['id']==export_id),None)
            item=next((f for f in entry['files'] if f['name']==name),None) if entry else None
            if not item:raise ValueError('这个手动剪辑不存在')
            path=directory/item['path']
            if not self._inside(path,directory):raise ValueError('文件不在这局的集锦文件夹里，取消删除')
            if path.exists():self._retry_locked(path.unlink)
            entry['files'].remove(item)
            if not entry['files']:
                project['manual_exports'].remove(entry)
                parent=path.parent
                # 清掉空的导出目录（只删空目录）
                while parent.resolve()!=directory.resolve() and parent.resolve().is_relative_to(directory.resolve()):
                    try:parent.rmdir()
                    except OSError:break
                    parent=parent.parent
            projects.save(row,project)

    def delete_bundle(self,record_id):
        with self._lock:
            row,directory=self._owned_bundle(record_id)
            # 先整体改名：Windows 下有文件被占用时改名会失败，避免删到一半。
            trash=directory.with_name(f'.删除中_{row["id"]}')
            self._retry_locked(lambda:directory.rename(trash))
            self._update(row['id'],status='removed',result=None,cleanup_after=None,
                         allow_cleanup=0,error=None)
            try:shutil.rmtree(trash)
            except OSError as exc:
                self._update(row['id'],error=f'集锦包已移除，残留临时文件夹 {trash}：{exc}')

    def retry(self, record_id: str):
        with self._lock, self._db() as db:
            row = db.execute('SELECT * FROM recordings WHERE id=?', (record_id,)).fetchone()
            if not row or row['status'] in {'processing', 'deleted', 'removed'}:
                raise ValueError('只能重试历史、失败、无高光或待复核的录像')
            path = self._source_path(row)
            values=dict(fingerprint=_fingerprint(path)) if path==Path(row['path']) else {}
            # 归档后重试延续七天策略，不重新起算保留时钟。
            allow=row['allow_cleanup'] if row['archive_path'] else 0
            previous=json.loads(row['result']) if row['result'] else None
            if previous:previous.pop('analysis_params',None)
            db.execute("UPDATE recordings SET status='waiting', fingerprint=?, stable_since=?, "
                       'allow_cleanup=?, result=?, error=NULL WHERE id=?',
                       (values.get('fingerprint',row['fingerprint']), time.time(),allow,
                        json.dumps(previous,ensure_ascii=False) if previous else None,record_id))

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        # 只有真正启动监控服务时恢复中断任务，单纯导入/查看状态不改正在处理的队列。
        with self._db() as db:
            db.execute("UPDATE recordings SET status='waiting' WHERE status='processing'")
        self._thread = threading.Thread(target=self._loop, daemon=True, name='record-workflow')
        self._thread.start()

    def stop(self):
        self._stop.set()

    def _loop(self):
        while not self._stop.is_set():
            try:
                if self.settings.enabled and self.settings.configured:
                    self.discover()
                if self.settings.configured and self._may_process():
                    self.process_next()
                self.cleanup_due()
                self.cleanup_cache()
                self.notify_pending()
                self.last_error = ''
            except Exception as exc:
                self.last_error = str(exc)
            self._stop.wait(self.settings.poll_seconds)


workflow = WorkflowService()
