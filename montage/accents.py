"""找一首歌里听感最"重"的重音（给击杀卡点用）。

python accents.py song.wav out.json [--top 12]

方法（2026-10 在《柳宗元进行曲》上验证：用户听感最重的 15.2s 排在前列）：
1. 节拍网格对准底鼓：用 30-120Hz 低频 onset 做节拍跟踪，再判断网格是否落在反拍（librosa 默认常错半拍），
   每拍吸附到最近的底鼓瞬态起点（±70ms）。
2. "重"按反差算，不按绝对响度（很多歌被压限到每拍一样响）：
   该点 80ms 内的峰值 vs 前 2 秒（去掉最后 0.1s）的平均，分别看低频、全频、高频(镲片)；
   再加瞬态强度(谱通量)、绝对低频峰值、结构位置(小节线/4、8 小节句首)。
3. 只按公式排序，不人工加分。网格外的大冲击（谱通量 99 分位以上）也作为候选。
"""
import json, sys
import numpy as np
import librosa

SR = 22050
HOP = 110          # ~5ms


def band_db(S, freqs, lo, hi):
    m = (freqs >= lo) & (freqs < hi)
    return 10 * np.log10(S[m].sum(0) + 1e-10)


def analyze(path, top=12):
    y, _ = librosa.load(path, sr=SR, mono=True)
    D = np.abs(librosa.stft(y, n_fft=2048, hop_length=HOP)) ** 2
    freqs = librosa.fft_frequencies(sr=SR, n_fft=2048)
    t = librosa.frames_to_time(np.arange(D.shape[1]), sr=SR, hop_length=HOP)
    low = band_db(D, freqs, 30, 120)
    mid = band_db(D, freqs, 150, 2500)
    high = band_db(D, freqs, 4000, 11000)
    full = 10 * np.log10(D.sum(0) + 1e-10)
    logS = np.log1p(D / (D.mean() + 1e-12))
    flux = np.maximum(0, np.diff(logS, axis=1, prepend=logS[:, :1])).sum(0)
    low_on = np.maximum(0, np.diff(low, prepend=low[0]))

    # ---- 节拍网格（对准底鼓）
    tempo, beats = librosa.beat.beat_track(onset_envelope=low_on, sr=SR, hop_length=HOP, units='frames', tightness=200)
    tempo = float(np.atleast_1d(tempo)[0])
    period = 60.0 / tempo
    bt = t[beats]
    def strength(times):
        idx = np.searchsorted(t, times)
        return np.array([low_on[max(0, i - 6):i + 14].max() for i in idx])
    half = bt + period / 2
    half = half[half < t[-1]]
    if strength(half).mean() > strength(bt).mean() * 1.15:   # 网格落在反拍上，挪半拍
        bt = half
    snapped = []
    for b in bt:
        i0, i1 = np.searchsorted(t, b - 0.07), np.searchsorted(t, b + 0.07)
        if i1 <= i0:
            continue
        j = i0 + int(np.argmax(low_on[i0:i1]))
        snapped.append(float(t[j]))
    snapped = np.array(snapped)

    # ---- 小节线相位：每拍和声变化(chroma 新颖度)最大的那个 mod-4 相位
    chroma = librosa.feature.chroma_stft(y=y, sr=SR, hop_length=HOP)
    bi = np.searchsorted(t, snapped)
    cb = np.array([chroma[:, max(0, i - 40):i + 40].mean(1) for i in bi])
    nov = np.r_[0, np.linalg.norm(np.diff(cb, axis=0), axis=1)]
    lowpk = strength(snapped)
    phase = int(np.argmax([nov[p::4].mean() + 0.3 * lowpk[p::4].mean() / (lowpk.mean() + 1e-9) for p in range(4)]))
    beat_no = (np.arange(len(snapped)) - phase)

    # ---- 候选：吸附后的拍 + 网格外大冲击
    thr = np.percentile(flux, 99)
    extra = []
    for i in range(1, len(flux) - 1):
        if flux[i] >= thr and flux[i] >= flux[i - 1] and flux[i] >= flux[i + 1]:
            if np.min(np.abs(snapped - t[i])) > 0.09:
                extra.append(float(t[i]))
    # 所有明显的底鼓瞬态（断层后网格会漂，真正砸回来的那下可能不在网格上）
    kthr = np.percentile(low_on, 97)
    for i in range(1, len(low_on) - 1):
        if low_on[i] >= kthr and low_on[i] >= low_on[i - 1] and low_on[i] >= low_on[i + 1]:
            if np.min(np.abs(snapped - t[i])) > 0.09 and all(abs(e - t[i]) > 0.09 for e in extra):
                extra.append(float(t[i]))
    def grid_no(x):
        j = int(np.argmin(np.abs(snapped - x)))
        return j if abs(snapped[j] - x) < 0.12 else None
    cands = [(float(s), j) for j, s in enumerate(snapped)] + [(e, grid_no(e)) for e in extra]
    cands = [c for c in cands if c[0] > 2.5 and c[0] < t[-1] - 1.0]

    def feat(tc):
        i = np.searchsorted(t, tc)
        win = slice(i, min(len(t), i + 16))                       # 80ms
        pre = slice(np.searchsorted(t, tc - 2.0), max(np.searchsorted(t, tc - 2.0) + 1, np.searchsorted(t, tc - 0.3)))   # 避开弱起(808 先进来)
        c_low = low[win].max() - low[pre].mean()
        c_full = full[win].max() - full[pre].mean()
        c_high = high[win].max() - high[pre].mean()
        return [c_low, c_full, c_high, flux[win].max(), low[win].max()]

    F = np.array([feat(c[0]) for c in cands])
    R = np.zeros_like(F)
    for k in range(F.shape[1]):
        R[:, k] = (np.argsort(np.argsort(F[:, k])) / max(1, len(F) - 1))   # 百分位排名，避免量纲问题
    gi = [k for k, c in enumerate(cands) if c[1] is not None]
    topk = sorted(gi, key=lambda k: -F[k, 0])[:12]
    def mode(vals):
        return max(set(vals), key=vals.count)
    ph4 = mode([cands[k][1] % 4 for k in topk])
    ph16 = mode([(cands[k][1] - ph4) % 16 for k in topk[:6]]) + ph4
    struct = []
    for _, j in cands:
        b = None if j is None else j - ph16
        if b is None:
            struct.append(0.0)
        elif b % 32 == 0:
            struct.append(1.0)
        elif b % 16 == 0:
            struct.append(0.8)
        elif b % 4 == 0:
            struct.append(0.5)
        else:
            struct.append(0.0)
    struct = np.array(struct)
    score = 100 * (0.30 * R[:, 0] + 0.15 * R[:, 1] + 0.15 * R[:, 2] + 0.15 * R[:, 3] + 0.10 * R[:, 4] + 0.15 * struct)
    # 绝对差值本身也很重要：低频反差 > 6dB 的额外加权（断层后砸回来）
    score += np.clip(F[:, 0] - 6, 0, 10) * 2
    score *= np.array([1.0 if c[1] is not None else 0.85 for c in cands])   # 网格外的点卡上去像不在拍上，打折

    # 连续几拍都很重时（drop 之后每拍都比前面的断层响），取第一拍：往前一拍的点分数不低于 85% 就让给它
    times = np.array([c[0] for c in cands])
    best = score.copy()
    for i in np.argsort(times)[::-1]:
        prev = [k for k in range(len(cands)) if cands[k][1] is not None and 0.3 < times[i] - times[k] < period * 1.25]
        if prev:
            k = max(prev, key=lambda k: score[k])
            if score[k] >= 0.85 * score[i] and cands[i][1] is not None:
                score[k] = max(score[k], score[i] + 0.1)
                score[i] = score[i] * 0.9
    order = np.argsort(-score)
    picked = []
    for i in order:
        tc = cands[i][0]
        if all(abs(tc - p['t']) > 1.5 for p in picked):
            picked.append(dict(t=round(tc, 3), score=round(float(score[i]), 1), low_contrast_db=round(float(F[i, 0]), 1),
                               full_contrast_db=round(float(F[i, 1]), 1), high_contrast_db=round(float(F[i, 2]), 1),
                               bar_pos=None if cands[i][1] is None else int((cands[i][1] - ph4) % 4), on_grid=cands[i][1] is not None))
        if len(picked) >= top:
            break
    # 小节线：以最终最重的几个网格点为准（drop 第一拍一定是小节第一拍）
    gidx = [int(np.argmin(np.abs(snapped - p['t']))) for p in picked[:6] if p['on_grid']]
    if gidx:
        ph4 = mode([g % 4 for g in gidx])
    for p in picked:
        if p['on_grid']:
            p['bar_pos'] = int((int(np.argmin(np.abs(snapped - p['t']))) - ph4) % 4)
    downbeats = [round(float(x), 3) for j, x in enumerate(snapped) if (j - ph4) % 4 == 0]
    return dict(bpm=round(60 / np.median(np.diff(snapped)), 2), beats=[round(float(s), 3) for s in snapped],
                downbeats=downbeats, top=picked)


if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('song'); ap.add_argument('out'); ap.add_argument('--top', type=int, default=12)
    a = ap.parse_args()
    r = analyze(a.song, a.top)
    json.dump(r, open(a.out, 'w'), indent=1)
    print('BPM', r['bpm'])
    for p in r['top']:
        print(f"{p['t']:8.3f}  score {p['score']:5.1f}  low +{p['low_contrast_db']}dB  full +{p['full_contrast_db']}dB  high +{p['high_contrast_db']}dB  grid={p['on_grid']}")
