"""歌曲分析：节拍（对准底鼓）+ 按"重"排序的重音。输出 song.json。"""
import json

from . import accents


def analyze(wav, cfg):
    info = accents.analyze(wav, top=cfg['song']['top_accents'])
    info['path'] = wav
    return info


def save(info, path):
    json.dump(info, open(path, 'w'), indent=1)


def load(path):
    return json.load(open(path))
