"""时间线规划。输出 timeline.json（人和 agent 都可以直接改，再 retime/render）：

{
  "version": 1, "song": "song.wav", "song_start": 0, "duration": 57.5,
  "shots": [{
      "file": "...高光.mp4", "start": 0.0, "end": 17.52,        # 成片时间
      "kills": [{"src": 62.43, "at": 16.014}, ...],            # 片段内开枪帧 -> 成片里落在哪
      "transition_in": "cut",                                   # cut / push / impact
      "segments": [{"src": [a, b], "speed": [v0, v1]}, ...]     # 由 kills 自动推出，可用 retime 重算
  }]
}
"""
from __future__ import annotations

import math

import numpy as np


# ------------------------------------------------------------------ 变速桥接
def bridge(a, b, out_len, cfg):
    """把素材 [a,b] 放进 out_len 秒。返回 segments 或 None（需要慢放才行 = 不可行）。"""
    g = b - a
    if out_len <= 0 or g <= 0:
        return None
    r = g / out_len
    p = cfg['plan']
    if r < p['speed_min'] - 1e-6:
        return None
    if r <= p['speed_max']:
        return [seg(a, b, r, r)]
    # 快进：击杀后原速 ka -> 匀速 vf -> 平滑减速到 1x（ramp 秒素材）-> 下一击杀前原速 kb
    ka, kb, R = p['ff_keep_after'], p['ff_keep_before'], p['ff_ramp']
    M, O = g - ka - kb, out_len - ka - kb
    if M > R + 0.2 and O > 0.3:
        def out_of(vf):            # 中段在速度 vf 下的成片时长
            return (M - R) / vf + 2 * R / (vf + 1)
        lo, hi = 1.0, p['ff_speed_max']
        if out_of(hi) <= O <= out_of(lo):
            for _ in range(50):
                mid = (lo + hi) / 2
                lo, hi = (mid, hi) if out_of(mid) > O else (lo, mid)
            vf = (lo + hi) / 2
            return [seg(a, a + ka, 1, 1), seg(a + ka, b - kb - R, vf, vf), seg(b - kb - R, b - kb, vf, 1), seg(b - kb, b, 1, 1)]
    if r <= p['ff_speed_max'] and g < 3:
        return [seg(a, b, r, r)]
    return None


def lead_in(k, out_len, cfg, clip_start=0.2):
    """击杀(素材时间 k)前留 out_len 秒成片作为前因；太长时开头快进并平滑减速回 1x。"""
    p = cfg['plan']
    if out_len <= p['lead_realtime_max']:
        return [seg(k - out_len, k, 1, 1)] if k - out_len >= clip_start else None
    keep = p['lead_realtime_keep']
    O1 = out_len - keep
    avail = k - keep - clip_start
    v0 = min(p['ff_speed_max'], 2 * avail / O1 - 1)
    if v0 < 1.0:
        return None
    s1 = O1 * (v0 + 1) / 2
    return [seg(k - keep - s1, k - keep, v0, 1.0), seg(k - keep, k, 1, 1)]


def seg(a, b, v0, v1):
    return dict(src=[round(a, 4), round(b, 4)], speed=[round(v0, 5), round(v1, 5)])


def seg_out(s):
    return 2 * (s['src'][1] - s['src'][0]) / (s['speed'][0] + s['speed'][1])


# ------------------------------------------------------------------ 规划
def pick_targets(song, cfg):
    p = cfg['plan']
    dur = p['duration']
    targets = []
    for a in song['top']:
        t = a['t']
        if p['first_lead'][0] <= t < dur - 2.5 and all(abs(t - q) >= p['target_min_gap'] for q in targets):
            targets.append(t)
    return sorted(targets)


def plan(song, clips, cfg):
    p = cfg['plan']
    dur = p['duration']
    beats = np.array(song['beats'])
    accents = {round(a['t'], 3) for a in song['top']}
    targets = pick_targets(song, cfg)
    downs = [d for d in song['downbeats'] if d < dur - 2.5]

    def next_beat(x):
        i = int(np.searchsorted(beats, x))
        return float(beats[min(i, len(beats) - 1)])

    used, shots, c, tried = set(), [], 0.0, set()
    while c < dur - 6:
        lo, hi = p['first_lead'] if not shots else p['lead']
        nxt = [t for t in targets if t - c >= lo and t not in tried]
        if nxt and nxt[0] - c <= hi + p['fill_gap'] / 2:
            a = nxt[0]
        else:
            fill = [d for d in downs if c + lo + 1 <= d <= c + lo + 4 and d not in tried]
            if fill:
                a = fill[0]
            elif nxt:
                a = nxt[0]
            else:
                break
        tried.add(a)
        best = None
        for ci, cl in enumerate(clips):
            if ci in used:
                continue
            segs = lead_in(cl['kills'][0], a - c, cfg)
            if segs is None:
                continue
            score = len(cl['kills'])
            if best is None or score > best[0]:
                best = (score, ci, segs)
        if best is None:
            continue
        _, ci, segs = best
        used.add(ci)
        cl = clips[ci]
        kills = [dict(src=cl['kills'][0], at=round(float(a), 3))]
        cur_a, cur_k = a, cl['kills'][0]
        for k2 in cl['kills'][1:]:
            if p['kills_per_shot'] and len(kills) >= p['kills_per_shot']:
                break
            if p['chain_max_gap'] and k2 - cur_k > p['chain_max_gap']:
                break
            limit = min(dur - 2.5, c + p['max_shot_len'])
            options = []
            for bt in beats:
                if not (cur_a + 0.3 < bt < limit):
                    continue
                bs = bridge(cur_k, k2, bt - cur_a, cfg)
                if bs is None:
                    continue
                avg = (k2 - cur_k) / (bt - cur_a)
                cost = abs(math.log(avg)) - (p['accent_bonus'] if round(bt, 3) in accents else 0) \
                    - (0.5 if any(abs(bt - t) < 0.05 for t in targets) else 0)
                options.append((cost, bt, bs))
            if not options:
                break
            _, bt, bs = min(options, key=lambda o: o[0])
            segs += bs
            kills.append(dict(src=k2, at=round(float(bt), 3)))
            cur_a, cur_k = bt, k2
        end = next_beat(cur_a + p['tail'])
        end = min(end, cur_a + (cl['dur'] - 0.1 - cur_k))
        segs.append(seg(cur_k, cur_k + (end - cur_a), 1, 1))
        n = len(shots)
        tr = p['transition'] if (n > 0 and p['transition_every'] and n % p['transition_every'] == 0) else 'cut'
        shots.append(dict(file=cl['file'], start=round(c, 4), end=round(end, 4), kills=kills, transition_in=tr, segments=segs))
        c = end
    return dict(version=1, song_start=cfg['song']['start'], duration=round(c, 4), shots=shots)


# ------------------------------------------------------------------ 手动改后重算
def retime(timeline, cfg):
    """按每个镜头的 start/end 和 kills[].at 重新推出 segments。改了落点/删了击杀/换了片段后调用。"""
    errors = []
    t = 0.0
    for i, s in enumerate(timeline['shots']):
        s['start'] = round(t, 4) if i else s.get('start', 0.0)
        ks = sorted(s['kills'], key=lambda k: k['at'])
        segs = lead_in(ks[0]['src'], ks[0]['at'] - s['start'], cfg, clip_start=0.0)
        if segs is None:
            errors.append(f"镜头{i}: 第一个击杀前的素材不够 {ks[0]['at'] - s['start']:.2f}s 前因")
            continue
        for k1, k2 in zip(ks, ks[1:]):
            bs = bridge(k1['src'], k2['src'], k2['at'] - k1['at'], cfg)
            if bs is None:
                errors.append(f"镜头{i}: 击杀 {k1['src']}→{k2['src']} 放进 {k2['at'] - k1['at']:.2f}s 需要慢放或超出快进上限")
                bs = [seg(k1['src'], k2['src'], 1, 1)]
            segs += bs
        tail = s['end'] - ks[-1]['at']
        segs.append(seg(ks[-1]['src'], ks[-1]['src'] + tail, 1, 1))
        s['segments'] = segs
        s['end'] = round(s['start'] + sum(seg_out(x) for x in segs), 4)
        t = s['end']
    timeline['duration'] = round(t, 4)
    return timeline, errors
