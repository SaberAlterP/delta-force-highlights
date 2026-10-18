"""Read official local event markers without modifying the WeGame database.

Event names follow the official replay web client (2026-10-18):
https://replay-cnprod.df.qq.com/cnprod/assets/index-BqCsiO6G.js
The database stores event IDs, not the literal display names. Names and timestamps
are independent of OCR; target identity still requires local visual verification.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import ntpath
import os
from pathlib import Path
import shutil
import subprocess
import threading


VERSION = 'wegame-events-v1'
EVENT_NAMES = {**{str(i): '击杀' for i in (1000801,1000802,1000803,1000804,
    1000822,1000842,1000843,1000844)},
    **{str(i): '摸金' for i in range(1000811,1000818)},
    **{str(i): '载具摧毁' for i in range(1000831,1000837)},
    '1000810':'对局开始','1000800':'对局结束'}


def normalized_path(value):
    return ntpath.normcase(ntpath.normpath(str(value).replace('/', '\\')))


def nested(value, default):
    if isinstance(value, str):
        try:return json.loads(value)
        except (ValueError,TypeError):return default
    return value if isinstance(value,type(default)) else default


def parse_record(row, recording, player_id=''):
    info=row.get('gameInfo',{})
    videos=[v for v in row.get('videos',[]) if v.get('highLightType')==1
            and normalized_path(v.get('videoSrc',''))==normalized_path(recording)]
    if len(videos)!=1:return None
    if player_id and info.get('user_name')!=player_id:
        raise ValueError('官方事件所属玩家与当前游戏 ID 不符，保留原片')
    video=videos[0]
    duration=float(video.get('duration',0))/1000
    if not math.isfinite(duration) or duration<=0:raise ValueError('官方录像时长无效')
    marks=[];seen=set();warnings=[];counts={}
    for clip in video.get('clips',[]):
        for event in clip.get('events',[]):
            event_id=str(event.get('id',''))
            name=EVENT_NAMES.get(event_id,'未知事件 '+event_id)
            ext=nested(event.get('ext'),{})
            items=nested(ext.get('itemInfo'),[])
            # A repeated clip can contain the same event; an identical timestamp
            # with a different anchor ID can represent two simultaneous kills.
            for index,anchor in enumerate(event.get('anchors',[])):
                stamp=float(anchor.get('time',-1))/1000
                if not math.isfinite(stamp) or not 0<=stamp<=duration:
                    warnings.append('忽略了超出录像时长的事件点');continue
                key=(event_id,event.get('realStartTime'),anchor.get('prefix'),
                     anchor.get('id'),anchor.get('time'))
                if key in seen:continue
                seen.add(key)
                kind={'击杀':'kill','摸金':'loot','载具摧毁':'vehicle'}.get(name,'other')
                counts[name]=counts.get(name,0)+1
                label=f'{name}{counts[name]}'
                item=items[index] if index<len(items) and isinstance(items[index],dict) else {}
                if kind=='loot' and item.get('item_name'):label+=' · '+str(item['item_name'])
                anchor_ext=nested(anchor.get('ext'),{})
                if kind=='other' and anchor_ext.get('broadcast'):label=str(anchor_ext['broadcast'])
                identity=hashlib.sha256(json.dumps(key,ensure_ascii=False).encode()).hexdigest()[:24]
                marks.append(dict(id='wg_'+identity,time=round(stamp,3),label=label,
                    event_name=name,event_type=kind,source='wegame',confidence=1.,
                    confirmed=False,review_required=kind=='kill',victim_id='',
                    official_event_id=event_id,anchor_prefix=anchor.get('prefix'),
                    anchor_id=anchor.get('id'),item_name=item.get('item_name',''),
                    prompt_text=label,id_text='官方本地事件记录'))
    stats=info.get('stats',{})
    total=stats.get('kills')
    if isinstance(total,bool) or not isinstance(total,(int,float)) or total<0:total=None
    kill_points=sum(m['event_type']=='kill' for m in marks)
    if total is not None and kill_points!=total:
        warnings.append(f'官方结算 {int(total)} 杀，记录了 {kill_points} 个击杀事件点；两者分别显示')
    compact=dict(marks=sorted(marks,key=lambda m:m['time']),official_kills=int(total) if total is not None else None,
        kill_points=kill_points,loot_points=sum(m['event_type']=='loot' for m in marks),
        duration=duration,video_id=str(video.get('id','')),matches_id=str(info.get('matches_id','')),
        player_id=info.get('user_name',''),warnings=list(dict.fromkeys(warnings)),version=VERSION)
    compact['signature']=hashlib.sha256(json.dumps(compact,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    return compact


def verification_windows(data, duration, before=2., after=5.):
    windows=[]
    for mark in data['marks']:
        if mark['event_type']!='kill':continue
        start,end=max(0.,mark['time']-before),min(duration,mark['time']+after)
        if end<=start:continue
        if windows and start<=windows[-1][1]:windows[-1][1]=max(windows[-1][1],end)
        else:windows.append([start,end])
    return windows


def verified_marks(data, observations):
    """Bind verified distinct targets one-to-one; never invent target identities."""
    from .highlights import confirmed_events
    marks=copy.deepcopy(data['marks'])
    targets=confirmed_events(observations)
    pairs=sorted((abs(m['time']-o['time']),i,j)
        for i,m in enumerate(marks) if m['event_type']=='kill'
        for j,o in enumerate(targets) if abs(m['time']-o['time'])<=7.)
    used_marks=set();used_targets=set()
    for _,i,j in pairs:
        if i in used_marks or j in used_targets:continue
        used_marks.add(i);used_targets.add(j)
        mark,observed=marks[i],targets[j]
        mark.update(confirmed=True,review_required=False,victim_id=observed['victim_id'],
            confidence=observed.get('confidence',.9),id_text=observed.get('id_text',''),
            verification_time=observed['time'],verification_source=observed.get('source','feed'))
    return marks


class EventIndex:
    def __init__(self, directory=None):
        self.directory=Path(directory) if directory else default_directory()
        self._cache={};self._lock=threading.Lock()

    def find(self, recording, player_id=''):
        if not self.directory.is_dir():return None
        parts=ntpath.normpath(str(recording)).split('\\')
        account=parts[-3] if len(parts)>=3 and parts[-2].lower()=='record' and parts[-3].isdecimal() else None
        files=[self.directory/account] if account else list(self.directory.iterdir())
        with self._lock:
            for file in files:
                if not file.name.isdecimal() or not file.is_file():continue
                stat=file.stat();fingerprint=(stat.st_size,stat.st_mtime_ns)
                if stat.st_size>64*1024*1024:raise ValueError('官方事件数据库过大，停止读取')
                if self._cache.get(file,{}).get('fingerprint')!=fingerprint:
                    node=shutil.which('node')
                    if not node:raise RuntimeError('读取官方事件需要本地 Node.js')
                    result=subprocess.run([node,str(Path(__file__).with_name('wegame_decode.cjs')),str(file)],
                        capture_output=True,timeout=15,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
                    if result.returncode:
                        if account:raise DatabaseBusy('官方事件数据库暂时无法读取，可能仍在保存；稍后重试')
                        continue
                    data=json.loads(result.stdout)
                    if not isinstance(data,list):raise ValueError('官方事件数据库结构已改变')
                    after=file.stat()
                    if (after.st_size,after.st_mtime_ns)!=fingerprint:
                        raise DatabaseBusy('官方事件数据库仍在保存；稍后重试')
                    self._cache[file]=dict(fingerprint=fingerprint,rows=data)
                for row in self._cache[file]['rows']:
                    found=parse_record(row,recording,player_id)
                    if found:return found
        return None


class DatabaseBusy(ValueError):pass


def default_directory():
    return Path(os.environ.get('APPDATA',''))/'icreate-pc-df'/'wonderfulDb'


index=EventIndex()
_indexes={}


def index_for(directory=''):
    # 设置里留空时用默认目录；同一目录复用解码缓存。
    if not directory:return index
    return _indexes.setdefault(str(directory),EventIndex(directory))


def describe(directory=''):
    """设置页用：目录是否存在、有几个账号数据库、本机有没有 Node.js。"""
    path=Path(directory) if directory else default_directory()
    found=[f for f in path.iterdir() if f.is_file() and f.name.isdecimal()] if path.is_dir() else []
    return dict(path=str(path),exists=path.is_dir(),accounts=len(found),node=bool(shutil.which('node')))
