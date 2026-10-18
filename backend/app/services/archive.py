"""单份整局录像的归档：跨盘复制校验后才移除源文件，支持中断恢复。"""
from concurrent.futures import CancelledError
from datetime import datetime, timezone, timedelta
import hashlib
import json
import os
from pathlib import Path
import re
import shutil


LOCAL_TIME = timezone(timedelta(hours=8))


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def fingerprint(path: Path) -> str:
    stat = path.stat()
    return f'{stat.st_size}:{stat.st_mtime_ns}'


def atomic_json(path: Path, value):
    temp = path.with_suffix(path.suffix + '.writing')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(temp, path)


def recording_time(path: str) -> str:
    match = re.fullmatch(r'record(\d{8})-(\d{6})\.mp4', Path(path).name, re.I)
    if not match:
        raise ValueError('录像文件名没有可识别的录制时间')
    return datetime.strptime(''.join(match.groups()), '%Y%m%d%H%M%S').replace(
        tzinfo=LOCAL_TIME).isoformat()


def bundle_name(path: str, record_id: str, kills: int, has_highlights: bool, *, official=False) -> str:
    stamp = datetime.fromisoformat(recording_time(path)).strftime('%Y-%m-%d_%H-%M-%S')
    return f'{stamp}_全局{"" if official else "识别"}{kills}杀_{"有集锦" if has_highlights else "无集锦"}_{record_id[:8]}'


def _same_volume(source,directory):
    return source.stat().st_dev == directory.stat().st_dev


def move_verified(source: Path, dest: Path, expected_fp: str, *, closed, commit,
                  cancelled=lambda: False) -> str:
    """commit 在删除 E 盘来源之前持久化 D 盘文件的校验记录。"""
    source, dest = Path(source), Path(dest)
    if source.is_symlink() or dest.is_symlink() or dest.parent.is_symlink():
        raise RuntimeError('拒绝归档符号链接')
    if fingerprint(source) != expected_fp or not closed(source):
        raise RuntimeError('原片仍在写入或已改变，暂不移动')
    if cancelled():
        raise CancelledError()
    if source.resolve() == dest.resolve():
        digest = sha256(source)
        commit(digest, fingerprint(source))
        return digest
    digest = sha256(source)
    if dest.exists():
        if dest.stat().st_size != source.stat().st_size or sha256(dest) != digest:
            raise RuntimeError('归档目标已存在且内容不同，保留两边文件等待复核')
    else:
        # D 盘内重命名不复制；E -> D 最多临时多占一份，复制校验后立刻释放 E。
        if _same_volume(source,dest.parent):
            commit(digest, expected_fp)
            if cancelled():
                raise CancelledError()
            source.rename(dest)
            return digest
        partial = dest.with_suffix('.mp4.partial')
        if partial.exists():
            # 只处理本次归档的精确临时文件，且源文件已经确认完整、仍然存在。
            if partial.is_symlink():
                raise RuntimeError('归档临时文件为符号链接')
            partial.unlink()
        try:
            with source.open('rb') as src, partial.open('xb') as target:
                while block := src.read(8 * 1024 * 1024):
                    if cancelled():
                        raise CancelledError()
                    target.write(block)
                target.flush()
                os.fsync(target.fileno())
            if fingerprint(source) != expected_fp or sha256(partial) != digest:
                raise RuntimeError('跨盘归档校验不一致，原片保留')
            shutil.copystat(source, partial)
            partial.rename(dest)
        except BaseException:
            if partial.exists() and not partial.is_symlink():
                partial.unlink()
            raise
    if fingerprint(source) != expected_fp or not closed(source):
        raise RuntimeError('复制期间源文件改变或被占用，暂不移除来源')
    commit(digest, fingerprint(dest))
    if cancelled():
        raise CancelledError()
    source.unlink()
    return digest
