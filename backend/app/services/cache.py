"""清理可再生成的缓存，保留输出成片、模型、队列及正在使用的文件。"""
import json
import os
from pathlib import Path
import re
import threading
import time

from .. import config
from .archive import atomic_json, sha256


class CacheManager:
    def __init__(self, root=None):
        self.root = Path(root or config.STORAGE_DIR)
        self.index = self.root/'workflow'/'cache-index.json'
        self.lock = threading.RLock()
        self.aliases = {}
        self.last = dict(removed_files=0, removed_bytes=0, checked_at=None)
        if self.index.exists():
            self.aliases = json.loads(self.index.read_text(encoding='utf-8'))

    def touch(self,path):
        path = Path(path)
        with self.lock:
            stat = path.stat()
            if time.time()-stat.st_atime > 30:
                os.utime(path, ns=(time.time_ns(), stat.st_mtime_ns))

    def _save(self):
        self.index.parent.mkdir(parents=True, exist_ok=True)
        atomic_json(self.index, self.aliases)

    def _category_root(self,name):
        raw=self.root/name
        resolved=raw.resolve()
        if raw.is_symlink() or not resolved.is_relative_to(self.root.resolve()):return None
        return resolved

    def alias(self, upload_id):
        value = self.aliases.get(upload_id)
        if value and Path(value).is_file():
            return Path(value)
        return None

    def relocate_aliases(self, old, new):
        changed=False
        with self.lock:
            for key,value in list(self.aliases.items()):
                path=Path(value)
                if path.is_relative_to(old):
                    self.aliases[key]=str(new/path.relative_to(old));changed=True
            if changed:self._save()

    def deduplicate_uploads(self, original, digest, *, closed, busy=False):
        if busy:
            return dict(removed_files=0, removed_bytes=0)
        original = Path(original)
        removed = dict(removed_files=0, removed_bytes=0)
        root = self._category_root('uploads')
        if root is None:return removed
        with self.lock:
            for path in root.glob('*'):
                try:
                    if (path.is_symlink() or not path.resolve().is_relative_to(root)
                            or not path.is_file() or path.stat().st_size != original.stat().st_size
                            or path.resolve() == original.resolve() or not closed(path)
                            or sha256(path) != digest):
                        continue
                    # 先保存播放别名，再移除逐字节相同的上传副本。
                    self.aliases[path.stem] = str(original.resolve())
                    self._save()
                    size = path.stat().st_size
                    path.unlink()
                    removed['removed_files'] += 1
                    removed['removed_bytes'] += size
                except OSError:
                    continue
        return removed

    def cleanup(self, *, now=None, closed, busy=False, active_workers=()):
        now = time.time() if now is None else now
        removed = dict(removed_files=0, removed_bytes=0, checked_at=now)
        active_workers = {Path(p).resolve() for p in active_workers}
        plans = [('chunks',86400), ('tmp',86400), ('uploads',7*86400)]
        if not busy:
            for folder, age in plans:
                root = self._category_root(folder)
                if root is None:continue
                for path in root.rglob('*') if root.exists() else ():
                    try:
                        if (path.is_symlink() or not path.resolve().is_relative_to(root)
                                or not path.is_file()):
                            continue
                        stat = path.stat()
                        if max(stat.st_mtime,stat.st_atime) > now-age or not closed(path):
                            continue
                        path.unlink()
                        removed['removed_files'] += 1;removed['removed_bytes'] += stat.st_size
                    except OSError:
                        continue
        workers = self._category_root('workflow/workers')
        known = {'request.json','result.json','progress.json','worker.log',
                 'result.json.tmp','progress.json.tmp','result.writing','progress.writing'}
        for directory in workers.iterdir() if workers and workers.exists() else ():
            if (not re.fullmatch('[0-9a-f]{32}',directory.name) or directory.is_symlink()
                    or not directory.resolve().is_relative_to(workers)
                    or directory.resolve() in active_workers or not directory.is_dir()):
                continue
            files = list(directory.iterdir())
            if any(p.name not in known or not p.is_file() or p.is_symlink() for p in files):
                continue
            if any(max(p.stat().st_mtime,p.stat().st_atime)>now-7*86400 for p in files):
                continue
            for path in files:
                try:
                    if closed(path):
                        size=path.stat().st_size;path.unlink()
                        removed['removed_files']+=1;removed['removed_bytes']+=size
                except OSError:
                    pass
            try:directory.rmdir()
            except OSError:pass
        # 只移除已空的暂存子目录，不进行目录递归删除。
        if not busy:
            for name in ('chunks','tmp'):
                root=self._category_root(name)
                if root is None:continue
                for path in sorted(root.rglob('*'),key=lambda p:len(p.parts),reverse=True) if root.exists() else ():
                    if not path.is_symlink() and path.resolve().is_relative_to(root):
                        try:path.rmdir()
                        except OSError:pass
        with self.lock:
            expired=[k for k,v in self.aliases.items() if not Path(v).exists()]
            for key in expired:self.aliases.pop(key)
            if expired:self._save()
        self.last=removed
        return removed

    def deduplicate_legacy_exports(self,files,*,closed):
        root=(config.BASE_DIR.parent/'outputs'/'highlights').resolve()
        targets={(item['size'],item['sha256']):item['path'] for item in files}
        removed=0
        for manifest in root.glob('*/识别记录.json'):
            try:
                data=json.loads(manifest.read_text(encoding='utf-8'))
                for item in data.get('files',[]):
                    path=Path(item['path'])
                    if (path.is_symlink() or path.resolve().parent!=manifest.parent.resolve()
                            or not path.resolve().is_relative_to(root) or not path.is_file()
                            or not any(size==path.stat().st_size for size,_ in targets)
                            or not closed(path)):
                        continue
                    digest=sha256(path)
                    dest=targets.get((path.stat().st_size,digest))
                    if dest and path.resolve()!=Path(dest).resolve():
                        # 已归档成片仍在，且完整哈希相同，才移除旧验证目录中的重复副本。
                        if Path(dest).is_file() and sha256(Path(dest))==digest:
                            path.unlink();removed+=1
                # 只移除我们已知的旧识别记录和空目录，未知文件原样保留。
                if not any(manifest.parent.glob('*.mp4')):
                    manifest.unlink()
                    try:manifest.parent.rmdir()
                    except OSError:pass
            except (OSError,ValueError,KeyError):continue
        return removed


cache = CacheManager()
