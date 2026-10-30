"""集锦剪辑工程：把仓库根目录的 montage 卡点模块包成网页可用的工程。

一个工程 = 挑选的素材 + 一首歌 + 参数（片头 / 转场 / 片尾 / 卡点规则）+ 时间线。
工程文件放在 storage/montage/projects/<id>/project.json；人和 agent 改的是同一份时间线，
都通过 apply_ops() 修改，再用 montage.retime 重算变速。
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .. import config

_ROOT = config.BASE_DIR.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import montage  # noqa: E402
from montage import kills as kills_mod, planner, render as render_mod  # noqa: E402
from montage.media import duration as probe_duration  # noqa: E402

HOME = config.STORAGE_DIR / 'montage'
PROJECTS = HOME / 'projects'
THUMBS = HOME / 'thumbs'
BUMPERS = HOME / 'bumpers'
SETTINGS = HOME / 'settings.json'
for _d in (PROJECTS, THUMBS, BUMPERS / 'intro', BUMPERS / 'outro'):
    _d.mkdir(parents=True, exist_ok=True)

VIDEO_EXT = {'.mp4', '.mkv', '.mov', '.m4v', '.webm', '.avi'}
AUDIO_EXT = {'.mp3', '.flac', '.wav', '.m4a', '.aac', '.ogg', '.ncm'}

TRANSITIONS = [
    dict(id='cut', label='硬切', desc='直接切到下一个镜头'),
    dict(id='push', label='推镜', desc='上一镜头加速推进，下一镜头从放大回落'),
    dict(id='impact', label='重击', desc='入场闪白加轻微抖动'),
    dict(id='flash', label='闪白', desc='切点处一下白闪'),
    dict(id='dip', label='闪黑', desc='快速压黑再亮起'),
    dict(id='whip', label='甩镜', desc='横向甩动带运动模糊'),
]
OPENINGS = [
    dict(id='fade_blur', label='模糊渐显', desc='从黑场和模糊里浮现，轻微推近'),
    dict(id='zoom', label='推近入场', desc='从放大的画面快速回落'),
    dict(id='flash', label='白闪入场', desc='一下白闪后进入'),
    dict(id='none', label='无', desc='第一帧直接开始'),
]
ENDINGS = [
    dict(id='fade', label='渐黑', desc='最后几秒画面和音乐一起淡出'),
    dict(id='blur', label='模糊渐黑', desc='先模糊再渐黑'),
    dict(id='none', label='无', desc='最后一帧直接结束'),
]
STYLES = [
    dict(id='clean', label='干净硬切', desc='全部硬切，节奏最清楚',
         config={'plan': {'transition': 'cut', 'transition_every': 0}, 'render': {'opening': 'fade_blur', 'ending': 'fade'}}),
    dict(id='punchy', label='燃向推镜', desc='每两个切点推一次镜，开头推近',
         config={'plan': {'transition': 'push', 'transition_every': 2}, 'render': {'opening': 'zoom', 'ending': 'fade'}}),
    dict(id='impact', label='重击闪白', desc='每三个切点一次重击入场',
         config={'plan': {'transition': 'impact', 'transition_every': 3}, 'render': {'opening': 'flash', 'ending': 'fade'}}),
    dict(id='flow', label='流畅甩镜', desc='每个切点都甩镜，结尾模糊',
         config={'plan': {'transition': 'whip', 'transition_every': 1}, 'render': {'opening': 'fade_blur', 'ending': 'blur'}}),
    dict(id='cinema', label='电影感', desc='闪黑转场，前因留得更长',
         config={'plan': {'transition': 'dip', 'transition_every': 2, 'lead': [6.0, 10.0]},
                 'render': {'opening': 'fade_blur', 'ending': 'blur', 'fade_out': 2.5}}),
]
# 网页上可以直接调的参数（其余参数 agent 或高级设置里改）
EDITABLE = {
    'plan': ['duration', 'kills_per_shot', 'chain_max_gap', 'speed_max', 'ff_speed_max', 'first_lead', 'lead',
             'transition', 'transition_every', 'max_shot_len', 'tail'],
    'render': ['opening', 'title', 'ending', 'fade_out', 'intro_video', 'outro_video', 'hq', 'game_volume', 'music_volume'],
    'kills': ['av_offset', 'only_confirmed'],
}

_lock = threading.RLock()
_probe_cache: dict[tuple, float] = {}


# ------------------------------------------------------------------ 设置（agent 的 API key 等）
def load_settings() -> dict:
    try:
        return json.loads(SETTINGS.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}


def save_settings(values: dict) -> dict:
    cur = load_settings()
    for k in ('api_key', 'model'):
        if k in values and values[k] is not None:
            cur[k] = str(values[k]).strip()
    SETTINGS.write_text(json.dumps(cur, ensure_ascii=False, indent=1), encoding='utf-8')
    return public_settings()


def public_settings() -> dict:
    s = load_settings()
    return dict(model=s.get('model') or 'claude-opus-5-5',
                api_key_set=bool(s.get('api_key') or os.environ.get('ANTHROPIC_API_KEY')))


# ------------------------------------------------------------------ 路径访问控制
def _output_root() -> str:
    from .workflow import workflow
    return workflow.settings.output_root or ''


def _inside(path: Path, base: Path) -> bool:
    try:
        path.resolve().relative_to(base.resolve())
        return True
    except (ValueError, OSError):
        return False


def allowed(path: str) -> Path:
    """只允许读集锦文件夹、各工程挑过的素材文件夹、片头片尾库里的文件。"""
    p = Path(path)
    roots = [BUMPERS, PROJECTS]
    if _output_root():
        roots.append(Path(_output_root()))
    for proj in list_projects():
        if proj.get('folder'):
            roots.append(Path(proj['folder']))
    if p.is_file() and any(_inside(p, r) for r in roots):
        return p
    raise PermissionError('这个文件不在素材文件夹里')


# ------------------------------------------------------------------ 素材扫描
def _duration(path: Path) -> float:
    st = path.stat()
    key = (str(path), st.st_mtime, st.st_size)
    if key not in _probe_cache:
        try:
            _probe_cache[key] = round(probe_duration(str(path)), 3)
        except (ValueError, OSError):
            _probe_cache[key] = 0.0
    return _probe_cache[key]


def _bundle_kills(path: Path, dur: float) -> int:
    """集锦包里的高光 / 整局原片：数一下识别记录里落在这段的击杀。"""
    rec = path.parent / '识别记录.json'
    if not rec.is_file():
        return 0
    m = re.search(r'_高光_([\d.]+)-([\d.]+)s', path.name)
    a, b = (float(m.group(1)), float(m.group(2))) if m else (0.0, dur) if path.name.startswith('整局原录像') else (None, None)
    if a is None:
        return 0
    try:
        marks = json.loads(rec.read_text(encoding='utf-8')).get('marks', [])
    except (OSError, ValueError):
        return 0
    return sum(1 for mk in marks if mk.get('event_type') == 'kill' and mk.get('confirmed')
               and mk.get('verification_time') is not None and a + 0.5 <= mk['verification_time'] <= b)


def _kind(path: Path) -> str:
    if '_高光_' in path.name:
        return 'highlight'
    if path.name.startswith('整局原录像'):
        return 'original'
    if path.parent.name == '手动剪辑' or path.parent.parent.name == '手动剪辑':
        return 'manual'
    return 'other'


def scan_folder(folder: str, depth: int = 3, limit: int = 600) -> dict:
    root = Path(folder)
    if not root.is_dir():
        raise ValueError('文件夹不存在')
    found = []
    for dirpath, dirnames, filenames in os.walk(root):
        rel_depth = len(Path(dirpath).relative_to(root).parts)
        if rel_depth >= depth:
            dirnames[:] = []
        dirnames[:] = [d for d in dirnames if not d.startswith('.')]
        for name in filenames:
            p = Path(dirpath) / name
            if p.suffix.lower() in VIDEO_EXT:
                found.append(p)
        if len(found) >= limit:
            break
    found = sorted(found[:limit], key=lambda p: p.stat().st_mtime, reverse=True)
    with ThreadPoolExecutor(8) as ex:
        durs = list(ex.map(_duration, found))
    items = []
    for p, d in zip(found, durs):
        st = p.stat()
        items.append(dict(path=str(p), name=p.name, rel=str(p.relative_to(root)), group=str(p.parent.relative_to(root)) or '.',
                          size=st.st_size, mtime=st.st_mtime, duration=d, kind=_kind(p), auto_kills=_bundle_kills(p, d)))
    return dict(folder=str(root), items=items, truncated=len(found) >= limit)


def thumbnail(path: str, t: float) -> Path:
    p = allowed(path)
    st = p.stat()
    key = hashlib.sha1(f'{p}|{st.st_mtime}|{round(t, 1)}'.encode()).hexdigest()[:20]
    out = THUMBS / f'{key}.jpg'
    if not out.is_file():
        subprocess.run(['ffmpeg', '-v', 'error', '-y', '-ss', f'{max(0.0, t):.2f}', '-i', str(p), '-frames:v', '1',
                        '-vf', 'scale=320:-2', '-q:v', '5', str(out)], capture_output=True, timeout=60)
        if not out.is_file():
            raise FileNotFoundError('无法截取画面')
    return out


# ------------------------------------------------------------------ 片头 / 片尾视频库
def list_bumpers() -> dict:
    out = {}
    for kind in ('intro', 'outro'):
        out[kind] = [dict(path=str(p), name=p.name, duration=_duration(p))
                     for p in sorted((BUMPERS / kind).iterdir()) if p.suffix.lower() in VIDEO_EXT]
    return out


def save_bumper(kind: str, filename: str, data_iter) -> dict:
    if kind not in ('intro', 'outro'):
        raise ValueError('只能是片头或片尾')
    name = Path(filename).name
    if Path(name).suffix.lower() not in VIDEO_EXT:
        raise ValueError('请上传视频文件')
    dest = BUMPERS / kind / name
    with dest.open('wb') as f:
        for chunk in data_iter:
            f.write(chunk)
    return dict(path=str(dest), name=name, duration=_duration(dest))


def presets() -> dict:
    return dict(transitions=TRANSITIONS, openings=OPENINGS, endings=ENDINGS, styles=STYLES,
                defaults=montage.config.DEFAULTS, editable=EDITABLE, bumpers=list_bumpers())


# ------------------------------------------------------------------ 工程读写
def _pdir(pid: str) -> Path:
    if not re.fullmatch(r'[0-9a-f]{12}', pid or ''):
        raise KeyError(pid)
    return PROJECTS / pid


def list_projects() -> list[dict]:
    out = []
    for d in PROJECTS.iterdir():
        f = d / 'project.json'
        if f.is_file():
            try:
                p = json.loads(f.read_text(encoding='utf-8'))
            except (OSError, ValueError):
                continue
            out.append(dict(id=p['id'], name=p['name'], updated=p.get('updated', 0), folder=p.get('folder', ''),
                            shots=len((p.get('timeline') or {}).get('shots', [])), song=(p.get('song') or {}).get('name')))
    return sorted(out, key=lambda x: -x['updated'])


def load(pid: str) -> dict:
    f = _pdir(pid) / 'project.json'
    if not f.is_file():
        raise KeyError(pid)
    return json.loads(f.read_text(encoding='utf-8'))


def save(p: dict) -> dict:
    with _lock:
        p['updated'] = time.time()
        d = _pdir(p['id'])
        d.mkdir(parents=True, exist_ok=True)
        tmp = d / 'project.json.tmp'
        tmp.write_text(json.dumps(p, ensure_ascii=False, indent=1), encoding='utf-8')
        os.replace(tmp, d / 'project.json')
    return p


def create(name: str = '', folder: str = '') -> dict:
    pid = uuid.uuid4().hex[:12]
    p = dict(id=pid, name=name or time.strftime('集锦 %m-%d %H:%M'), created=time.time(), folder=folder or _output_root(),
             clips=[], song=None, settings={}, timeline=None, errors=[], kills_cache={}, chat=[], agent_messages=[], renders=[])
    return save(p)


def delete(pid: str):
    shutil.rmtree(_pdir(pid), ignore_errors=True)


def public(p: dict) -> dict:
    """给网页的工程：去掉 agent 原始消息这类大字段。"""
    out = {k: v for k, v in p.items() if k not in ('agent_messages', 'kills_cache')}
    if p.get('song'):
        out['song'] = {k: v for k, v in p['song'].items() if k != 'path'}
    out['config'] = cfg_of(p)
    return out


def cfg_of(p: dict) -> dict:
    return montage.config.load(override=p.get('settings') or {})


def update(pid: str, values: dict) -> dict:
    """网页保存：名称、素材文件夹、素材选择 / 手动击杀、参数。"""
    with _lock:
        p = load(pid)
        if 'name' in values:
            p['name'] = str(values['name'])[:80] or p['name']
        if 'folder' in values:
            p['folder'] = str(values['folder'] or '')
        if 'clips' in values:
            p['clips'] = [dict(path=str(c['path']), selected=bool(c.get('selected', True)),
                               manual_kills=sorted(float(k) for k in c.get('manual_kills') or []),
                               duration=float(c.get('duration') or 0), name=c.get('name') or Path(c['path']).name)
                          for c in values['clips'] if c.get('path')]
        if 'settings' in values:
            p['settings'] = merge_settings(p.get('settings') or {}, values['settings'] or {})
        return save(p)


def merge_settings(cur: dict, new: dict) -> dict:
    out = copy.deepcopy(cur)
    for sec, vals in (new or {}).items():
        if sec not in montage.config.DEFAULTS or not isinstance(vals, dict):
            raise ValueError(f'没有这组参数：{sec}')
        for k, v in vals.items():
            if k not in montage.config.DEFAULTS[sec]:
                raise ValueError(f'没有这个参数：{sec}.{k}')
            if sec == 'plan' and k == 'transition' and v not in render_mod.TRANSITIONS:
                raise ValueError(f'没有这种转场：{v}')
            if sec == 'render' and k == 'opening' and v not in render_mod.OPENINGS:
                raise ValueError(f'没有这种开头：{v}')
            if sec == 'render' and k == 'ending' and v not in render_mod.ENDINGS:
                raise ValueError(f'没有这种结尾：{v}')
            out.setdefault(sec, {})[k] = v
    return out


# ------------------------------------------------------------------ 歌曲
def _peaks(wav: str, per_second: int = 50) -> list[float]:
    import numpy as np
    raw = subprocess.run(['ffmpeg', '-v', 'error', '-i', wav, '-ac', '1', '-ar', '8000', '-f', 's16le', '-'],
                         capture_output=True).stdout
    a = np.abs(np.frombuffer(raw, np.int16).astype(float) / 32768)
    hop = 8000 // per_second
    n = len(a) // hop
    if not n:
        return []
    pk = a[:n * hop].reshape(n, hop).max(1)
    pk = pk / (pk.max() or 1)
    return [round(float(x), 3) for x in pk]


def analyze_song(pid: str, src: Path, name: str, job=None) -> dict:
    work = _pdir(pid) / 'work'
    work.mkdir(parents=True, exist_ok=True)
    if job:
        job.update(progress=0.1, message='正在读取歌曲…')
    p = load(pid)
    info = montage.analyze_song(str(src), str(work), cfg_of(p))
    if job:
        job.update(progress=0.8, message='正在画波形…')
    song = dict(name=name, path=info['path'], bpm=info['bpm'], beats=info['beats'], downbeats=info['downbeats'],
                top=info['top'], duration=round(probe_duration(info['path']), 3), peaks=_peaks(info['path']), peaks_per_second=50)
    with _lock:
        p = load(pid)
        p['song'] = song
        save(p)
    return dict(bpm=song['bpm'], duration=song['duration'])


def song_path(pid: str) -> Path:
    p = load(pid)
    if not p.get('song'):
        raise FileNotFoundError('还没有歌')
    return Path(p['song']['path'])


# ------------------------------------------------------------------ 编排 / 时间线修改
def _clip_kills(p: dict, cfg: dict, log=lambda m: None) -> tuple[list, list]:
    sel = [c for c in p.get('clips', []) if c.get('selected', True)]
    cache = p.setdefault('kills_cache', {})
    clips, skipped = [], []
    for i, c in enumerate(sel):
        path = c['path']
        if not os.path.isfile(path):
            skipped.append(f"{c.get('name') or path}：文件不存在")
            continue
        st = os.stat(path)
        key = f"{path}|{st.st_mtime}|{cfg['kills']['av_offset']}|{cfg['kills']['only_confirmed']}"
        manual = {path: c['manual_kills']} if c.get('manual_kills') else {}
        if not manual and key in cache:
            got = cache[key]
        else:
            log(f'正在找开枪时刻 {i + 1}/{len(sel)}')
            got = kills_mod.from_files([path], cfg['kills'], manual, {path: c.get('duration') or _duration(Path(path))})
            if not manual:
                cache[key] = got
        if got:
            clips += got
        else:
            skipped.append(f"{c.get('name') or Path(path).name}：没有击杀标记（可在预览里手动标）")
    return clips, skipped


def auto_plan(pid: str, job=None) -> dict:
    p = load(pid)
    if not p.get('song'):
        raise ValueError('先选一首歌')
    cfg = cfg_of(p)
    log = (lambda m: job.update(message=m)) if job else (lambda m: None)
    clips, skipped = _clip_kills(p, cfg, log)
    if not clips:
        raise ValueError('选中的素材里没有可用的击杀。集锦包里的高光会自动识别；其他视频请在预览里手动标记击杀。')
    song = dict(p['song'])
    tl = planner.plan(song, clips, cfg)
    tl['song'] = song['path']
    tl, errors = planner.retime(tl, cfg)
    with _lock:
        cur = load(pid)
        cur['kills_cache'] = p['kills_cache']
        cur['timeline'] = tl
        cur['errors'] = errors
        cur['skipped'] = skipped
        cur['clip_kills'] = {c['file']: c['kills'] for c in clips}
        save(cur)
    return dict(shots=len(tl['shots']), duration=tl['duration'], skipped=skipped, errors=errors)


def apply_ops(pid: str, ops: list[dict]) -> dict:
    """修改时间线。人在网页上拖动、agent 调工具，走的都是这里。

    op 种类：
      move_kill {shot, kill, at}          击杀落在成片第几秒
      delete_kill {shot, kill}
      delete_shot {shot}
      move_shot {shot, to}                调整镜头顺序
      set_transition {shot, transition}   镜头入场转场
      set_end {shot, end}                 镜头结束时间（成片秒）
      replace_clip {shot, file}           换成另一段素材（用它的击杀，落点保持）
      set_all_transitions {transition}
    """
    with _lock:
        p = load(pid)
        tl = p.get('timeline')
        if not tl:
            raise ValueError('还没有时间线，先自动编排')
        cfg = cfg_of(p)
        shots = tl['shots']
        clip_kills = p.get('clip_kills') or {}

        def shot(i):
            i = int(i)
            if not 0 <= i < len(shots):
                raise ValueError(f'没有第 {i + 1} 个镜头')
            return shots[i]

        for op in ops:
            kind = op.get('op')
            if kind == 'move_kill':
                s = shot(op['shot'])
                ks = sorted(s['kills'], key=lambda k: k['at'])
                k = int(op['kill'])
                if not 0 <= k < len(ks):
                    raise ValueError('没有这个击杀')
                ks[k]['at'] = round(float(op['at']), 3)
                s['kills'] = sorted(ks, key=lambda k: k['at'])
                if k == len(ks) - 1:
                    s['end'] = max(s['end'], ks[k]['at'] + 0.5)
            elif kind == 'delete_kill':
                s = shot(op['shot'])
                ks = sorted(s['kills'], key=lambda k: k['at'])
                if len(ks) <= 1:
                    raise ValueError('镜头至少要留一个击杀；要删整个镜头请用删除镜头')
                ks.pop(int(op['kill']))
                s['kills'] = ks
            elif kind == 'delete_shot':
                shot(op['shot'])
                shots.pop(int(op['shot']))
            elif kind == 'move_shot':
                s = shot(op['shot'])
                to = max(0, min(len(shots) - 1, int(op['to'])))
                shots.pop(int(op['shot']))
                shots.insert(to, s)
            elif kind == 'set_transition':
                if op['transition'] not in render_mod.TRANSITIONS:
                    raise ValueError(f"没有这种转场：{op['transition']}")
                shot(op['shot'])['transition_in'] = op['transition']
            elif kind == 'set_all_transitions':
                if op['transition'] not in render_mod.TRANSITIONS:
                    raise ValueError(f"没有这种转场：{op['transition']}")
                for s in shots[1:]:
                    s['transition_in'] = op['transition']
            elif kind == 'set_end':
                s = shot(op['shot'])
                last = max(k['at'] for k in s['kills'])
                s['end'] = round(max(last + 0.3, float(op['end'])), 3)
            elif kind == 'replace_clip':
                s = shot(op['shot'])
                ks = clip_kills.get(op['file'])
                if not ks:
                    raise ValueError('这段素材没有击杀信息，先把它勾选进素材再自动编排一次')
                first = min(k['at'] for k in s['kills'])
                s['file'] = op['file']
                s['kills'] = [dict(src=ks[0], at=first)]
                s['end'] = round(first + 1.5, 3)
            else:
                raise ValueError(f'不认识的操作：{kind}')
        # 删了 / 挪了镜头后，按顺序把每个镜头平移到新的起点，第一个击杀重新吸附到最近的拍上（只改前因长短）
        beats = (p.get('song') or {}).get('beats') or []
        t = 0.0
        for s in shots:
            shift = t - s['start']
            if abs(shift) > 1e-6:
                first = min(k['at'] for k in s['kills']) + shift
                near = [b for b in beats if b - t >= 1.0]
                if near:
                    shift += min(near, key=lambda b: abs(b - first)) - first
                for k in s['kills']:
                    k['at'] = round(k['at'] + shift, 3)
                s['end'] = round(s['end'] + shift, 3)
                s['start'] = round(t, 4)
            t = s['end']
        if shots:
            shots[0]['transition_in'] = 'cut'
        tl, errors = planner.retime(tl, cfg)
        p['timeline'] = tl
        p['errors'] = errors
        save(p)
        return dict(timeline=tl, errors=errors)


# ------------------------------------------------------------------ 出片
def render(pid: str, job=None) -> dict:
    p = load(pid)
    tl = p.get('timeline')
    if not tl or not tl.get('shots'):
        raise ValueError('时间线是空的')
    cfg = cfg_of(p)
    root = Path(_output_root()) / '音乐卡点集锦' if _output_root() else _pdir(pid) / 'renders'
    root.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r'[\\/:*?"<>|]+', '_', p['name']).strip() or '集锦'
    out = root / f"{safe}_{time.strftime('%Y%m%d_%H%M%S')}.mp4"
    work = _pdir(pid) / 'work' / 'render'
    shutil.rmtree(work, ignore_errors=True)
    n = len(tl['shots'])
    done = [0]

    def log(msg):
        if msg.startswith('shot '):
            done[0] += 1
        if job:
            job.update(progress=0.05 + 0.85 * done[0] / n, message=f'正在出片：镜头 {done[0]}/{n}' if msg.startswith('shot ') else msg)
            if job.is_cancelled():
                raise RuntimeError('已取消')

    D = render_mod.render(tl, tl['song'], str(out), cfg, str(work), log)
    shutil.rmtree(work, ignore_errors=True)
    item = dict(path=str(out), name=out.name, duration=round(D, 2), at=time.time())
    with _lock:
        cur = load(pid)
        cur.setdefault('renders', []).insert(0, item)
        save(cur)
    return item
