"""集锦剪辑助手：用 Claude 读工程、改参数、编排和微调时间线。

只把工程的文字信息（文件名、击杀时间、节拍、参数）发给模型，不上传视频和音频。
出片不交给 agent：出片耗时长，由用户在网页上点。
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from . import montage_studio as studio

SYSTEM = """你是《三角洲行动》多杀集锦的剪辑助手，帮用户把高光素材按一首歌剪成卡点视频。
工程由三部分组成：挑选的素材、一首歌（已分析出节拍 beats、小节线 downbeats、按听感排序的重音 top）、
参数（片头 opening、镜头转场 transition、片尾 ending、卡点规则 plan.*）。时间线 timeline 里每个镜头 shot 有
file（素材）、start/end（成片秒）、kills（src=素材里开枪那一帧，at=落在成片第几秒）、transition_in。

工作方式：
- 先用 get_project 看现状，再动手。改参数后需要 auto_plan 才会体现在时间线上；微调时间线用 edit_timeline。
- 击杀要落在拍点上，最重要的击杀落在 top 里最重的重音上；at 用歌曲里实际存在的 beats / top 时间。
- 用户偏好：不慢放、击杀瞬间不加缩放/震屏、歌从头放、每个击杀前要留前因（看得懂怎么打的）。
- edit_timeline 返回的 errors 说明哪些改动不可行（需要慢放或超出快进上限），要换个落点再试。
- 不要出片，出片由用户点按钮。
回答用简体中文，简短说明你改了什么、为什么；不确定用户想要的风格时先问一句。"""

TOOLS = [
    dict(name='get_project', description='读取工程现状：参数、素材列表（是否选中、击杀数）、歌曲（BPM、时长、重音、小节线）、时间线、上次重算的错误、可选的转场/片头/片尾/风格预设。',
         input_schema=dict(type='object', properties={}, additionalProperties=False)),
    dict(name='update_settings', description='修改参数（深度合并，只写要改的项）。例：{"plan": {"duration": 45, "transition": "push", "transition_every": 2}, "render": {"opening": "zoom", "ending": "blur", "title": "周末三连"}}。改完要 auto_plan 才会重新编排。',
         input_schema=dict(type='object', properties=dict(settings=dict(type='object')), required=['settings'], additionalProperties=False)),
    dict(name='apply_style', description='套用一个风格预设（clean/punchy/impact/flow/cinema），会改转场、片头、片尾等参数。',
         input_schema=dict(type='object', properties=dict(style=dict(type='string')), required=['style'], additionalProperties=False)),
    dict(name='select_clips', description='勾选或取消素材。indices 是 get_project 返回的素材序号（从 0 开始）。',
         input_schema=dict(type='object', properties=dict(indices=dict(type='array', items=dict(type='integer')), selected=dict(type='boolean')),
                           required=['indices', 'selected'], additionalProperties=False)),
    dict(name='auto_plan', description='按当前参数和选中的素材自动编排整条时间线（会覆盖手动改动）。',
         input_schema=dict(type='object', properties={}, additionalProperties=False)),
    dict(name='edit_timeline', description=studio.apply_ops.__doc__.split('\n', 1)[1].strip()
         + '\n镜头和击杀序号从 0 开始；击杀按 at 排序。所有操作做完后自动重算变速并返回时间线和 errors。',
         input_schema=dict(type='object', properties=dict(ops=dict(type='array', items=dict(type='object'))), required=['ops'], additionalProperties=False)),
]


def _summary(pid: str) -> dict:
    p = studio.load(pid)
    song = p.get('song') or {}
    tl = p.get('timeline') or {}
    clip_kills = p.get('clip_kills') or {}
    return dict(
        name=p['name'], settings=studio.cfg_of(p),
        clips=[dict(index=i, name=c.get('name'), file=c['path'], selected=c.get('selected', True), duration=c.get('duration'),
                    kills=clip_kills.get(c['path']), manual_kills=c.get('manual_kills') or None) for i, c in enumerate(p.get('clips', []))],
        song=dict(name=song.get('name'), bpm=song.get('bpm'), duration=song.get('duration'),
                  top_accents=[a['t'] for a in song.get('top', [])[:24]], downbeats=song.get('downbeats'),
                  beats_count=len(song.get('beats', []))) if song else None,
        timeline=dict(duration=tl.get('duration'), shots=[
            dict(index=i, file=Path(s['file']).name, path=s['file'], start=s['start'], end=s['end'], transition_in=s.get('transition_in', 'cut'),
                 kills=sorted(s['kills'], key=lambda k: k['at'])) for i, s in enumerate(tl.get('shots', []))]) if tl else None,
        errors=p.get('errors'), skipped=p.get('skipped'),
        presets=dict(transitions=[t['id'] for t in studio.TRANSITIONS], openings=[o['id'] for o in studio.OPENINGS],
                     endings=[e['id'] for e in studio.ENDINGS], styles={s['id']: s['desc'] for s in studio.STYLES}),
    )


def _run_tool(pid: str, name: str, args: dict) -> tuple[str, str | None]:
    """返回 (给模型的结果, 给用户看的一行改动说明)。"""
    if name == 'get_project':
        return json.dumps(_summary(pid), ensure_ascii=False), None
    if name == 'update_settings':
        studio.update(pid, dict(settings=args.get('settings') or {}))
        return '已保存', '改了参数：' + json.dumps(args.get('settings'), ensure_ascii=False)
    if name == 'apply_style':
        st = next((s for s in studio.STYLES if s['id'] == args.get('style')), None)
        if not st:
            raise ValueError('没有这个风格')
        studio.update(pid, dict(settings=st['config']))
        return '已套用', f"套用风格「{st['label']}」"
    if name == 'select_clips':
        p = studio.load(pid)
        for i in args.get('indices') or []:
            if 0 <= i < len(p['clips']):
                p['clips'][i]['selected'] = bool(args.get('selected'))
        studio.update(pid, dict(clips=p['clips']))
        return '已保存', f"{'勾选' if args.get('selected') else '取消'}了 {len(args.get('indices') or [])} 段素材"
    if name == 'auto_plan':
        r = studio.auto_plan(pid)
        return json.dumps(r, ensure_ascii=False), f"重新编排：{r['shots']} 个镜头，{r['duration']:.1f} 秒"
    if name == 'edit_timeline':
        r = studio.apply_ops(pid, args.get('ops') or [])
        brief = dict(duration=r['timeline']['duration'], errors=r['errors'],
                     shots=[dict(index=i, file=Path(s['file']).name, start=s['start'], end=s['end'], transition_in=s.get('transition_in'),
                                 kills=[k['at'] for k in sorted(s['kills'], key=lambda k: k['at'])]) for i, s in enumerate(r['timeline']['shots'])])
        return json.dumps(brief, ensure_ascii=False), f"调整时间线（{len(args.get('ops') or [])} 处）" + ('，有不可行的改动' if r['errors'] else '')
    raise ValueError(f'没有这个工具：{name}')


def _client():
    import anthropic
    key = studio.load_settings().get('api_key') or os.environ.get('ANTHROPIC_API_KEY')
    if not key:
        raise PermissionError('还没填 Claude API Key：在「集锦剪辑 → 助手」里的设置填写')
    return anthropic.Anthropic(api_key=key)


def chat(pid: str, text: str, max_steps: int = 16) -> dict:
    import anthropic
    client = _client()
    model = studio.public_settings()['model']
    p = studio.load(pid)
    messages = p.get('agent_messages') or []
    last = messages[-1] if messages else None
    if last and last['role'] == 'user' and isinstance(last['content'], list):   # 上次停在工具结果后面
        last['content'].append(dict(type='text', text=text))
    else:
        messages.append(dict(role='user', content=text))
    changes: list[str] = []
    reply = ''
    for _ in range(max_steps):
        try:
            resp = client.beta.messages.create(
                model=model, max_tokens=16000, system=SYSTEM, tools=TOOLS, messages=messages,
                thinking={'type': 'adaptive'}, output_config={'effort': 'medium'},
                betas=['server-side-fallback-2026-07-01'], extra_body={'fallbacks': 'default'})
        except anthropic.AuthenticationError:
            raise PermissionError('Claude API Key 无效，请在助手设置里重新填写')
        except anthropic.RateLimitError:
            raise RuntimeError('请求太频繁，稍等一会儿再试')
        except anthropic.APIConnectionError:
            raise RuntimeError('连不上 Claude 接口，检查一下网络')
        messages.append(dict(role='assistant', content=[b.model_dump(exclude_none=True) for b in resp.content]))
        if resp.stop_reason == 'refusal':
            reply = '这条请求助手没法处理，换个说法试试。'
            break
        if resp.stop_reason == 'pause_turn':
            continue
        uses = [b for b in resp.content if b.type == 'tool_use']
        reply = '\n'.join(b.text for b in resp.content if b.type == 'text').strip() or reply
        if resp.stop_reason != 'tool_use' or not uses:
            break
        results = []
        for b in uses:
            try:
                out, note = _run_tool(pid, b.name, b.input if isinstance(b.input, dict) else {})
                if note:
                    changes.append(note)
                results.append(dict(type='tool_result', tool_use_id=b.id, content=out))
            except (ValueError, KeyError, TypeError, PermissionError, FileNotFoundError) as exc:
                results.append(dict(type='tool_result', tool_use_id=b.id, content=f'出错：{exc}', is_error=True))
        messages.append(dict(role='user', content=results))
    else:
        reply = reply or '步骤太多，先停在这里。看看时间线，有需要再接着说。'
    p = studio.load(pid)
    p['agent_messages'] = messages
    p.setdefault('chat', []).append(dict(role='user', text=text))
    p['chat'].append(dict(role='assistant', text=reply, changes=changes))
    studio.save(p)
    return studio.public(p)


def reset(pid: str) -> dict:
    p = studio.load(pid)
    p['agent_messages'] = []
    p['chat'] = []
    return studio.public(studio.save(p))
