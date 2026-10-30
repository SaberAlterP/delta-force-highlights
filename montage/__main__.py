"""命令行：python -m montage <命令> ...   （在仓库根目录运行；Windows 建议加 -X utf8）

  run      一键：歌 + 集锦文件夹 -> 成片
  analyze  只分析歌 -> work/song.json
  kills    只提取击杀 -> work/kills.json
  plan     song.json + kills.json -> work/timeline.json（可手动/agent 修改）
  retime   改完 timeline.json 后重算变速
  render   timeline.json -> 成片

通用参数：--work 工作目录  --config 配置 JSON  --set plan.duration=45 （可多次，覆盖任意配置项）
"""
import argparse
import json
import os
import sys

from . import analyze_song, collect_kills, config, load_timeline, make_plan, render_timeline, retime, run_all, save_timeline
from . import kills as kills_mod, song as song_mod


def parse_set(items):
    over = {}
    for it in items or []:
        key, val = it.split('=', 1)
        try:
            val = json.loads(val)
        except ValueError:
            pass
        d = over
        ks = key.split('.')
        for k in ks[:-1]:
            d = d.setdefault(k, {})
        d[ks[-1]] = val
    return over


def main(argv=None):
    ap = argparse.ArgumentParser(prog='montage', description='三角洲集锦音乐卡点剪辑')
    ap.add_argument('cmd', choices=['run', 'analyze', 'kills', 'plan', 'retime', 'render'])
    ap.add_argument('--song', help='歌曲 .mp3/.flac/.wav')
    ap.add_argument('--root', help='集锦包根目录（平台设置里的集锦文件夹）')
    ap.add_argument('--out', help='输出 mp4')
    ap.add_argument('--work', help='工作目录（中间文件）')
    ap.add_argument('--timeline', help='timeline.json 路径（默认 work/timeline.json）')
    ap.add_argument('--config')
    ap.add_argument('--set', action='append', help='覆盖配置，如 plan.duration=45 plan.kills_per_shot=2 render.hq=true')
    a = ap.parse_args(argv)
    cfg = config.load(a.config, parse_set(a.set))
    work = a.work or (os.path.splitext(a.out)[0] + '_work' if a.out else 'montage_work')
    os.makedirs(work, exist_ok=True)
    tl_path = a.timeline or os.path.join(work, 'timeline.json')

    if a.cmd == 'run':
        r = run_all(a.song, a.root, a.out, cfg, work)
        print_timeline(load_timeline(r['timeline']))
        print('done', r['output'], round(r['duration'], 2), 's')
    elif a.cmd == 'analyze':
        s = analyze_song(a.song, work, cfg)
        print('BPM', s['bpm'], '最重:', [p['t'] for p in s['top'][:8]])
    elif a.cmd == 'kills':
        c = collect_kills(a.root, work, cfg)
        print(f'{len(c)} 段高光，{sum(len(x["kills"]) for x in c)} 个击杀 -> {os.path.join(work, "kills.json")}')
    elif a.cmd == 'plan':
        s = song_mod.load(os.path.join(work, 'song.json'))
        c = kills_mod.load(os.path.join(work, 'kills.json'))
        tl = make_plan(s, c, cfg)
        save_timeline(tl, tl_path)
        print_timeline(tl)
    elif a.cmd == 'retime':
        tl, errs = retime(load_timeline(tl_path), cfg)
        save_timeline(tl, tl_path)
        print_timeline(tl)
        for e in errs:
            print('!!', e)
    elif a.cmd == 'render':
        tl = load_timeline(tl_path)
        D = render_timeline(tl, tl['song'], a.out, cfg, work)
        print('done', a.out, round(D, 2), 's')


def print_timeline(tl):
    for i, s in enumerate(tl['shots']):
        sp = ' '.join(f"[{x['src'][0]:.2f}-{x['src'][1]:.2f} x{x['speed'][0]:.2f}->{x['speed'][1]:.2f}]" for x in s['segments'])
        print(f"{i:2d} {s['start']:6.2f}-{s['end']:6.2f} {s.get('transition_in', 'cut'):6s} {os.path.basename(s['file'])[:26]} "
              f"击杀@{[k['at'] for k in s['kills']]}  {sp}")
    print('总长', tl['duration'])


if __name__ == '__main__':
    sys.exit(main())
