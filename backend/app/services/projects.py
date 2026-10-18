"""归档目录里的剪辑工程数据；视频始终原位引用，不复制原片。"""
import json
import math
from pathlib import Path
import re
import time

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


def save_marks(row,source_id,kills):
    match=SOURCE_ID.fullmatch(source_id)
    if not match or match[1]!=row['id'] or not isinstance(kills,list) or len(kills)>5000:
        raise ValueError('无效的剪辑工程数据')
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
    value['sources'][source_id]=dict(kills=clean,updated_at=time.time())
    save(row,value)
    return len(clean)


def manual_exports(row):
    return load(row).get('manual_exports',[])
