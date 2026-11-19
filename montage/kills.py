"""击杀素材：从集锦包自动提取，或手动给出。

输出 kills.json：
[{"file": "...高光.mp4", "dur": 88.9, "kills": [62.43, 79.81, 83.83], "source": "archive"}]
kills 里是片段内的**开枪画面帧**时间（秒）。手动模式直接写这个格式即可。
"""
import glob
import json
import os
import re
import subprocess

import numpy as np


def gunshots(f, t0, t1):
    t0 = max(0.0, t0)
    a = subprocess.run(['ffmpeg', '-v', 'error', '-ss', f'{t0:.3f}', '-t', f'{t1 - t0:.3f}', '-i', f, '-ac', '1', '-ar', '16000',
                        '-af', 'highpass=f=300', '-f', 's16le', '-'], capture_output=True).stdout
    a = np.frombuffer(a, np.int16).astype(float) / 32768
    hop = 48                                   # 3ms
    n = len(a) // hop
    if n < 3:
        return []
    e = 20 * np.log10(np.sqrt((a[:n * hop].reshape(n, hop) ** 2).mean(1)) + 1e-9)
    d = np.diff(e, prepend=e[0])
    return [t0 + i * 0.003 for i in range(n) if d[i] > 8 and e[i] > e.max() - 15]


def shot_time(f, verification_t, cfg):
    """官方 time 是倒地者最终死亡时刻，不准；用画面提示时刻前的最后一声枪响。"""
    w = cfg['shot_window']
    shots = gunshots(f, verification_t - w, verification_t + 0.02)
    t = shots[-1] if shots else verification_t - cfg['fallback_lead']
    return round(t - cfg['av_offset'], 3)


def from_archive(root, cfg):
    """扫描平台的集锦包文件夹：每局一个文件夹，含 识别记录.json 和 *_高光_起-止s.mp4。"""
    clips = []
    for d in sorted(glob.glob(os.path.join(root, '*'))):
        rec = os.path.join(d, '识别记录.json')
        if not os.path.isfile(rec):
            continue
        r = json.load(open(rec, encoding='utf-8'))
        marks = [m for m in r.get('marks', []) if m.get('event_type') == 'kill'
                 and (m.get('confirmed') or not cfg['only_confirmed'])]
        for f in sorted(glob.glob(os.path.join(d, '*_高光_*.mp4'))):
            m = re.search(r'_高光_([\d.]+)-([\d.]+)s', os.path.basename(f))
            if not m:
                continue
            a, b = float(m.group(1)), float(m.group(2))
            ks = []
            for mk in marks:
                vt = mk.get('verification_time')
                if vt is None or not (a + 0.5 <= vt <= b):
                    continue
                ks.append(shot_time(f, vt - a, cfg))
            ks = sorted(ks)
            ks = [k for i, k in enumerate(ks) if i == 0 or k - ks[i - 1] > cfg['merge_within']]
            if ks:
                clips.append(dict(file=f, dur=round(b - a, 3), kills=ks, source='archive', match=os.path.basename(d)))
    return clips


def _bundle_marks(d, cfg, cache):
    if d not in cache:
        rec = os.path.join(d, '识别记录.json')
        marks = []
        if os.path.isfile(rec):
            r = json.load(open(rec, encoding='utf-8'))
            marks = [m for m in r.get('marks', []) if m.get('event_type') == 'kill'
                     and (m.get('confirmed') or not cfg['only_confirmed'])]
        cache[d] = marks
    return cache[d]


def from_files(files, cfg, manual=None, durations=None):
    """任意挑选的素材文件。集锦包里的高光 / 整局原片自动读识别记录；
    manual = {文件: [开枪帧秒数...]} 手动标的击杀（优先）。没有击杀的文件跳过。"""
    manual, durations, cache = manual or {}, durations or {}, {}
    clips = []
    for f in files:
        dur = durations.get(f)
        if f in manual and manual[f]:
            ks, source = sorted(float(k) for k in manual[f]), 'manual'
        else:
            base = os.path.basename(f)
            m = re.search(r'_高光_([\d.]+)-([\d.]+)s', base)
            if m:
                a, b = float(m.group(1)), float(m.group(2))
            elif base.startswith('整局原录像') and dur:
                a, b = 0.0, dur
            else:
                continue
            ks = [shot_time(f, mk['verification_time'] - a, cfg) for mk in _bundle_marks(os.path.dirname(f), cfg, cache)
                  if mk.get('verification_time') is not None and a + 0.5 <= mk['verification_time'] <= b]
            ks, source, dur = sorted(ks), 'archive', dur or round(b - a, 3)
        ks = [k for i, k in enumerate(ks) if i == 0 or k - ks[i - 1] > cfg['merge_within']]
        if ks and dur:
            clips.append(dict(file=f, dur=round(dur, 3), kills=ks, source=source))
    return clips


def save(clips, path):
    json.dump(clips, open(path, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)


def load(path):
    return json.load(open(path, encoding='utf-8'))
