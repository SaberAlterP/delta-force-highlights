"""只用已确认的不同干员，按滑动时间窗筛选多杀片段。"""
from __future__ import annotations
from .events import normalize, same_name


def confirmed_events(marks: list[dict]) -> list[dict]:
    events = []
    for mark in sorted(marks, key=lambda m: m['time']):
        victim = normalize(mark.get('victim_id', ''))
        if (not mark.get('confirmed') or mark.get('review_required', False) or not victim or
            mark.get('event_type') in {'assist', 'squad'}):
            continue
        if any(same_name(victim, prev['victim_id']) and mark['time']-prev['time'] <= 120
               for prev in events):
            continue
        events.append(mark)
    return events


def select_highlights(marks: list[dict], duration: float, *, window: float = 90,
                      minimum: int = 2, pre: float = 20, post: float = 5) -> list[dict]:
    if window <= 0 or minimum < 2 or duration <= 0:
        raise ValueError('多杀窗口、人数或视频时长无效')
    events = confirmed_events(marks)
    windows = []
    for i, first in enumerate(events):
        group = [e for e in events[i:] if e['time']-first['time'] <= window]
        if len(group) < minimum:
            continue
        windows.append(dict(start=max(0., first['time']-pre),
                            end=min(duration, group[-1]['time']+post),
                            events=group))
    merged = []
    for item in windows:
        if merged and item['start'] <= merged[-1]['end']:
            current = merged[-1]
            current['end'] = max(current['end'], item['end'])
            known = {e['id'] for e in current['events']}
            current['events'].extend(e for e in item['events'] if e['id'] not in known)
        else:
            merged.append(item)
    return merged
