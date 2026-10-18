"""全局配置。

检测区域使用「相对比例」（0~1）表示，与分辨率无关：
    (x1, y1, x2, y2) —— 左上角 (x1,y1)、右下角 (x2,y2)，均为占整帧宽/高的比例。

⚠️ 下面的默认区域是按 16:9（如 1920x1080）三角洲行动 HUD 的经验值预设的，
   收到用户截图后需要据此校准（也可在前端「区域校准」面板用鼠标框选覆盖）。
"""
from __future__ import annotations

import os
from pathlib import Path
from dataclasses import dataclass, field

# ---------- 路径 ----------
BASE_DIR = Path(__file__).resolve().parent.parent          # backend/
DETECTOR_VERSION_FILE = BASE_DIR / "detector-version.txt"
DETECTOR_VERSION = DETECTOR_VERSION_FILE.read_text(encoding="utf-8").strip()
# 环境变量 DELTA_STORAGE_DIR 可换数据目录（测试实例与正式实例互不干扰）
STORAGE_DIR = (Path(os.environ["DELTA_STORAGE_DIR"]).resolve() if os.environ.get("DELTA_STORAGE_DIR")
               else BASE_DIR / "storage")
UPLOAD_DIR = STORAGE_DIR / "uploads"        # 上传的原始视频
CHUNK_DIR = STORAGE_DIR / "chunks"          # 分片上传的临时块
CLIP_DIR = STORAGE_DIR / "clips"            # 导出的片段
TMP_DIR = STORAGE_DIR / "tmp"               # 其它临时文件
ID_TEMPLATE_DIR = BASE_DIR / "assets" / "id_templates"

for _d in (STORAGE_DIR, UPLOAD_DIR, CHUNK_DIR, CLIP_DIR, TMP_DIR, ID_TEMPLATE_DIR):
    _d.mkdir(parents=True, exist_ok=True)


def _template_player_id() -> str:
    path = ID_TEMPLATE_DIR / "player_id.txt"
    return path.read_text(encoding="utf-8").strip() if path.is_file() else ""


@dataclass
class DetectRegion:
    """相对比例区域 (x1, y1, x2, y2)，取值 0~1。"""
    x1: float
    y1: float
    x2: float
    y2: float

    def to_pixels(self, w: int, h: int) -> tuple[int, int, int, int]:
        return (
            max(0, int(self.x1 * w)),
            max(0, int(self.y1 * h)),
            min(w, int(self.x2 * w)),
            min(h, int(self.y2 * h)),
        )

    def as_list(self) -> list[float]:
        return [self.x1, self.y1, self.x2, self.y2]


@dataclass
class DetectConfig:
    """识别相关的可调参数（前端发起分析时可覆盖部分字段）。"""

    # 右上角「击杀信息 / kill feed」区域（主判断：匹配玩家 ID）
    # —— 依据 2026-04-14 实际录像截图校准
    id_region: DetectRegion = field(
        # 击杀信息固定出现在右上角；保留长 ID 和两行 kill feed 的安全边距。
        # 恢复到最后一个稳定识别基线（2026-07-12 对话截图）。
        default_factory=lambda: DetectRegion(0.79, 0.03, 0.995, 0.14)
    )
    # 屏幕中下方「击杀提示」区域（辅助判断：击败/击倒关键词）
    # —— 截图中文字在约 70%~85% 高度，故区域下移到中下部
    prompt_region: DetectRegion = field(
        # 依据 2026-07-12 实际录像校准：提示文字固定在准星下方中央。
        # 相比旧区域 (0.34, 0.64, 0.66, 0.90)，面积减少约 78%。
        # 恢复到最后一个稳定识别基线（2026-07-12 对话截图）。
        default_factory=lambda: DetectRegion(0.43, 0.72, 0.58, 0.84)
    )

    # 击杀提示关键词（命中其一即视为出现击杀提示）
    # —— 实际游戏文字为「击败」「击中头部击败」「灭队」，并保留「击倒」等
    knockdown_keywords: list[str] = field(
        default_factory=lambda: [
            "击败", "击中头部击败", "灭队",
            "击倒", "击中头部击倒", "淘汰",
        ]
    )
    # 这些提示不是玩家正式击杀，即使包含「击倒」也必须排除。
    prompt_exclude_keywords: list[str] = field(
        default_factory=lambda: ["协助", "助攻"]
    )

    # 稳定基线默认值：3 FPS，在召回率和长视频耗时之间取平衡。
    sample_fps: float = 3.0
    fine_scan_fps: float = 6.0

    # 准星提示与右上角击杀信息可能相差数帧；只在提示命中后扫描此时间窗确认 ID。
    # 「灭队」等提示可能晚于 kill feed 两秒左右，向前窗口必须覆盖这种延迟。
    id_confirm_before_seconds: float = 2.5
    id_confirm_after_seconds: float = 1.25
    id_confirm_fps: float = 6.0

    # 同一次击杀的去抖动窗口（秒）：窗口内的多次命中合并为一次击杀
    debounce_seconds: float = 4.0

    # ID 模糊匹配阈值（0~1）：OCR 结果与玩家 ID 的相似度达到此值即算命中
    id_match_ratio: float = 0.7

    # 中间区域「快速预筛」的亮像素比例范围：在此范围内才认为可能有文字，触发 OCR。
    # 阈值放宽以避免漏掉文字较小的帧（GPU 下多做些 OCR 也来得及）。
    bright_pixel_low: float = 0.001
    bright_pixel_high: float = 0.6
    bright_threshold: int = 180     # 灰度阈值，高于此视为亮像素
    # 保守的文字边缘预筛：仅淘汰纯色、极暗等明显不含提示文字的帧。
    edge_pixel_low: float = 0.001
    edge_threshold: int = 32

    # 右上角 ID 字号更小，单独提高放大倍数并降低 OCR 结果过滤阈值。
    id_ocr_upscale: float = 2.2
    id_ocr_min_confidence: float = 0.04
    id_ocr_enhanced_upscale: float = 4.0

    # 多证据融合：OCR、多帧字符投票、玩家 ID 模板、kill feed 新行帧差。
    # 本人 ID 字形模板只对这个 ID 生效；写在 assets/id_templates/player_id.txt（个人数据，不随仓库发布）
    id_template_player_id: str = field(default_factory=lambda: _template_player_id())
    id_template_match_threshold: float = 0.63
    id_composite_threshold: float = 0.58
    id_frame_change_reference: float = 0.08

    # 人机击杀排除采用保守的“明确空白”判定：至少检查多帧，且既无有效 OCR
    # 文本，也无最低限度的玩家模板迹象。帧差不参与空白判定，避免镜头移动伪造证据。
    id_blank_min_scanned_frames: int = 3
    id_presence_min_text_length: int = 2
    id_presence_partial_match_ratio: float = 0.20
    id_presence_template_min_frames: int = 2
    id_template_confirm_min_frames: int = 3
    rejected_prompt_similarity: float = 0.72

    # 单帧 OCR 前把裁剪区域放大的倍率（小区域放大有助于 OCR）
    ocr_upscale: float = 1.6


@dataclass
class ClipConfig:
    pre_seconds: float = 20.0       # 击杀前
    post_seconds: float = 5.0       # 击杀后


# ---------- OCR / 运行时 ----------
# EasyOCR 语言：简体中文 + 英文
OCR_LANGS = ["ch_sim", "en"]
# 是否使用 GPU（用户机器有 NVIDIA 显卡）。若运行时无 CUDA，ocr.py 会自动回退到 CPU。
USE_GPU = True

# 上传分片大小（前端需与之对应；此处仅作参考）
CHUNK_SIZE = 5 * 1024 * 1024  # 5MB

# 允许的前端来源
CORS_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]

DETECT = DetectConfig()
CLIP = ClipConfig()
