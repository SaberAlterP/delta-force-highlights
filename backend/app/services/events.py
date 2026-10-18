"""按目标身份跟踪击杀事件，不用整段时间盲区来去重。"""
from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
import re
import unicodedata
import uuid


def normalize(text: str) -> str:
    return ''.join(c for c in unicodedata.normalize('NFKC', text).casefold()
                   if c.isalnum())


def name_score(target: str, observed: str) -> float:
    """在一条姓名内部做定长局部匹配；禁止跨 OCR 行/预处理结果拼接。"""
    a, b = normalize(target), normalize(observed)
    if not a or not b:
        return 0.0
    if a in b:
        return 1.0
    if len(a) <= 2:
        return 0.0  # 短 ID 不做模糊匹配
    widths = {max(1, len(a) - 1), len(a), len(a) + 1}
    choices = [b]
    for width in widths:
        choices.extend(b[i:i+width] for i in range(max(0, len(b)-width+1)))
    return max(SequenceMatcher(None, a, x, autojunk=False).ratio() for x in choices)


def same_name(a: str, b: str) -> bool:
    a, b = normalize(a), normalize(b)
    if not a or not b:
        return False
    # 两名干员可能只差一个字符；身份去重不得使用宽松的姓名相似度。
    # OCR 错字交给字形证据和有时间约束的提示补全处理。
    return a == b


@dataclass(frozen=True)
class Prompt:
    text: str
    victim: str = ''
    kind: str = 'unknown'


def parse_prompt(text: str) -> Prompt:
    text = unicodedata.normalize('NFKC', text)
    kind = ('assist' if any(k in text for k in ('协助', '助攻')) else
            'down' if '击倒' in text else
            'kill' if any(k in text for k in ('击败', '淘汰')) else 'squad')
    match = re.search(r'(?:击败|击倒|淘汰)\s*([^\n]+)', text)
    victim = match.group(1) if match else ''
    victim = re.split(r'灭队|击中头部|\+\s*\d', victim)[0]
    return Prompt(text=text, victim=normalize(victim), kind=kind)


class EventTracker:
    """提示滞留、OCR 抖动、两处 HUD、击倒后补杀共同合并到一个目标事件。"""
    def __init__(self, debounce: float = 4.0, encounter_seconds: float = 120.0):
        self.debounce = debounce
        self.encounter_seconds = encounter_seconds
        self.marks: list[dict] = []
        self.last_seen: dict[str, float] = {}

    def add(self, t: float, *, victim: str = '', kind: str = 'unknown',
            confirmed: bool = False, confidence: float = 0.55,
            prompt_text: str = '', id_text: str = '', source: str = 'prompt',
            signature: str = '', identity_key: str = '') -> bool:
        if kind == 'assist':
            return False
        victim = normalize(victim)
        if kind == 'squad' and not victim:
            # 灭队是战斗结果，不代表又击杀了一名新干员。
            return False
        existing = None
        for mark in reversed(self.marks):
            dt = t - mark['time']
            if dt > self.encounter_seconds:
                break
            old_victim = mark['victim_id']
            if identity_key and mark.get('identity_key') == identity_key:
                existing = mark
                break
            if signature and mark.get('victim_signature'):
                from .killfeed import glyphs_match
                if glyphs_match(signature, mark['victim_signature']):
                    existing = mark
                    break
                continue
            if victim and old_victim and same_name(victim, old_victim):
                existing = mark
                break
            if abs(dt) <= 2 and victim and old_victim:
                # 中间提示可晚于右上角；一侧已被字形确认时允许补全 OCR 错字。
                approximate = SequenceMatcher(None, victim, old_victim).ratio()
                same_partial_prompt = (not confirmed and not mark['confirmed'] and
                                       abs(dt) <= .75 and victim[:3] == old_victim[:3] and
                                       min(len(victim),len(old_victim)) >= 4 and
                                       abs(len(victim)-len(old_victim)) >= 2)
                if ((confirmed != mark['confirmed'] and approximate >= .55) or
                    same_partial_prompt):
                    existing = mark
                    break
                if source == 'prompt' and not confirmed and mark['confirmed'] and abs(dt) <= 1.0:
                    existing = mark
                    break
            # 两路证据前后到达，缺少姓名的一路只合并很近的同一事件。
            if (not victim or not old_victim) and abs(dt) <= min(0.65, self.debounce):
                existing = mark
                break
            if (not victim and not old_victim and
                t - self.last_seen[mark['id']] <= self.debounce and
                same_name(prompt_text, mark['prompt_text'])):
                existing = mark
                break
        if existing is not None:
            self.last_seen[existing['id']] = t
            # 证据升级不会挪动首次击倒的时间，补杀也不会增加人数。
            existing['confirmed'] |= confirmed
            existing['confidence'] = round(max(existing['confidence'], confidence), 3)
            existing['victim_id'] = existing['victim_id'] or victim
            if source == 'prompt' and victim and existing['confirmed']:
                existing['victim_id'] = victim
            existing['victim_signature'] = existing.get('victim_signature') or signature
            existing['identity_key'] = existing.get('identity_key') or identity_key
            if prompt_text:
                existing['prompt_text'] = prompt_text
            if id_text:
                existing['id_text'] = id_text
            if source not in existing['source'].split('+'):
                existing['source'] += '+' + source
            existing['review_required'] = not existing['confirmed']
            return False
        mark = dict(id=uuid.uuid4().hex, time=round(t, 3),
                    confidence=round(confidence, 3), id_text=id_text,
                    prompt_text=prompt_text, victim_id=victim, event_type=kind,
                    confirmed=confirmed, review_required=not confirmed, source=source)
        mark['victim_signature'] = signature
        mark['identity_key'] = identity_key
        self.marks.append(mark)
        self.last_seen[mark['id']] = t
        return True
