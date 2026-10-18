"""视频分段响应：每次只读一小段到内存后立即关闭文件。

FileResponse 对「bytes=0-」会一直流到文件末尾；浏览器缓冲够了就暂停读取，
连接和 Windows 文件句柄会长期挂着。这样既删不掉正在看过的原片，
同一站点的连接数被占满后，新打开的视频也会黑屏。
"""
from __future__ import annotations

from pathlib import Path
import re

from fastapi import Request
from fastapi.responses import FileResponse, Response

CHUNK = 4 * 1024 * 1024
_RANGE = re.compile(r'bytes=(\d*)-(\d*)$')


def video_response(path: Path, request: Request, media_type: str = 'video/mp4', filename: str | None = None):
    header = request.headers.get('range')
    if not header:
        # 无 Range 只出现在直接下载时，按原样整体返回。
        return FileResponse(path, media_type=media_type, filename=filename)
    size = path.stat().st_size
    match = _RANGE.match(header.strip())
    if not match or (not match[1] and not match[2]):
        return Response(status_code=416, headers={'Content-Range': f'bytes */{size}'})
    if match[1]:
        start = int(match[1])
        end = int(match[2]) if match[2] else size - 1
    else:  # bytes=-N：最后 N 字节
        start = max(0, size - int(match[2]))
        end = size - 1
    if start >= size or end < start:
        return Response(status_code=416, headers={'Content-Range': f'bytes */{size}'})
    end = min(end, size - 1, start + CHUNK - 1)
    with path.open('rb') as handle:
        handle.seek(start)
        data = handle.read(end - start + 1)
    return Response(data, status_code=206, media_type=media_type, headers={
        'Content-Range': f'bytes {start}-{start + len(data) - 1}/{size}',
        'Accept-Ranges': 'bytes',
        'Cache-Control': 'no-store',
    })
