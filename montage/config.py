"""所有可调参数。默认值是用户验证过的效果；任何一项都能用 JSON 覆盖（--config 或 Python 传 dict）。"""
from __future__ import annotations

import copy
import json

DEFAULTS = {
    "song": {
        "start": 0.0,              # 歌从第几秒开始放（用户偏好：从头放）
        "top_accents": 40,         # 分析时保留多少个重音候选
    },
    "kills": {
        "av_offset": 0.12,         # 录像游戏声比画面晚多少秒；开枪画面帧 = 枪声起点 - av_offset
        "shot_window": 0.7,        # 在 verification_time 前多少秒内找"最后一声枪响"
        "fallback_lead": 0.35,     # 找不到枪声时，开枪帧 = verification_time - fallback_lead
        "only_confirmed": True,    # 只用画面核对过的击杀
        "merge_within": 0.3,       # 间隔小于此值的击杀合并
    },
    "plan": {
        "duration": 60.0,          # 成片目标时长
        "target_min_gap": 6.0,     # 作为"主击杀落点"的重音之间至少间隔
        "first_lead": [9.0, 18.0], # 第一个镜头击杀前留的前因（秒）范围
        "lead": [4.0, 9.0],        # 其余镜头击杀前留的前因范围
        "lead_realtime_max": 7.0,  # 前因超过这么长时，开头部分用快进（平滑减速回 1x）
        "lead_realtime_keep": 6.0, # 用快进时，击杀前保留多少秒原速
        "fill_gap": 14.0,          # 两个重音之间空当超过这么长，就在小节线上补一个落点
        "kills_per_shot": None,    # 一个镜头最多几个击杀；None = 不限制
        "max_shot_len": 30.0,      # 一个镜头最长（秒，成片时间）
        "speed_min": 1.0,          # 两次击杀之间的最低速度（1.0 = 不慢放）
        "speed_max": 1.35,         # 不做"快进效果"时的最高速度
        "ff_speed_max": 4.0,       # 快进的最高速度
        "ff_keep_after": 0.8,      # 击杀后、进入快进前保留的原速秒数
        "ff_keep_before": 2.5,     # 下一次击杀前、快进结束后保留的原速秒数
        "ff_ramp": 2.0,            # 快进结束时平滑减速回 1x 用掉的素材秒数
        "chain_max_gap": 20.0,     # 同一镜头里两次击杀的素材间隔超过这个就换镜头（None = 不限）
        "accent_bonus": 0.3,       # 后续击杀落在重音（而非普通拍）上的偏好权重
        "tail": 1.2,               # 最后一次击杀后至少再放多久（之后切在拍点上）
        "transition": "cut",       # 镜头之间默认转场：cut / push / impact
        "transition_every": 0,     # 每隔几个切点用一次上面的转场（0 = 全部硬切）
    },
    "render": {
        "hq": False,               # True：非 1x 段先补帧（慢很多，画面更顺）
        "preset": "veryfast",      # x264 preset（hq 时自动用 medium）
        "crf": 17,
        "opening": "fade_blur",    # 开头：fade_blur / none
        "fade_out": 1.5,
        "ff_blur": 4.0,            # 快进段额外模糊（>=2.5x 时）
        "game_volume": 0.85,       # 游戏声相对音乐的混音权重
        "music_volume": 0.9,
    },
}


def merge(base: dict, override: dict | None) -> dict:
    out = copy.deepcopy(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = merge(out[k], v)
        else:
            out[k] = v
    return out


def load(path: str | None = None, override: dict | None = None) -> dict:
    cfg = DEFAULTS
    if path:
        cfg = merge(cfg, json.load(open(path, encoding='utf-8')))
    return merge(cfg, override)
