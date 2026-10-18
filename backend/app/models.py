"""API 请求 / 响应数据模型。"""
from __future__ import annotations

from typing import Optional
from pydantic import BaseModel, Field


class RegionModel(BaseModel):
    x1: float
    y1: float
    x2: float
    y2: float


class AnalyzeRequest(BaseModel):
    upload_id: str = Field(..., description="上传完成后返回的视频 ID")
    player_id: str = Field("", description="玩家游戏 ID（右上角击杀信息里显示的名字）")
    sample_fps: Optional[float] = None
    debounce_seconds: Optional[float] = None
    id_match_ratio: Optional[float] = None
    id_region: Optional[RegionModel] = None
    prompt_region: Optional[RegionModel] = None
    knockdown_keywords: Optional[list[str]] = None


class KillMark(BaseModel):
    id: str
    time: float = Field(..., description="击杀时刻（秒）")
    confidence: float = 0.0
    id_text: str = ""        # OCR 在右上角识别到的文本
    prompt_text: str = ""    # OCR 在中间识别到的击倒文本
    victim_id: str = ""
    victim_signature: str = ""
    identity_key: str = ""
    event_type: str = "unknown"
    confirmed: bool = False
    review_required: bool = True
    source: str = "prompt"


class VideoMeta(BaseModel):
    upload_id: str
    filename: str
    duration: float
    width: int
    height: int
    fps: float
    size_bytes: int


class JobStatus(BaseModel):
    job_id: str
    state: str               # pending / running / done / error
    progress: float = 0.0    # 0~1
    message: str = ""
    kills: list[KillMark] = []
    meta: Optional[VideoMeta] = None
    error: Optional[str] = None


class ClipSpec(BaseModel):
    upload_id: str               # 该片段来自哪个视频（支持跨视频导出）
    kill_id: str = ""
    label: str = ""
    start: float
    end: float


class ExportRequest(BaseModel):
    clips: list[ClipSpec]
    merge: bool = False          # 是否合并为一个集锦
    accurate: bool = False       # True=精确剪辑(重编码) / False=快速剪辑(流拷贝)
    stretch_169: bool = True     # 默认真正拉伸为 16:9，可显式关闭


class ExportResult(BaseModel):
    job_id: str


class CleanupRequest(BaseModel):
    targets: list[str]   # ["uploads","clips","chunks","tmp"] 的子集
    force: bool = False  # 取消后台任务、等待句柄释放后重试删除


class StorageDeleteRequest(BaseModel):
    target: str
    path: str


class StorageRestoreRequest(BaseModel):
    path: str
    filename: str = ""
