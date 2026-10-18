"""右上角独立扫描：保留行和左右角色，防止把自己的死亡当成击杀。"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
from functools import lru_cache
import cv2
import numpy as np

from .. import config
from . import ocr
from .events import name_score, normalize, same_name


@dataclass(frozen=True)
class FeedRow:
    killer: str
    victim: str
    score: float
    text: str
    signature: str = ''


def rows_from_boxes(boxes: list[ocr.TextBox], player_id: str,
                    threshold: float) -> list[FeedRow]:
    lines: list[list[ocr.TextBox]] = []
    for box in sorted(boxes, key=lambda b: (b.y1 + b.y2, b.x1)):
        cy = (box.y1 + box.y2) / 2
        line = next((line for line in lines if abs(
            cy - (line[0].y1 + line[0].y2) / 2
        ) <= min(box.y2-box.y1, line[0].y2-line[0].y1) * .55), None)
        if line is None:
            lines.append([box])
        else:
            line.append(box)
    rows = []
    for line in lines:
        line.sort(key=lambda b: b.x1)
        # 只有两侧都读到姓名且中间存在武器图标空隙，才将其视作有角色的击杀行。
        if len(line) < 2:
            continue
        gaps = [line[i+1].x1-line[i].x2 for i in range(len(line)-1)]
        split = max(range(len(gaps)), key=gaps.__getitem__)
        if gaps[split] < .035:
            continue
        left, right = line[:split+1], line[split+1:]
        killer = ''.join(b.text for b in left)
        victim = ''.join(b.text for b in right)
        if len(normalize(victim)) < 2 or len(normalize(killer)) < 2:
            continue
        score = name_score(player_id, killer)
        # 自己位于右侧是死亡记录，不能贡献 ID 支持或多帧投票。
        if score >= threshold and name_score(player_id, victim) < threshold:
            rows.append(FeedRow(killer, victim, score, f'{killer} → {victim}'))
    return rows


def read_rows(crop: np.ndarray, player_id: str, threshold: float) -> list[FeedRow]:
    if crop.size == 0 or not player_id:
        return []
    rows = []
    h, w = crop.shape[:2]
    for x, y, width, height in red_name_regions(crop):
        y1, y2 = max(0, y-3), min(h, y+height+4)
        # 红色被击杀者单独读取；避免暗红小字被明亮姓名和武器图标吞并。
        victim_crop = crop[y1:y2, max(0, x-3):min(w, x+width+3)]
        victim = read_name(victim_crop, red=True)
        signature = glyph_signature(crop[y:y+height, x:x+width])
        if name_score(player_id, victim) >= threshold:
            continue
        # 左侧可能有武器/击倒图标，但不会把右侧受害者名字纳入本人匹配。
        killer_crop = crop[y1:y2, :max(1, x-max(3, height*3))]
        killer = read_name(killer_crop)
        score = name_score(player_id, killer)
        if score >= threshold:
            victim = victim if len(normalize(victim)) >= 2 else '图像目标'+hashlib.sha256(
                signature.encode()).hexdigest()[:12]
            rows.append(FeedRow(killer, victim, score, f'{killer} → {victim}', signature))
    return rows


def red_name_regions(crop: np.ndarray) -> list[tuple[int, int, int, int]]:
    """敌方姓名为红色，救起/队友姓名为蓝色；后者不能当成击杀。"""
    if crop.size == 0:
        return []
    h, w = crop.shape[:2]
    b, g, r = [channel.astype(np.int16) for channel in cv2.split(crop)]
    mask = ((r >= 40) & (r-g >= 20) & (r-b >= 12)).astype(np.uint8)*255
    mask[:, :int(w*.48)] = 0
    joined = cv2.morphologyEx(mask, cv2.MORPH_CLOSE,
                             np.ones((2, max(3, round(w*.022))), np.uint8))
    contours, _ = cv2.findContours(joined, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    regions = []
    for contour in contours:
        x, y, width, height = cv2.boundingRect(contour)
        if (width >= max(12, w*.045) and 4 <= height <= max(8, h*.18) and
            x+width >= w*.72):
            density = np.count_nonzero(mask[y:y+height, x:x+width]) / (width*height)
            if .08 <= density <= .8:
                regions.append((x, y, width, height))
    return sorted(regions, key=lambda box: (box[1], box[0]))


def read_name(crop: np.ndarray, red: bool = False) -> str:
    if crop.size == 0:
        return ''
    if red:
        image = cv2.normalize(crop[:, :, 2], None, 0, 255, cv2.NORM_MINMAX)
    else:
        image = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)[:, :, 2]
    image = cv2.copyMakeBorder(image, 4, 4, 4, 4, cv2.BORDER_CONSTANT, value=0)
    image = cv2.resize(image, None, fx=4., fy=4., interpolation=cv2.INTER_CUBIC)
    # 受害者低置信度姓名只供显示/辅助；真正身份由多帧字形匹配确认。
    texts = ocr.recognize_line(image, min_confidence=0.00001 if red else .01)
    return ''.join(t for t, _ in texts)


def glyph_signature(crop: np.ndarray) -> str:
    b, g, r = [c.astype(np.int16) for c in cv2.split(crop)]
    chroma = np.clip(r-np.maximum(g, b), 0, 255).astype(np.uint8)
    # 保留连续灰度；二值化会随枪口闪光/透明度变化丢掉大半笔画。
    resized = cv2.resize(chroma, (64, 24), interpolation=cv2.INTER_AREA)
    normalized = cv2.normalize(resized, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
    return f'{crop.shape[1]}x{crop.shape[0]}:' + normalized.tobytes().hex()


@lru_cache(maxsize=2048)
def _glyph_features(data: str) -> tuple[np.ndarray, np.ndarray]:
    image = np.frombuffer(bytes.fromhex(data), dtype=np.uint8).reshape(24,64).astype(np.float32)
    variants = []
    for top in (0,2,4,6):
        for bottom in (0,2,4,6):
            resized = cv2.resize(image[top:24-bottom],(64,24)).ravel()
            centered = resized-resized.mean()
            variants.append(centered/max(1e-6,float(np.linalg.norm(centered))))
    matrix = np.stack(variants)
    return matrix[0], matrix


def glyphs_match(a: str, b: str) -> bool:
    if not a or not b:
        return False
    shape_a, data_a = a.split(':', 1)
    shape_b, data_b = b.split(':', 1)
    width_a, width_b = float(shape_a.split('x')[0]), float(shape_b.split('x')[0])
    # 同一录像中的字体宽度稳定；不能把四字和六字姓名拉成同样宽再误合并。
    if abs(width_a-width_b) > max(width_a,width_b)*.10:
        return False
    x, variants_x = _glyph_features(data_a)
    y, variants_y = _glyph_features(data_b)
    best = max(float(np.sum(variants_x*y,axis=1).max()),
               float(np.sum(variants_y*x,axis=1).max()))
    return best >= .68


class FeedTracker:
    def __init__(self):
        self.tracks: list[dict] = []
        self.parents: dict[str, str] = {}

    def root(self, key: str) -> str:
        parent = self.parents.get(key, key)
        if parent != key:
            parent = self.root(parent)
            self.parents[key] = parent
        return parent

    def confirmed_identity(self, row: FeedRow) -> str:
        for track in self.tracks:
            if track['emitted'] and any(glyphs_match(s, row.signature) for s in track['gallery']):
                return self.root(track['key'])
        return ''

    def confirmed_signature(self, row: FeedRow) -> str:
        for track in self.tracks:
            if track['emitted'] and any(glyphs_match(s, row.signature) for s in track['gallery']):
                return track['row'].signature
        return ''

    def observe(self, t: float, rows: list[FeedRow]) -> list[tuple[float, FeedRow, str]]:
        emitted = []
        for row in rows:
            matches = [x for x in self.tracks if t-x['last'] <= 120 and
                          (not row.signature or
                           abs(float(x['anchor'].split('x')[0])-float(row.signature.split('x')[0]))
                           <= max(float(x['anchor'].split('x')[0]),float(row.signature.split('x')[0]))*.10) and
                          (any(glyphs_match(s, row.signature) for s in x['gallery']) if row.signature
                           else same_name(x['row'].victim, row.victim))]
            matches.sort(key=lambda track: track['first'])
            match = matches[0] if matches else None
            # 新帧桥接此前因闪光/透明度而分开的轨迹，统一目标身份；人数在最终输出前重算。
            if len(matches) > 1:
                for other in matches[1:]:
                    # 防止 A~B、B~C 的渐变把不同名字串联；两条原始字形也必须相似。
                    if not glyphs_match(match['anchor'],other['anchor']):
                        continue
                    self.parents[self.root(other['key'])] = self.root(match['key'])
                    match['gallery'] = list(dict.fromkeys(match['gallery'] + other['gallery']))[-12:]
                    match['emitted'] |= other['emitted']
                    match['count'] = max(match['count'],other['count'])
                    self.tracks.remove(other)
            if match is None:
                key = str(len(self.parents))
                self.parents[key] = key
                match = dict(first=t, last=t, count=0, emitted=False, row=row, gallery=[],key=key,
                             anchor=row.signature)
                self.tracks.append(match)
            # 同帧两个预处理/相同行不能充当独立帧证据。
            if match['count'] == 0 or t > match['last']:
                match['count'] += 1
            match['last'] = t
            if row.signature:
                match['gallery'] = (match['gallery'][:1] + match['gallery'][-4:] + [row.signature])[-6:]
            if row.score > match['row'].score:
                match['row'] = row
            if match['count'] >= 2 and not match['emitted']:
                emitted.append((match['first'], match['row'],self.root(match['key'])))
                match['emitted'] = True
        self.tracks = [x for x in self.tracks if t-x['last'] <= 120]
        return emitted
