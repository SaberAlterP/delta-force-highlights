"""EasyOCR 封装：进程内单例，优先 GPU，无 CUDA 时自动回退 CPU。"""
from __future__ import annotations

import threading
from dataclasses import dataclass

import numpy as np

from .. import config

_reader = None
_lock = threading.Lock()


@dataclass(frozen=True)
class TextBox:
    text: str
    confidence: float
    x1: float
    y1: float
    x2: float
    y2: float


def recognize_line(image: np.ndarray, *, min_confidence: float = .01) -> list[tuple[str, float]]:
    """区域已经校准为单行时直接识字，避免小字在 CRAFT 检测阶段被丢弃。"""
    import cv2
    if image is None or image.size == 0:
        return []
    if image.ndim == 3:
        image = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    reader = get_reader()
    with _lock:
        results = reader.recognize(image, detail=1, paragraph=False)
    return [(str(text).strip(), float(conf or 0)) for _, text, conf in results
            if str(text).strip() and float(conf or 0) >= min_confidence]


def read_boxes(image: np.ndarray, *, upscale: float = 1.0,
               min_confidence: float = 0.3) -> list[TextBox]:
    """保留文字位置；坐标归一化，供同一行的击杀者/被击杀者分离使用。"""
    import cv2
    if image is None or image.size == 0:
        return []
    if upscale and upscale != 1.0:
        image = cv2.resize(image, None, fx=upscale, fy=upscale,
                           interpolation=cv2.INTER_LINEAR)
    h, w = image.shape[:2]
    reader = get_reader()
    with _lock:
        results = reader.readtext(image, detail=1, paragraph=False)
    out = []
    for item in results:
        try:
            bbox, text, conf = item
            points = np.asarray(bbox, dtype=float)
            conf = float(conf or 0)
            if conf < min_confidence or not text.strip() or points.shape != (4, 2):
                continue
            out.append(TextBox(text.strip(), conf,
                               float(points[:, 0].min()) / w,
                               float(points[:, 1].min()) / h,
                               float(points[:, 0].max()) / w,
                               float(points[:, 1].max()) / h))
        except (ValueError, TypeError):
            continue
    return out


def _build_reader():
    """惰性创建 EasyOCR Reader（首次会下载模型）。"""
    import easyocr  # 延迟导入，避免无 GPU 环境下导入开销

    use_gpu = config.USE_GPU
    if use_gpu:
        try:
            import torch
            use_gpu = bool(torch.cuda.is_available())
        except Exception:
            use_gpu = False

    reader = easyocr.Reader(config.OCR_LANGS, gpu=use_gpu)
    print(f"[ocr] EasyOCR 就绪，GPU={'ON' if use_gpu else 'OFF (CPU 回退)'}")
    return reader


def get_reader():
    global _reader
    if _reader is None:
        with _lock:
            if _reader is None:
                _reader = _build_reader()
    return _reader


def read_texts(image: np.ndarray, *, upscale: float = 1.0,
               min_confidence: float = 0.3) -> list[tuple[str, float]]:
    """对图像块做 OCR，返回 [(文本, 置信度), ...]。

    EasyOCR 不是线程安全的，这里加锁串行调用（GPU 下单流足够快）。
    """
    return [(b.text, b.confidence) for b in read_boxes(
        image, upscale=upscale, min_confidence=min_confidence)]
