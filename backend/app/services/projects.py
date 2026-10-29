"""归档目录里的剪辑工程数据；视频始终原位引用，不复制原片。"""
import json
import math
from pathlib import Path
import re
import time
import uuid

from .archive import atomic_json

SOURCE_ID=re.compile(r'^bundle_([0-9a-f]{32})(?:_clip_([0-9a-f]{12}))?$')


def directory(row):
    if not row or not row['archive_dir']:raise ValueError('这段录像尚未归档')
    path=Path(row['archive_dir'])
    if (path.is_symlink() or path.resolve().parent!=Path(row['archive_root']).resolve()
            or json.loads((path/'归档标识.json').read_text(encoding='utf-8')).get('recording_id')!=row['id']):
        raise ValueError('归档目录身份校验失败')
    return path


def load(row):
    path=directory(row)/'剪辑工程.json'
    if path.exists():return json.loads(path.read_text(encoding='utf-8'))
    return dict(version=1,recording_id=row['id'],sources={},manual_exports=[])


def save(row,value):
    atomic_json(directory(row)/'剪辑工程.json',value)


def _clean_segments(segments):
    if segments is None:return None
    if not isinstance(segments,list) or len(segments)>2000:raise ValueError('无效的片段数据')
    clean=[]
    for seg in segments:
        start,end=float(seg['start']),float(seg['end'])
        if not (math.isfinite(start) and math.isfinite(end) and 0<=start<end):raise ValueError('无效的片段范围')
        label=str(seg.get('label',''))[:200]
        clean.append(dict(id=str(seg.get('id',''))[:40],start=round(start,3),end=round(end,3),label=label,
                          selected=seg.get('selected') is not False))
    return clean


def save_marks(row,source_id,kills,segments=None):
    match=SOURCE_ID.fullmatch(source_id)
    if not match or match[1]!=row['id'] or not isinstance(kills,list) or len(kills)>5000:
        raise ValueError('无效的剪辑工程数据')
    segments=_clean_segments(segments)
    allowed={'id','time','label','pre','post','selected','confidence','id_text','prompt_text',
             'victim_id','confirmed','review_required','event_type','source'}
    clean=[]
    for mark in kills:
        item={key:value for key,value in mark.items() if key in allowed}
        stamp=float(item.get('time',0))
        if not math.isfinite(stamp) or stamp<0:raise ValueError('无效的时间点')
        item['time']=stamp
        for key in ('pre','post'):
            if key in item:
                value=float(item[key])
                if not math.isfinite(value) or not 0<=value<=300:raise ValueError('无效的剪辑时长')
                item[key]=value
        for key,value in item.items():
            if isinstance(value,str) and len(value)>500:raise ValueError('工程文字过长')
        clean.append(item)
    value=load(row)
    entry=dict(kills=clean,updated_at=time.time())
    previous=value['sources'].get(source_id,{})
    if segments is not None:entry['segments']=segments
    elif 'segments' in previous:entry['segments']=previous['segments']
    value['sources'][source_id]=entry
    save(row,value)
    return len(clean)


def manual_exports(row):
    return load(row).get('manual_exports',[])


def flatten_manual_exports(row):
    """旧版把手动剪辑放在「手动剪辑/<导出编号>/」里；挪到集锦包根目录，和自动高光放一起。"""
    base=directory(row)
    old=base/'手动剪辑'
    value=load(row)
    moved=0
    for entry in value.get('manual_exports',[]):
        for item in entry['files']:
            path=base/item['path']
            # 只挪旧子目录里的文件，记录指向别处（比如整局原片）时不碰
            if (not item['path'].startswith('手动剪辑/') or path.is_symlink() or not path.is_file()
                    or not path.resolve().is_relative_to(old.resolve())):continue
            name=item['name'] if item['name'].startswith('手动') else '手动_'+item['name']
            target=base/name
            if target.exists():target=target.with_stem(target.stem+'_'+uuid.uuid4().hex[:6])
            path.rename(target)
            item.update(name=target.name,path=target.name)
            moved+=1
    if moved:
        save(row,value)
        # 只删已经空了的旧目录
        for folder in sorted(old.rglob('*'),key=lambda p:len(p.parts),reverse=True) if old.is_dir() else ():
            if folder.is_dir() and not folder.is_symlink():
                try:folder.rmdir()
                except OSError:pass
        try:old.rmdir()
        except OSError:pass
    return moved
