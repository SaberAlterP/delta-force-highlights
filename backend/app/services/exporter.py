"""使用 ffmpeg 剪辑 / 合并击杀片段。

- 快速模式（accurate=False）：未启用画面拉伸时使用流拷贝 `-c copy`。
- 画面拉伸需要改变真实像素尺寸，因此无论是否精确剪辑都会重编码视频。
- 精确模式（accurate=True）：重编码，起止精确，耗时较长。
"""
from __future__ import annotations

import shutil
import subprocess
import uuid
from concurrent.futures import CancelledError
from pathlib import Path
from typing import Callable

from .. import config


def _ffmpeg() -> str:
    exe = shutil.which("ffmpeg")
    if exe is None:
        raise RuntimeError("未找到 ffmpeg，请先安装并加入 PATH（见 README）。")
    return exe


def _run(cmd: list[str], cancel_cb: Callable[[], bool] | None = None):
    """运行 ffmpeg；强制清理缓存时可终止子进程并立即释放源文件。"""
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                            encoding='utf-8', errors='replace')
    while True:
        if cancel_cb and cancel_cb():
            proc.terminate()
            try:
                proc.communicate(timeout=2)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.communicate()
            raise CancelledError("导出已取消")
        try:
            _stdout, stderr = proc.communicate(timeout=0.2)
            break
        except subprocess.TimeoutExpired:
            continue
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg 失败：{stderr[-800:]}")


def cut_clip(src: Path, start: float, end: float, out: Path,
             accurate: bool = False, stretch_169: bool = False,
             cancel_cb: Callable[[], bool] | None = None):
    """剪辑单个片段。

    stretch_169=True 时真正把 4:3（或其它比例）的像素横向拉伸为 16:9。
    拉伸必然需要重编码；accurate 仅控制输入定位方式。
    """
    start = max(0.0, start)
    duration = max(0.1, end - start)
    ff = _ffmpeg()

    if accurate or stretch_169:
        if accurate:
            # 精确定位：-ss 放在 -i 之后。
            cmd = [
                ff, "-y", "-i", str(src),
                "-ss", f"{start:.3f}", "-t", f"{duration:.3f}",
            ]
        else:
            # 快速定位，但仍重编码以确保拉伸后的像素尺寸真实生效。
            cmd = [
                ff, "-y", "-ss", f"{start:.3f}", "-i", str(src),
                "-t", f"{duration:.3f}",
            ]
        if stretch_169:
            # 宽 = 高 * 16/9（取偶数）；SAR=1，输出文件拥有真实的 16:9 像素尺寸。
            cmd += ["-vf", "scale=trunc(ih*16/9/2)*2:trunc(ih/2)*2,setsar=1"]
        cmd += [
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
            "-c:a", "aac", "-b:a", "192k",
            "-movflags", "+faststart",
            str(out),
        ]
    else:
        # 快速：-ss 放在 -i 之前（输入定位，快），流拷贝
        cmd = [
            ff, "-y",
            "-ss", f"{start:.3f}", "-i", str(src),
            "-t", f"{duration:.3f}",
            "-c", "copy", "-avoid_negative_ts", "make_zero",
        ]
        cmd += ["-movflags", "+faststart", str(out)]
    _run(cmd, cancel_cb=cancel_cb)


def merge_clips(clip_paths: list[Path], out: Path,
                cancel_cb: Callable[[], bool] | None = None):
    """把多个片段合并成一个集锦（concat demuxer，需编码参数一致）。"""
    ff = _ffmpeg()
    list_file = config.TMP_DIR / f"concat_{uuid.uuid4().hex}.txt"
    with list_file.open("w", encoding="utf-8") as f:
        for p in clip_paths:
            # 反斜杠转义，路径用单引号
            safe = str(p).replace("\\", "/")
            f.write(f"file '{safe}'\n")
    try:
        cmd = [
            ff, "-y", "-f", "concat", "-safe", "0",
            "-i", str(list_file),
            "-c", "copy", "-movflags", "+faststart",
            str(out),
        ]
        try:
            _run(cmd, cancel_cb=cancel_cb)
        except RuntimeError:
            # 流拷贝合并失败（多为参数不一致）→ 回退重编码合并
            cmd_re = [
                ff, "-y", "-f", "concat", "-safe", "0",
                "-i", str(list_file),
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
                "-c:a", "aac", "-b:a", "192k",
                "-movflags", "+faststart",
                str(out),
            ]
            _run(cmd_re, cancel_cb=cancel_cb)
    finally:
        list_file.unlink(missing_ok=True)


def export_clips(specs: list[dict], merge: bool, accurate: bool,
                 stretch_169: bool = False,
                 progress_cb: Callable[[float, str], None] | None = None,
                 cancel_cb: Callable[[], bool] | None = None,
                 output_root: Path | None = None) -> dict:
    """specs: [{src, kill_id, label, start, end}, ...]（每个片段带自己的源文件 src，支持跨视频）
    返回 {"files": [{name, path}], "merged": path|None}
    """
    out_dir = (output_root or config.CLIP_DIR) / uuid.uuid4().hex
    out_dir.mkdir(parents=True, exist_ok=True)

    files: list[dict] = []
    n = len(specs)
    for i, spec in enumerate(specs):
        if cancel_cb and cancel_cb():
            raise CancelledError("导出已取消")
        label = spec.get("label") or f"kill_{i + 1:02d}"
        safe_label = "".join(c for c in label if c.isalnum() or c in "._-")[:40] or f"kill_{i+1:02d}"
        out_path = out_dir / f"{i + 1:02d}_{safe_label}.mp4"
        cut_clip(Path(spec["src"]), float(spec["start"]), float(spec["end"]), out_path,
                 accurate=accurate, stretch_169=stretch_169, cancel_cb=cancel_cb)
        files.append({"name": out_path.name, "path": str(out_path)})
        if progress_cb:
            progress_cb((i + 1) / max(1, n) * (0.9 if merge else 1.0),
                        f"已导出 {i + 1}/{n} 个片段")

    merged_path = None
    if merge and files:
        merged_path = out_dir / "highlight_merged.mp4"
        merge_clips([Path(f["path"]) for f in files], merged_path, cancel_cb=cancel_cb)
        if progress_cb:
            progress_cb(1.0, "已合并为集锦")

    return {
        "dir": str(out_dir),
        "files": files,
        "merged": str(merged_path) if merged_path else None,
    }
