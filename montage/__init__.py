"""三角洲集锦 · 音乐卡点剪辑（独立模块）。

Python 用法：
    import montage
    cfg = montage.config.load(override={"plan": {"duration": 45}})
    song = montage.analyze_song("歌.mp3", work, cfg)
    clips = montage.collect_kills("<集锦文件夹>", work, cfg)
    tl = montage.make_plan(song, clips, cfg)          # 可改 tl 再 montage.retime(tl, cfg)
    montage.render_timeline(tl, song["path"], "out.mp4", cfg, work)

命令行见 `python -m montage -h`。
"""
import json
import os

from . import config, kills, planner, render, song as song_mod
from .media import to_wav

__all__ = ['config', 'analyze_song', 'collect_kills', 'make_plan', 'retime', 'render_timeline', 'run_all']


def analyze_song(song_path, workdir, cfg=None):
    cfg = cfg or config.load()
    wav = to_wav(song_path, workdir)
    info = song_mod.analyze(wav, cfg)
    song_mod.save(info, os.path.join(workdir, 'song.json'))
    return info


def collect_kills(root, workdir, cfg=None):
    cfg = cfg or config.load()
    clips = kills.from_archive(root, cfg['kills'])
    kills.save(clips, os.path.join(workdir, 'kills.json'))
    return clips


def make_plan(song, clips, cfg=None, workdir=None):
    cfg = cfg or config.load()
    tl = planner.plan(song, clips, cfg)
    tl['song'] = song['path']
    if workdir:
        save_timeline(tl, os.path.join(workdir, 'timeline.json'))
    return tl


def retime(timeline, cfg=None):
    return planner.retime(timeline, cfg or config.load())


def render_timeline(timeline, song_wav, out, cfg=None, workdir=None, log=print):
    cfg = cfg or config.load()
    return render.render(timeline, song_wav, out, cfg, workdir or os.path.splitext(out)[0] + '_work', log)


def run_all(song_path, root, out, cfg=None, workdir=None, log=print):
    cfg = cfg or config.load()
    workdir = workdir or os.path.splitext(out)[0] + '_work'
    s = analyze_song(song_path, workdir, cfg)
    c = collect_kills(root, workdir, cfg)
    tl = make_plan(s, c, cfg, workdir)
    D = render_timeline(tl, s['path'], out, cfg, workdir, log)
    return dict(output=out, duration=D, timeline=os.path.join(workdir, 'timeline.json'))


def save_timeline(tl, path):
    json.dump(tl, open(path, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)


def load_timeline(path):
    return json.load(open(path, encoding='utf-8'))
