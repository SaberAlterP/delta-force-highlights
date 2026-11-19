"""把视频重新编码成小文件，方便发给别人。

- 输出 H.264 + AAC 的 MP4（微信 / QQ / 浏览器都能直接播），带 +faststart。
- 分辨率只缩不放，帧率只降不升。
- 有 NVIDIA 显卡时优先用 h264_nvenc，失败自动退回 libx264。
- 「指定大小」按时长算码率，压完超出目标会再降一次码率重压。
"""
from __future__ import annotations

import math
import shutil
import subprocess
import threading
import time
import uuid
from concurrent.futures import CancelledError
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .video import probe

VIDEO_EXTS = {'.mp4', '.mkv', '.mov', '.avi', '.flv', '.ts', '.m4v', '.webm', '.wmv'}


@dataclass(frozen=True)
class Preset:
    key: str
    label: str
    hint: str
    max_height: int = 0
    max_fps: float = 0
    crf: int = 0
    audio_kbps: int = 128


PRESETS = {
    p.key: p for p in (
        Preset('hd', '高清', '最高 1080p，画质几乎不变，体积约为原来的一半以下', 1080, 60, 23, 160),
        Preset('share', '分享', '最高 720p，手机上看很清楚，适合发微信 / QQ', 720, 60, 26, 128),
        Preset('small', '最小', '最高 540p、30 帧，体积最小，画面会糊一些', 540, 30, 30, 96),
        Preset('target', '指定大小', '按你填的大小（MB）自动算码率和分辨率', 0, 0, 0, 96),
    )
}


def presets() -> list[dict]:
    return [dict(key=p.key, label=p.label, hint=p.hint) for p in PRESETS.values()]


def _ffmpeg() -> str:
    exe = shutil.which('ffmpeg')
    if exe is None:
        raise RuntimeError('未找到 ffmpeg，请先安装并加入 PATH（见 README）。')
    return exe


_nvenc: dict[str, bool] = {}


def nvenc_available() -> bool:
    """ffmpeg 编进了 h264_nvenc 且真能开起来（有显卡和驱动）才算可用；结果缓存。"""
    if 'ok' not in _nvenc:
        try:
            out = subprocess.run(
                [_ffmpeg(), '-hide_banner', '-loglevel', 'error', '-f', 'lavfi', '-i',
                 'color=c=black:s=256x256:d=0.1', '-c:v', 'h264_nvenc', '-f', 'null', '-'],
                capture_output=True, timeout=20)
            _nvenc['ok'] = out.returncode == 0
        except (OSError, RuntimeError, subprocess.SubprocessError):
            _nvenc['ok'] = False
    return _nvenc['ok']


def target_plan(duration: float, target_mb: float, src_height: int, src_fps: float) -> dict:
    """按目标大小算视频码率，并据此挑合适的分辨率和帧率（码率太低时 1080p 会满屏马赛克）。"""
    if target_mb <= 0:
        raise ValueError('目标大小要大于 0')
    duration = max(duration, 0.5)
    audio_kbps = 96 if target_mb * 8192 / duration > 600 else 64
    # 留 4% 给封装开销
    total_kbps = target_mb * 8192 * 0.96 / duration
    video_kbps = int(total_kbps - audio_kbps)
    if video_kbps < 150:
        need = (150 + audio_kbps) * duration / 8192 / 0.96
        raise ValueError(f'这段视频有 {duration:.0f} 秒，压到 {target_mb:g} MB 画面会糊得没法看，'
                         f'至少要 {math.ceil(need)} MB')
    if video_kbps >= 4500:
        height = 1080
    elif video_kbps >= 2000:
        height = 720
    elif video_kbps >= 900:
        height = 540
    else:
        height = 480
    fps = 60 if video_kbps >= 3000 else 30
    return dict(video_kbps=video_kbps, audio_kbps=audio_kbps,
                max_height=min(height, src_height) if src_height else height,
                max_fps=min(fps, src_fps) if src_fps else fps)


def build_command(src: Path, out: Path, info: dict, preset: str, *, target_mb: float = 0,
                  video_kbps: int = 0, gpu: bool = False) -> list[str]:
    p = PRESETS.get(preset)
    if p is None:
        raise ValueError(f'未知的压缩档位：{preset}')
    src_h, src_fps = int(info.get('height') or 0), float(info.get('fps') or 0)
    if p.key == 'target':
        plan = target_plan(float(info.get('duration') or 0), target_mb, src_h, src_fps)
        max_h, max_fps, audio = plan['max_height'], plan['max_fps'], plan['audio_kbps']
        video_kbps = video_kbps or plan['video_kbps']
    else:
        max_h, max_fps, audio = p.max_height, p.max_fps, p.audio_kbps

    filters = []
    if src_h and max_h and src_h > max_h:
        filters.append(f'scale=-2:{max_h}:flags=lanczos')
    if src_fps and max_fps and src_fps > max_fps + 0.5:
        filters.append(f'fps={max_fps:g}')

    cmd = [_ffmpeg(), '-hide_banner', '-y', '-i', str(src), '-map', '0:v:0', '-map', '0:a:0?']
    if filters:
        cmd += ['-vf', ','.join(filters)]
    if gpu:
        cmd += ['-c:v', 'h264_nvenc', '-preset', 'p6', '-tune', 'hq', '-profile:v', 'high']
        if video_kbps:
            cmd += ['-rc', 'vbr', '-b:v', f'{video_kbps}k', '-maxrate', f'{int(video_kbps * 1.4)}k',
                    '-bufsize', f'{video_kbps * 2}k']
        else:
            # NVENC 的 cq 与 x264 的 crf 不完全等价，略调高一点让体积相近
            cmd += ['-rc', 'vbr', '-cq', str(p.crf + 2), '-b:v', '0']
    else:
        cmd += ['-c:v', 'libx264', '-preset', 'medium', '-profile:v', 'high']
        if video_kbps:
            cmd += ['-b:v', f'{video_kbps}k', '-maxrate', f'{int(video_kbps * 1.4)}k',
                    '-bufsize', f'{video_kbps * 2}k']
        else:
            cmd += ['-crf', str(p.crf)]
    cmd += ['-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', f'{audio}k', '-ac', '2',
            '-movflags', '+faststart', '-progress', 'pipe:1', '-nostats', str(out)]
    return cmd


def _run(cmd: list[str], duration: float, progress_cb, cancel_cb):
    """运行 ffmpeg 并按 -progress 输出的 out_time 汇报进度；可随时取消。"""
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                            encoding='utf-8', errors='replace', bufsize=1)
    tail: list[str] = []

    def drain_stderr():
        for line in proc.stderr:
            tail.append(line)
            del tail[:-30]

    reader = threading.Thread(target=drain_stderr, daemon=True)
    reader.start()
    try:
        for line in proc.stdout:
            if cancel_cb and cancel_cb():
                proc.kill()
                raise CancelledError('压缩已取消')
            key, _, value = line.strip().partition('=')
            if key in ('out_time_us', 'out_time_ms') and value.isdigit() and duration > 0 and progress_cb:
                progress_cb(min(1.0, int(value) / 1e6 / duration))
        proc.wait()
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
        reader.join(timeout=2)
        proc.stdout.close()
        proc.stderr.close()
    if cancel_cb and cancel_cb():
        raise CancelledError('压缩已取消')
    if proc.returncode != 0:
        raise RuntimeError('ffmpeg 压缩失败：' + ''.join(tail)[-800:])


def unique_path(folder: Path, stem: str, suffix: str = '.mp4') -> Path:
    path = folder / f'{stem}{suffix}'
    n = 2
    while path.exists():
        path = folder / f'{stem}_{n}{suffix}'
        n += 1
    return path


def compress(src: Path, out_dir: Path, preset: str, *, target_mb: float = 0,
             progress_cb: Callable[[float, str], None] | None = None,
             cancel_cb: Callable[[], bool] | None = None,
             use_gpu: bool | None = None, name: str = '') -> dict:
    """name：输出文件名用的名字（上传的录像在缓存里是一串编号，用原文件名更好认）。"""
    src = Path(src)
    if not src.is_file():
        raise FileNotFoundError('视频文件不存在')
    p = PRESETS.get(preset)
    if p is None:
        raise ValueError(f'未知的压缩档位：{preset}')
    info = probe(src)
    duration = float(info.get('duration') or 0)
    src_size = src.stat().st_size
    if p.key == 'target':
        target_plan(duration, target_mb, int(info.get('height') or 0), float(info.get('fps') or 0))
    out_dir.mkdir(parents=True, exist_ok=True)
    tag = f'{target_mb:g}MB' if p.key == 'target' else p.label
    stem = ''.join(c for c in Path(name).stem if c not in '\\/:*?"<>|').strip()[:80] if name else ''
    final = unique_path(out_dir, f'{stem or src.stem}_压缩{tag}')
    pending = out_dir / f'.pending_{uuid.uuid4().hex}.mp4'
    gpu = nvenc_available() if use_gpu is None else use_gpu
    started = time.monotonic()

    def report(frac: float, attempt_label: str = ''):
        if progress_cb:
            progress_cb(frac, f'正在压缩{attempt_label}… {frac * 100:.0f}%')

    try:
        video_kbps = 0
        for attempt in range(2):
            label = '（再压一次，让文件小于目标）' if attempt else ''
            cmd = build_command(src, pending, info, preset, target_mb=target_mb,
                                video_kbps=video_kbps, gpu=gpu)
            try:
                _run(cmd, duration, lambda f: report(f, label), cancel_cb)
            except RuntimeError:
                if not gpu:
                    raise
                # 显卡编码失败（驱动 / 显存 / 分辨率不支持）→ 用 CPU 重来
                gpu = False
                cmd = build_command(src, pending, info, preset, target_mb=target_mb,
                                    video_kbps=video_kbps, gpu=False)
                _run(cmd, duration, lambda f: report(f, label), cancel_cb)
            if p.key != 'target':
                break
            size = pending.stat().st_size
            limit = target_mb * 1024 * 1024
            if size <= limit:
                break
            if attempt == 0:
                plan = target_plan(duration, target_mb, int(info.get('height') or 0),
                                   float(info.get('fps') or 0))
                video_kbps = max(120, int(plan['video_kbps'] * limit / size * 0.92))
        pending.rename(final)
        if progress_cb:
            progress_cb(1.0, '压缩完成')
    finally:
        if pending.exists():
            pending.unlink()

    size = final.stat().st_size
    out_info = probe(final)
    return dict(
        name=final.name, path=str(final), size=size, src_size=src_size,
        src_name=src.name, duration=duration,
        width=out_info.get('width'), height=out_info.get('height'),
        src_width=info.get('width'), src_height=info.get('height'),
        ratio=size / src_size if src_size else 1.0,
        encoder='h264_nvenc' if gpu else 'libx264',
        seconds=round(time.monotonic() - started, 1),
        over_target=bool(p.key == 'target' and size > target_mb * 1024 * 1024),
    )
