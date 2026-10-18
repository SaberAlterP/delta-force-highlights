"""视频元信息读取（优先用 ffprobe，回退到 OpenCV）。"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path



def _ffprobe(path: Path) -> dict | None:
    if shutil.which("ffprobe") is None:
        return None
    try:
        out = subprocess.run(
            [
                "ffprobe", "-v", "error",
                "-select_streams", "v:0",
                "-show_entries",
                "stream=width,height,avg_frame_rate,r_frame_rate:format=duration,size",
                "-of", "json", str(path),
            ],
            capture_output=True, text=True, check=True, encoding='utf-8', errors='replace',
        )
        return json.loads(out.stdout)
    except Exception:
        return None


def _parse_fraction(value: str) -> float:
    try:
        if "/" in value:
            num, den = value.split("/")
            den = float(den)
            return float(num) / den if den else 0.0
        return float(value)
    except Exception:
        return 0.0


def probe(path: Path) -> dict:
    """返回 {duration, width, height, fps, size_bytes}。"""
    info = _ffprobe(path)
    if info and info.get("streams"):
        stream = info["streams"][0]
        fmt = info.get("format", {})
        fps = _parse_fraction(stream.get("avg_frame_rate") or stream.get("r_frame_rate") or "0")
        if fps <= 0:
            fps = _parse_fraction(stream.get("r_frame_rate", "0"))
        return {
            "duration": float(fmt.get("duration", 0.0) or 0.0),
            "width": int(stream.get("width", 0)),
            "height": int(stream.get("height", 0)),
            "fps": fps or 30.0,
            "size_bytes": int(fmt.get("size", path.stat().st_size)),
        }

    # 回退：OpenCV
    import cv2
    cap = cv2.VideoCapture(str(path))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    frame_count = cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    cap.release()
    duration = frame_count / fps if fps else 0.0
    return {
        "duration": duration,
        "width": width,
        "height": height,
        "fps": fps,
        "size_bytes": path.stat().st_size,
    }
