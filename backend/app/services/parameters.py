"""轻量识别参数；常驻监控无需导入 OpenCV、NumPy 或 OCR。"""
from dataclasses import dataclass
from .. import config


@dataclass
class DetectParams:
    player_id: str = ''
    sample_fps: float = config.DETECT.sample_fps
    debounce_seconds: float = config.DETECT.debounce_seconds
    id_match_ratio: float = config.DETECT.id_match_ratio
    id_region: tuple[float,float,float,float] | None = None
    prompt_region: tuple[float,float,float,float] | None = None
    knockdown_keywords: list[str] | None = None
    scan_windows: list[list[float]] | None = None
    use_gpu: bool = True

    def __post_init__(self):
        if self.id_region is None:
            self.id_region = tuple(config.DETECT.id_region.as_list())
        if self.prompt_region is None:
            self.prompt_region = tuple(config.DETECT.prompt_region.as_list())
        if self.knockdown_keywords is None:
            self.knockdown_keywords = list(config.DETECT.knockdown_keywords)
