"""击杀检测主流程。

策略（独立 kill feed 扫描 + 提示补充召回）：
  1. 按 sample_fps 采样帧（用 grab() 跳过非采样帧，避免完整解码）。
  2. 右上角独立扫描红色敌方姓名，逐行读取左侧本人 ID，以多帧字形确认目标。
  3. 准星下方提示补充候选；未由 kill feed 确认的候选保留待复核。
  4. 提示命中后回看一个粗采样间隔做局部细扫，校准提示首次出现时间。
  5. 按目标身份合并滞留提示和击倒/补杀，不跳过整个 debounce 时间段。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Callable
from functools import lru_cache

import cv2
import numpy as np

from .. import config
from . import ocr
from . import killfeed
from .events import EventTracker, name_score, parse_prompt
from .parameters import DetectParams


_id_template_cache: list[np.ndarray] | None = None


@dataclass(frozen=True)
class IdEvidence:
    """右上角确认窗口的结构化证据，避免用一个布尔值混淆“未确认”和“明确空白”。"""

    confirmed: bool = False
    text: str = ""
    confidence: float = 0.0
    ocr_score: float = 0.0
    vote_score: float = 0.0
    template_score: float = 0.0
    template_support_frames: int = 0
    change_score: float = 0.0
    meaningful_text_frames: int = 0
    scanned_frames: int = 0

    @property
    def conclusively_blank(self) -> bool:
        """窗口采样充分，且 OCR 与玩家模板都没有发现 kill feed 内容。"""
        return (
            self.scanned_frames >= config.DETECT.id_blank_min_scanned_frames
            and self.meaningful_text_frames == 0
            and self.template_support_frames
            < config.DETECT.id_presence_template_min_frames
        )


def _normalize(text: str) -> str:
    """归一化文本用于匹配：小写、去空格与常见标点。"""
    return re.sub(r"[\s\.\,\:\;\-_\|\[\]\(\)]", "", text).lower()


def _has_meaningful_id_text(text: str, match_ratio: float) -> bool:
    """排除空背景常见的纯数字 OCR 碎片，同时保留中英文玩家 ID。"""
    norm = _normalize(text)
    if match_ratio >= config.DETECT.id_presence_partial_match_ratio:
        return True
    if len(re.findall(r"[\u3400-\u9fff]", norm)) >= config.DETECT.id_presence_min_text_length:
        return True
    # 英文或混合 ID 必须包含字母，纯数字“1 1”等 HUD 噪声不算 kill feed。
    return (
        len(norm) >= max(3, config.DETECT.id_presence_min_text_length)
        and bool(re.search(r"[a-z]", norm))
    )


def _crop(frame: np.ndarray, region: tuple[float, float, float, float]) -> np.ndarray:
    h, w = frame.shape[:2]
    x1 = max(0, int(region[0] * w))
    y1 = max(0, int(region[1] * h))
    x2 = min(w, int(region[2] * w))
    y2 = min(h, int(region[3] * h))
    if x2 <= x1 or y2 <= y1:
        return np.empty((0, 0, 3), dtype=np.uint8)
    return frame[y1:y2, x1:x2]


def _visual_features(crop: np.ndarray) -> tuple[float, float]:
    """返回亮像素比例与明暗边缘比例，供 OCR 前的廉价预筛使用。"""
    if crop.size == 0:
        return 0.0, 0.0
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    bright_ratio = float(np.count_nonzero(gray >= config.DETECT.bright_threshold)) / gray.size
    dx = cv2.Sobel(gray, cv2.CV_16S, 1, 0, ksize=3)
    dy = cv2.Sobel(gray, cv2.CV_16S, 0, 1, ksize=3)
    edge_mask = (np.abs(dx) + np.abs(dy)) >= config.DETECT.edge_threshold
    edge_ratio = float(np.count_nonzero(edge_mask)) / gray.size
    return bright_ratio, edge_ratio


def _visual_prefilter(crop: np.ndarray) -> bool:
    """保守排除纯色、极暗等不可能含击杀提示文字的帧。"""
    bright_ratio, edge_ratio = _visual_features(crop)
    return (
        config.DETECT.bright_pixel_low <= bright_ratio <= config.DETECT.bright_pixel_high
        and edge_ratio >= config.DETECT.edge_pixel_low
    )


def _prompt_present(crop: np.ndarray, keywords: list[str]) -> tuple[bool, str]:
    texts = ocr.read_texts(crop, upscale=config.DETECT.ocr_upscale, min_confidence=0.25)
    joined = "".join(t for t, _ in texts)
    norm = _normalize(joined)
    if any(_normalize(word) in norm for word in config.DETECT.prompt_exclude_keywords):
        return False, joined
    kws = [_normalize(k) for k in keywords]
    for kw in kws:
        if kw and kw in norm:
            return True, joined
    # 对较长提示容忍少量 OCR 错字；两字关键词仍要求精确命中，避免过度召回。
    candidates = [_normalize(t) for t, _ in texts]
    if norm:
        candidates.append(norm)
    for kw in kws:
        if len(kw) < 3:
            continue
        if any(text and SequenceMatcher(None, kw, text).ratio() >= 0.72 for text in candidates):
            return True, joined
    return False, joined


def _id_present(crop: np.ndarray, player_id: str, ratio_threshold: float
                ) -> tuple[bool, str, float]:
    # 第一遍保留原始颜色；第二遍用 CLAHE 拉开暗色半透明小字的局部对比度。
    primary = ocr.read_texts(
        crop,
        upscale=config.DETECT.id_ocr_upscale,
        min_confidence=config.DETECT.id_ocr_min_confidence,
    )
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY) if crop.size else crop
    enhanced = (
        cv2.createCLAHE(clipLimit=3.0, tileGridSize=(4, 4)).apply(gray)
        if crop.size else crop
    )
    secondary = ocr.read_texts(
        enhanced,
        upscale=config.DETECT.id_ocr_enhanced_upscale,
        min_confidence=config.DETECT.id_ocr_min_confidence,
    )
    texts = primary + secondary
    if not texts:
        return False, "", 0.0

    joined = " ".join(t for t, _ in texts)
    if not player_id.strip():
        return False, joined, 0.0

    target = _normalize(player_id)
    best_ratio = 0.0
    for text, _conf in texts:
        norm = _normalize(text)
        if not norm:
            continue
        # 子串直接命中
        if target and target in norm:
            return True, joined, 1.0
        ratio = name_score(target, norm)
        best_ratio = max(best_ratio, ratio)
    return best_ratio >= ratio_threshold, joined, best_ratio


def _multi_frame_id_vote(player_id: str, observations: list[str]) -> float:
    """融合多帧 OCR：统计目标 ID 每个字符在不同帧中获得的支持度。"""
    target = _normalize(player_id)
    if not target or not observations:
        return 0.0
    ratios: list[float] = []
    for observation in observations:
        text = _normalize(observation)
        if not text:
            continue
        # 不能把不同姓名里零散出现的字符拼成一个“完整玩家 ID”。
        ratios.append(name_score(target, text))
    if not ratios:
        return 0.0
    top = sorted(ratios, reverse=True)[:3]
    stable_ratio = float(sum(top) / len(top)) * min(1.0, len(ratios) / 2.0)
    return stable_ratio


def _load_id_templates() -> list[np.ndarray]:
    global _id_template_cache
    if _id_template_cache is not None:
        return _id_template_cache
    templates: list[np.ndarray] = []
    for path in sorted(config.ID_TEMPLATE_DIR.glob("*.png")):
        # cv2.imread 在部分 Windows 中文路径下失败；fromfile + imdecode 支持 Unicode 路径。
        try:
            encoded = np.fromfile(str(path), dtype=np.uint8)
            image = cv2.imdecode(encoded, cv2.IMREAD_COLOR)
        except OSError:
            image = None
        if image is None or image.size == 0:
            continue
        # 用户模板是完整 kill feed 行；只保留左侧玩家 ID，排除武器与敌方名字。
        right = min(image.shape[1], 185)
        if right > 20:
            templates.append(image[:, 5:right])
    _id_template_cache = templates
    return templates


def _prepare_template_image(image: np.ndarray) -> np.ndarray:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image
    return cv2.createCLAHE(clipLimit=2.0, tileGridSize=(4, 4)).apply(gray)


@lru_cache(maxsize=1)
def _scaled_id_templates() -> tuple[np.ndarray, ...]:
    """整片复用缩放后的模板，避免每个采样帧重复 CLAHE 和缩放。"""
    variants = []
    for template in _load_id_templates():
        for scale in np.arange(0.45, 1.31, 0.05):
            resized = cv2.resize(template, None, fx=float(scale), fy=float(scale),
                                 interpolation=cv2.INTER_AREA if scale < 1 else cv2.INTER_CUBIC)
            variants.append(_prepare_template_image(resized))
    return tuple(variants)


def _template_match_score(crop: np.ndarray, player_id: str) -> float:
    """在右上角区域多尺度搜索玩家 ID 字形模板，返回 0~1 相似度。"""
    configured = _normalize(config.DETECT.id_template_player_id)
    target = _normalize(player_id)
    if not target or not configured or target != configured or crop.size == 0:
        return 0.0
    source = _prepare_template_image(crop)
    best = 0.0
    for prepared in _scaled_id_templates():
        if prepared.shape[0] >= source.shape[0] or prepared.shape[1] >= source.shape[1]:
            continue
        score = float(cv2.minMaxLoc(
            cv2.matchTemplate(source, prepared, cv2.TM_CCOEFF_NORMED)
        )[1])
        best = max(best, score)
    return max(0.0, min(1.0, best))


def _frame_change_score(previous: np.ndarray | None, current: np.ndarray) -> float:
    """检测 kill feed 新行造成的局部变化；仅作为弱证据，不单独触发击杀。"""
    if previous is None or previous.size == 0 or current.size == 0:
        return 0.0
    prev_gray = cv2.GaussianBlur(cv2.cvtColor(previous, cv2.COLOR_BGR2GRAY), (5, 5), 0)
    curr_gray = cv2.GaussianBlur(cv2.cvtColor(current, cv2.COLOR_BGR2GRAY), (5, 5), 0)
    if prev_gray.shape != curr_gray.shape:
        return 0.0
    raw = float(np.mean(cv2.absdiff(prev_gray, curr_gray))) / 255.0
    return min(1.0, raw / max(1e-6, config.DETECT.id_frame_change_reference))


def _refine_prompt_time(video_path: Path, coarse_t: float, source_fps: float,
                        params: DetectParams, stats: dict[str, float | int],
                        cancel_cb: Callable[[], bool] | None = None,
                        expected_text: str = '',
                        ) -> tuple[float, str]:
    """提示粗扫命中后回看一个采样间隔，定位提示首次出现时间。"""
    expected = parse_prompt(expected_text)
    if expected_text and not expected.victim:
        return coarse_t, ''
    coarse_interval = 1.0 / max(0.1, params.sample_fps)
    start_t = max(0.0, coarse_t - coarse_interval)
    fine_step = max(1, round(source_fps / max(0.1, config.DETECT.fine_scan_fps)))
    start_frame = max(0, int(start_t * source_fps))
    end_frame = max(start_frame, int(coarse_t * source_fps))

    fine_cap = cv2.VideoCapture(str(video_path))
    if not fine_cap.isOpened():
        return coarse_t, ""
    fine_cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)
    frame_idx = start_frame
    try:
        while frame_idx < end_frame:
            if cancel_cb and cancel_cb():
                break
            grabbed = fine_cap.grab()
            if not grabbed:
                break
            if (frame_idx - start_frame) % fine_step == 0:
                ok, frame = fine_cap.retrieve()
                if not ok or frame is None:
                    frame_idx += 1
                    continue
                prompt_crop = _crop(frame, params.prompt_region)
                if _visual_prefilter(prompt_crop):
                    stats["fine_prompt_ocr_calls"] += 1
                    hit, text = _prompt_present(prompt_crop, params.knockdown_keywords)
                    if hit:
                        candidate = parse_prompt(text)
                        if not expected_text or (candidate.victim and
                            SequenceMatcher(None, candidate.victim, expected.victim).ratio() >= .65):
                            return frame_idx / source_fps, text
            frame_idx += 1
    finally:
        fine_cap.release()
    return coarse_t, ""


def _confirm_id_near_time(video_path: Path, prompt_t: float, source_fps: float,
                          params: DetectParams, stats: dict[str, float | int],
                          cancel_cb: Callable[[], bool] | None = None,
                          ) -> IdEvidence:
    """在提示前后的小窗口内寻找玩家 ID，容忍 HUD 两处证据出现时间不同步。"""
    start_t = max(0.0, prompt_t - config.DETECT.id_confirm_before_seconds)
    end_t = prompt_t + config.DETECT.id_confirm_after_seconds
    start_frame = max(0, int(start_t * source_fps))
    end_frame = max(start_frame, int(end_t * source_fps))
    scan_step = max(1, round(source_fps / max(0.1, config.DETECT.id_confirm_fps)))

    confirm_cap = cv2.VideoCapture(str(video_path))
    if not confirm_cap.isOpened():
        return IdEvidence()
    confirm_cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)
    frame_idx = start_frame
    best_text = ""
    best_ratio = 0.0
    observations: list[str] = []
    best_template = 0.0
    template_support_frames = 0
    best_change = 0.0
    meaningful_text_frames = 0
    scanned_frames = 0
    previous_crop: np.ndarray | None = None
    try:
        while frame_idx <= end_frame:
            if cancel_cb and cancel_cb():
                break
            grabbed = confirm_cap.grab()
            if not grabbed:
                break
            if (frame_idx - start_frame) % scan_step == 0:
                ok, frame = confirm_cap.retrieve()
                if not ok or frame is None:
                    frame_idx += 1
                    continue
                id_crop = _crop(frame, params.id_region)
                scanned_frames += 1
                # 候选本来就很少；这里不得再用亮度预筛，否则暗色半透明 ID
                # 会在进入 OCR 前被漏掉。逐帧 OCR 成本远小于整片提示 OCR。
                best_change = max(best_change, _frame_change_score(previous_crop, id_crop))
                previous_crop = id_crop.copy()
                template_score = _template_match_score(id_crop, params.player_id)
                best_template = max(best_template, template_score)
                if template_score >= config.DETECT.id_template_match_threshold:
                    template_support_frames += 1
                stats["id_confirm_ocr_calls"] += 1
                _single_hit, text, ratio = _id_present(
                    id_crop, params.player_id, params.id_match_ratio
                )
                if text:
                    observations.append(text)
                    if _has_meaningful_id_text(text, ratio):
                        meaningful_text_frames += 1
                if text and (not best_text or ratio > best_ratio):
                    best_text, best_ratio = text, ratio
            frame_idx += 1
    finally:
        confirm_cap.release()

    vote_score = _multi_frame_id_vote(params.player_id, observations)
    composite = (
        0.52 * best_ratio
        + 0.23 * vote_score
        + 0.20 * best_template
        + 0.05 * best_change
    )
    stable_template_hit = (
        template_support_frames >= config.DETECT.id_template_confirm_min_frames
    )
    hit = (
        best_ratio >= params.id_match_ratio
        or composite >= config.DETECT.id_composite_threshold
        or (best_template >= config.DETECT.id_template_match_threshold and vote_score >= 0.35)
        or stable_template_hit
    )
    stats["best_id_ocr_score"] = max(float(stats.get("best_id_ocr_score", 0.0)), best_ratio)
    stats["best_id_vote_score"] = max(float(stats.get("best_id_vote_score", 0.0)), vote_score)
    stats["best_id_template_score"] = max(
        float(stats.get("best_id_template_score", 0.0)), best_template
    )
    stats["best_id_change_score"] = max(
        float(stats.get("best_id_change_score", 0.0)), best_change
    )
    return IdEvidence(
        confirmed=hit,
        text=best_text,
        confidence=max(
            best_ratio,
            composite,
            best_template if stable_template_hit else 0.0,
        ),
        ocr_score=best_ratio,
        vote_score=vote_score,
        template_score=best_template,
        template_support_frames=template_support_frames,
        change_score=best_change,
        meaningful_text_frames=meaningful_text_frames,
        scanned_frames=scanned_frames,
    )


def analyze(video_path: Path, params: DetectParams,
            progress_cb: Callable[[float, str], None] | None = None,
            max_seconds: float | None = None,
            stats_out: dict[str, float | int] | None = None,
            cancel_cb: Callable[[], bool] | None = None) -> list[dict]:
    """返回击杀标记列表 [{id, time, confidence, id_text, prompt_text}, ...]。"""
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"无法打开视频：{video_path}")

    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    step = max(1, round(fps / max(0.1, params.sample_fps)))
    # Official timestamps limit visual identity checks to short intervals.
    # None keeps the existing full-video manual scan; [] scans no frames.
    windows = None if params.scan_windows is None else [
        (max(0,int(start*fps)), min(total_frames-1,int(end*fps)))
        for start,end in params.scan_windows if end>start and start>=0]
    window_index = 0

    tracker = EventTracker(params.debounce_seconds)
    candidates = EventTracker(params.debounce_seconds)
    feed_tracker = killfeed.FeedTracker()
    kills = tracker.marks
    idx = 0
    stats = {
        "sampled_frames": 0,
        "debounce_skips": 0,
        "prompt_prefilter_rejects": 0,
        "prompt_ocr_calls": 0,
        "fine_prompt_ocr_calls": 0,
        "id_confirm_ocr_calls": 0,
        "prompt_candidates": 0,
        "id_confirmed_marks": 0,
        "id_uncertain_marks": 0,
        "id_blank_rejects": 0,
        "rejected_duplicate_skips": 0,
        "best_id_ocr_score": 0.0,
        "best_id_vote_score": 0.0,
        "best_id_template_score": 0.0,
        "best_id_change_score": 0.0,
        "feed_ocr_calls": 0,
        "feed_confirmed_marks": 0,
    }

    while True:
        if cancel_cb and cancel_cb():
            break
        if windows is not None:
            while window_index<len(windows) and idx>windows[window_index][1]:
                window_index+=1
            if window_index>=len(windows):break
            if idx<windows[window_index][0]:
                idx=windows[window_index][0]
                cap.set(cv2.CAP_PROP_POS_FRAMES,idx)
        grabbed = cap.grab()
        if not grabbed:
            break

        if idx % step == 0:
            stats["sampled_frames"] += 1
            ok, frame = cap.retrieve()
            if not ok or frame is None:
                idx += 1
                continue
            t = idx / fps
            if max_seconds is not None and t > max_seconds:
                break

            # 右上角独立发现事件；不依赖中间提示，也不设连续击杀盲区。
            rows = []
            if params.player_id.strip():
                id_crop = _crop(frame, params.id_region)
                # 敌方红字形态廉价召回；不把模板分数设成硬门槛，以免漏掉暗色姓名。
                possible_feed = bool(killfeed.red_name_regions(id_crop))
                if possible_feed:
                    stats["feed_ocr_calls"] += 1
                    rows = killfeed.read_rows(id_crop, params.player_id, params.id_match_ratio)
                for event_t, row, identity_key in feed_tracker.observe(t, rows):
                    tracker.add(event_t, victim=row.victim, kind='down_or_kill',
                                confirmed=True, confidence=min(.99, .65 + .3*row.score),
                                id_text=row.text, source='feed', signature=row.signature,
                                identity_key=identity_key)
                    stats["feed_confirmed_marks"] += 1

            # 第一级证据：准星下方明显的击败 / 击倒提示负责召回候选。
            prompt_crop = _crop(frame, params.prompt_region)
            if _visual_prefilter(prompt_crop):
                stats["prompt_ocr_calls"] += 1
                prompt_hit, prompt_text = _prompt_present(
                    prompt_crop, params.knockdown_keywords
                )
                if prompt_hit:
                    prompt = parse_prompt(prompt_text)
                    if not candidates.add(t, victim=prompt.victim, kind=prompt.kind,
                                          prompt_text=prompt_text):
                        stats["debounce_skips"] += 1
                        idx += 1
                        continue
                    stats["prompt_candidates"] += 1
                    refined_t, refined_text = _refine_prompt_time(
                        video_path, t, fps, params, stats, cancel_cb, prompt_text
                    )
                    if refined_text:
                        prompt_text = refined_text

                    # 三态判断：确认 ID 则高置信度保留；有 kill feed 但未确认 ID 时
                    # 低置信度保留；只有整个 ID 窗口明确空白才判为人机击杀并排除。
                    id_evidence = IdEvidence()
                    active_signature = ''
                    active_identity = ''
                    if rows:
                        chosen = max(rows, key=lambda row: name_score(prompt.victim, row.victim))
                        if name_score(prompt.victim, chosen.victim) < .55:
                            chosen = rows[0]
                        active_signature = feed_tracker.confirmed_signature(chosen)
                        active_identity = feed_tracker.confirmed_identity(chosen)
                    if active_signature:
                        id_evidence = IdEvidence(confirmed=True, text=chosen.text, confidence=.95)
                    elif params.player_id.strip():
                        id_evidence = _confirm_id_near_time(
                            video_path, refined_t, fps, params, stats, cancel_cb
                        )
                    if id_evidence.conclusively_blank:
                        stats["id_blank_rejects"] += 1
                        if progress_cb and total_frames > 0:
                            progress_cb(
                                idx / total_frames,
                                f"已分析 {int(t)} 秒，命中 {len(kills)} 次击杀，"
                                f"排除 {stats['id_blank_rejects']} 次人机击杀",
                            )
                        idx += 1
                        continue
                    if id_evidence.confirmed:
                        stats["id_confirmed_marks"] += 1
                        confidence = min(1.0, float(id_evidence.confidence) + 0.08)
                    else:
                        stats["id_uncertain_marks"] += 1
                        confidence = 0.55
                    prompt = parse_prompt(prompt_text)
                    tracker.add(refined_t, victim=prompt.victim, kind=prompt.kind,
                                confidence=.95 if active_signature else min(.79, confidence),
                                confirmed=bool(active_signature), signature=active_signature,
                                identity_key=active_identity,
                                id_text=id_evidence.text, prompt_text=prompt_text)
            else:
                stats["prompt_prefilter_rejects"] += 1

            if progress_cb and total_frames > 0:
                progress_cb(idx / total_frames, f"已分析 {int(t)} 秒，命中 {len(kills)} 次击杀")

        idx += 1

    cap.release()
    # 字形轨迹可能在后面的清晰帧才合并；最终按合并后的身份消除重复人数。
    merged = {}
    for mark in sorted(kills,key=lambda item:item['time']):
        key = feed_tracker.root(mark['identity_key']) if mark.get('identity_key') else mark['id']
        if key not in merged:
            merged[key] = mark
        else:
            old = merged[key]
            old['confirmed'] |= mark['confirmed']
            old['review_required'] = not old['confirmed']
            old['confidence'] = max(old['confidence'], mark['confidence'])
            if mark['prompt_text']:
                old['prompt_text'] = mark['prompt_text']
                old['victim_id'] = mark['victim_id'] or old['victim_id']
    kills = list(merged.values())
    if stats_out is not None:
        stats_out.clear()
        stats_out.update(stats)
    if progress_cb:
        progress_cb(
            1.0,
            f"完成：{sum(bool(k['confirmed']) for k in kills)} 名已确认干员，"
            f"{sum(bool(k['review_required']) for k in kills)} 个待复核候选。"
            f"击倒与补杀已合并；扫描 {stats['sampled_frames']} 帧，"
            f"排除 {stats['id_blank_rejects']} 个右上角明确空白的提示候选。",
        )
    return kills
