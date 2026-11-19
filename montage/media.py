"""ffmpeg 小工具 + 亚像素缩放。"""
import os
import re
import subprocess

FPS = 60
MI = 'minterpolate=fps=240:mi_mode=mci:mc_mode=aobmc:me_mode=bidir:vsbmc=1'


_major = []


def ffmpeg_major():
    if not _major:
        out = subprocess.run(['ffmpeg', '-version'], capture_output=True, text=True).stdout
        m = re.match(r'ffmpeg version n?(\d+)', out)
        _major.append(int(m.group(1)) if m else 7)
    return _major[0]


def run(args):
    if ffmpeg_major() < 7:     # 老版本没有 -/option 读文件的写法
        args = ['-filter_complex_script' if a == '-/filter_complex' else a for a in args]
    subprocess.run(['ffmpeg', '-v', 'error', '-y'] + args, check=True)


def frames(path):
    return int(subprocess.run(['ffprobe', '-v', 'error', '-count_packets', '-select_streams', 'v', '-show_entries',
                               'stream=nb_read_packets', '-of', 'csv=p=0', path], capture_output=True, text=True).stdout)


def duration(path):
    return float(subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', path],
                                capture_output=True, text=True).stdout)


def has_audio(path):
    return bool(subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'a', '-show_entries', 'stream=index',
                                '-of', 'csv=p=0', path], capture_output=True, text=True).stdout.strip())


def persp(Z, rate, dx='0', dy='0'):
    """亚像素平滑缩放/平移（比 scale eval=frame 顺）。Z/dx/dy 是关于 T（秒）的表达式。"""
    T = f'(in/{rate})'
    z, X, Y = Z.replace('T', T), dx.replace('T', T), dy.replace('T', T)
    q = f'((1-1/({z}))/2)'
    pts = [(f'W*{q}+{X}', f'H*{q}+{Y}'), (f'W*(1-{q})+{X}', f'H*{q}+{Y}'),
           (f'W*{q}+{X}', f'H*(1-{q})+{Y}'), (f'W*(1-{q})+{X}', f'H*(1-{q})+{Y}')]
    s = ':'.join(f"x{i}='{a}':y{i}='{b}'" for i, (a, b) in enumerate(pts))
    return f"perspective={s}:sense=source:eval=frame:interpolation=cubic"


def to_wav(song, workdir):
    """任意歌（.ncm/.mp3/.flac/.wav）-> 48k 立体声 wav。"""
    os.makedirs(workdir, exist_ok=True)
    src = song
    if song.lower().endswith('.ncm'):
        try:
            from . import ncm      # 不随仓库发布；本地自备
        except ImportError:
            raise SystemExit('.ncm 是加密格式，请先转成 mp3/flac 再用（或在本地放置 montage/ncm.py 解码器）')
        src = ncm.decode(song, os.path.join(workdir, 'song_raw'))
    wav = os.path.join(workdir, 'song.wav')
    run(['-i', src, '-ar', '48000', '-ac', '2', wav])
    return wav
