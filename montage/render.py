"""按 timeline.json 出片。"""
import json
import os

from .media import FPS, MI, duration as media_duration, frames, has_audio, persp, run
from .planner import seg_out


def _mblur(chain):
    return f"fps=240,{chain},tmix=frames=4,fps=60"


# 镜头入场（上一镜头结尾配合推镜）效果；都在 240fps 下做，带运动模糊
HEADS = {
    'push': (0.4, _mblur(persp("1+0.5*pow(max(0,1-T/0.4),3)", 240))),
    'impact': (0.6, persp("1+0.2*pow(max(0,1-T/0.35),2)+0.05*exp(-8*T)", 60,
                          dx="40*exp(-8*T)*sin(70*T)", dy="30*exp(-8*T)*cos(55*T)")
               + ",eq=brightness='0.6*pow(max(0,1-t/0.15),2)':eval=frame"),
    'flash': (0.35, "eq=brightness='0.75*pow(max(0,1-t/0.3),2)':eval=frame"),
    'dip': (0.3, "eq=brightness='-pow(max(0,1-t/0.3),2)':eval=frame"),
    'whip': (0.3, _mblur(persp("1.04", 240, dx="-0.3*W*pow(max(0,1-T/0.3),3)"))),
}
# 上一镜头结尾配合下一镜头的入场
TAILS = {
    'push': (0.25, _mblur(persp("1+0.5*pow(T/0.25,3)", 240))),
    'dip': (0.2, "eq=brightness='-pow(t/0.2,2)':eval=frame"),
    'whip': (0.2, _mblur(persp("1.04", 240, dx="0.3*W*pow(T/0.2,3)"))),
}
TRANSITIONS = ['cut'] + list(HEADS)
OPENINGS = ['fade_blur', 'flash', 'zoom', 'none']
ENDINGS = ['fade', 'blur', 'none']
FONTS = ['C:/Windows/Fonts/msyhbd.ttc', 'C:/Windows/Fonts/msyh.ttc', 'C:/Windows/Fonts/simhei.ttf',
         '/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc', '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf']


def _opening(kind):
    if kind == 'fade_blur':
        return (f",split=2[o1][o2];[o2]scale=480:-2,gblur=sigma=10,scale=1920:1080[ob];"
                f"[o1][ob]blend=all_expr='A*min(1,T/1.2)+B*max(0,1-T/1.2)',{persp('1+0.15*pow(max(0,1-T/1.6),2)', 60)},"
                "eq=brightness='-0.9*pow(max(0,1-t/1.0),2)':eval=frame")
    if kind == 'flash':
        return ",eq=brightness='pow(max(0,1-t/0.6),2)':eval=frame"
    if kind == 'zoom':
        return f",{persp('1+0.6*pow(max(0,1-T/1.2),3)', 60)},eq=brightness='-pow(max(0,1-t/0.5),2)':eval=frame"
    return ''


def _ending(kind, L, d):
    st = max(0.0, L - d)
    if kind == 'fade':
        return f",fade=t=out:st={st:.3f}:d={d}"
    if kind == 'blur':
        return (f",split=2[e1][e2];[e2]scale=480:-2,gblur=sigma=12,scale=1920:1080[eb];"
                f"[e1][eb]blend=all_expr='A*(1-clip((T-{st:.3f})/{d * 0.6:.3f},0,1))+B*clip((T-{st:.3f})/{d * 0.6:.3f},0,1)',"
                f"fade=t=out:st={st + d * 0.5:.3f}:d={d * 0.5:.3f}")
    return ''


def _font(path=None):
    for f in ([path] if path else []) + FONTS:
        if f and os.path.isfile(f):
            return f
    return None


def _title(text, font, dur=3.0):
    """片头标题：淡入淡出的大字。路径里的冒号要转义；文字里的特殊字符直接去掉。"""
    if not text or not font:
        return ''
    font = font.replace('\\', '/').replace(':', '\\:')
    txt = ''.join(ch for ch in text.replace(':', '：') if ch not in "\\'%{}")
    a = f"if(lt(t,0.4),t/0.4,if(lt(t,{dur - 0.5:.2f}),1,max(0,({dur:.2f}-t)/0.5)))"
    return (f",drawtext=fontfile='{font}':text='{txt}':fontsize=96:fontcolor=white:borderw=4:bordercolor=black@0.6"
            f":x=(w-text_w)/2:y=(h-text_h)/2:alpha='{a}':enable='lt(t,{dur:.2f})'")


def render_shot(i, shot, n_shots, next_tr, out, cfg):
    r = cfg['render']
    segs = shot['segments']
    src0 = min(s['src'][0] for s in segs)
    src1 = max(s['src'][1] for s in segs)
    v = [f"[0:v]fps=60,scale=1920:1080,format=yuv444p,setsar=1,split={len(segs)}" + ''.join(f'[s{j}]' for j in range(len(segs)))]
    a = [f"[0:a]aresample=48000,asplit={len(segs)}" + ''.join(f'[r{j}]' for j in range(len(segs)))]
    nL = 0
    for j, s in enumerate(segs):
        n = round(seg_out(s) * FPS)
        nL += n
        t0, t1 = s['src'][0] - src0, s['src'][1] - src0
        v0, v1 = s['speed']
        ch = f"[s{j}]trim={t0:.4f}:{t1:.4f},setpts=PTS-STARTPTS"
        if not (abs(v0 - 1) < 1e-3 and abs(v1 - 1) < 1e-3):
            d = seg_out(s)
            acc = (v1 - v0) / d
            pts = f"PTS/{v0:.6f}" if abs(acc) < 1e-9 else f"(-{v0:.6f}+sqrt({v0:.6f}*{v0:.6f}+2*{acc:.6f}*PTS*TB))/{acc:.6f}/TB"
            ch += (f",{MI}" if r['hq'] else '') + f",setpts='{pts}',fps=240,tmix=frames=4"
            if max(v0, v1) >= 2.5 and r['ff_blur']:
                ch += f",gblur=sigma={r['ff_blur']}"
        ch += f",fps=60,tpad=stop_mode=clone:stop_duration=0.3,trim=end_frame={n},setpts=PTS-STARTPTS[p{j}]"
        v.append(ch)
        x = (s['src'][1] - s['src'][0]) / seg_out(s)
        at = ''
        while x > 2:
            at += ',atempo=2'; x /= 2
        while x < 0.5:
            at += ',atempo=0.5'; x /= 0.5
        vol = ',volume=0.35' if max(v0, v1) >= 2.5 else ''
        a.append(f"[r{j}]atrim={t0:.4f}:{t1:.4f},asetpts=PTS-STARTPTS{at},atempo={x:.5f}{vol},apad,atrim=end={n / FPS:.5f}[q{j}]")
    L = nL / FPS
    v.append(''.join(f'[p{j}]' for j in range(len(segs))) + f"concat=n={len(segs)}:v=1:a=0[cat]")
    # 入场 / 结尾推镜 / 开头 / 淡出
    head = HEADS.get(shot.get('transition_in')) if i > 0 else None
    tail = TAILS.get(next_tr)
    parts, labs = [], []
    hs = head[0] if head else 0
    ts = tail[0] if tail else 0
    cuts = ([('h', 0, hs, head[1])] if head else []) + [('m', hs, L - ts, None)] + ([('t', L - ts, L, tail[1])] if tail else [])
    if len(cuts) > 1:
        parts.append(f"[cat]split={len(cuts)}" + ''.join(f'[c{x[0]}]' for x in cuts))
        for name, s0, s1, fx in cuts:
            parts.append(f"[c{name}]trim={s0:.4f}:{s1:.4f},setpts=PTS-STARTPTS" + (f",{fx}" if fx else '') + f"[d{name}]")
            labs.append(f'[d{name}]')
        parts.append(''.join(labs) + f"concat=n={len(cuts)}:v=1:a=0[cat2]")
        last = '[cat2]'
    else:
        last = '[cat]'
    post = ''
    if i == 0:
        post += _opening(r['opening']) + _title(r.get('title'), _font(r.get('font')))
    if i == n_shots - 1 and r['fade_out'] and r.get('ending', 'fade') != 'none':
        post += _ending(r.get('ending', 'fade'), L, r['fade_out'])
    parts.append(f"{last}null{post},trim=end_frame={nL},format=yuv420p[v]")
    a.append(''.join(f'[q{j}]' for j in range(len(segs))) + f"concat=n={len(segs)}:v=0:a=1,apad,atrim=end={L:.5f}[a]")
    g = ';'.join(v + parts + a)
    gp = out + '.txt'
    open(gp, 'w', encoding='utf-8').write(g)
    run(['-ss', f'{src0:.4f}', '-t', f'{src1 - src0 + 0.3:.4f}', '-i', shot['file'], '-/filter_complex', gp, '-map', '[v]', '-map', '[a]',
         '-c:v', 'libx264', '-preset', 'medium' if r['hq'] else r['preset'], '-crf', str(r['crf']), '-r', '60',
         '-c:a', 'pcm_s16le', '-ar', '48000', '-ac', '2', out])


def render(timeline, song_wav, out, cfg, workdir, log=print):
    os.makedirs(workdir, exist_ok=True)
    shots = timeline['shots']
    outs = []
    for i, s in enumerate(shots):
        o = os.path.join(workdir, f'shot{i:02d}.mkv')
        nxt = shots[i + 1].get('transition_in') if i + 1 < len(shots) else None
        render_shot(i, s, len(shots), nxt, o, cfg)
        outs.append(o)
        log(f'shot {i + 1}/{len(shots)}')
    lst = os.path.join(workdir, 'shots.txt')
    open(lst, 'w', encoding='utf-8').write(''.join(f"file '{os.path.abspath(o)}'\n" for o in outs))
    joined = os.path.join(workdir, 'joined.mkv')
    run(['-f', 'concat', '-safe', '0', '-i', lst, '-c', 'copy', joined])
    D = frames(joined) / FPS
    r = cfg['render']
    st = timeline.get('song_start', 0)
    run(['-i', joined, '-ss', f'{st:.3f}', '-i', song_wav, '-filter_complex',
         f"[0:a]loudnorm=I=-20:TP=-3,aresample=48000[g];[g]asplit[g1][g2];"
         f"[1:a]atrim=0:{D:.3f},afade=t=out:st={max(0, D - r['fade_out']):.3f}:d={r['fade_out']},volume={r['music_volume']}[m];"
         f"[m][g1]sidechaincompress=threshold=0.12:ratio=2:attack=5:release=200[duck];"
         f"[duck][g2]amix=inputs=2:normalize=0:weights=1 {r['game_volume']},alimiter=limit=0.95[a]",
         '-map', '0:v', '-map', '[a]', '-c:v', 'copy', '-c:a', 'aac', '-b:a', '256k', '-movflags', '+faststart', out])
    bumpers = [p for p in (r.get('intro_video'), out, r.get('outro_video')) if p]
    if len(bumpers) > 1:
        log('拼接片头 / 片尾视频')
        body = os.path.join(workdir, 'body.mp4')
        os.replace(out, body)
        attach([body if p == out else p for p in bumpers], out, r)
    return D


def attach(files, out, r):
    """自定义片头 / 片尾视频和成片首尾相接：统一成 1080p60、48k 立体声；没有声音的补静音。"""
    args, chains = [], []
    for j, f in enumerate(files):
        args += ['-i', f]
        chains.append(f"[{j}:v]scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:-1:-1,"
                      f"fps=60,setsar=1,format=yuv420p[v{j}]")
        if has_audio(f):
            chains.append(f"[{j}:a]aresample=48000,aformat=channel_layouts=stereo[a{j}]")
        else:
            chains.append(f"anullsrc=r=48000:cl=stereo,atrim=0:{media_duration(f):.3f}[a{j}]")
    chains.append(''.join(f'[v{j}][a{j}]' for j in range(len(files))) + f"concat=n={len(files)}:v=1:a=1[v][a]")
    run(args + ['-filter_complex', ';'.join(chains), '-map', '[v]', '-map', '[a]', '-c:v', 'libx264',
                '-preset', r['preset'], '-crf', str(r['crf']), '-c:a', 'aac', '-b:a', '256k', '-movflags', '+faststart', out])
