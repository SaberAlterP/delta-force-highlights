"""检测用户是否正在玩游戏：进程名单 + 前台全屏程序。只用 Windows 自带接口，无额外依赖。"""
from __future__ import annotations

import csv
import io
import os
import subprocess
import time

# 常见游戏进程（小写）。用户可在设置里追加。
KNOWN_GAMES = {
    'deltaforceclient-win64-shipping.exe',   # 三角洲行动
    'cs2.exe', 'valorant-win64-shipping.exe', 'r5apex.exe', 'r5apex_dx12.exe',
    'tslgame.exe', 'fortniteclient-win64-shipping.exe', 'overwatch.exe',
    'league of legends.exe', 'narakabladepoint.exe', 'gta5.exe', 'cod.exe',
    'eldenring.exe', 'bf2042.exe', 'rainbowsix.exe', 'yuanshen.exe', 'starrail.exe',
    'cf.exe', 'crossfire.exe', 'dnf.exe',
}
# 这些程序全屏通常是在看视频，不算玩游戏
FULLSCREEN_IGNORED = {'msedge.exe', 'chrome.exe', 'firefox.exe', 'opera.exe', 'brave.exe',
                      'explorer.exe', 'potplayermini64.exe', 'vlc.exe', 'mpc-hc64.exe'}


def _process_names() -> set[str]:
    if os.name != 'nt':
        return set()
    try:
        out = subprocess.run(['tasklist', '/fo', 'csv', '/nh'], capture_output=True, timeout=10,
                             creationflags=subprocess.CREATE_NO_WINDOW).stdout
    except (OSError, subprocess.SubprocessError):
        return set()
    text = out.decode('mbcs', errors='ignore') if hasattr(out, 'decode') else out
    return {row[0].lower() for row in csv.reader(io.StringIO(text)) if row}


def _fullscreen_process() -> str:
    """前台窗口铺满整个显示器时返回它的进程名，否则返回空。"""
    if os.name != 'nt':
        return ''
    import ctypes
    from ctypes import wintypes
    user32, kernel32 = ctypes.windll.user32, ctypes.windll.kernel32
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return ''
    name = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, name, 256)
    if name.value in ('Progman', 'WorkerW', 'Shell_TrayWnd'):
        return ''
    rect = wintypes.RECT()
    if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        return ''

    class MONITORINFO(ctypes.Structure):
        _fields_ = [('cbSize', wintypes.DWORD), ('rcMonitor', wintypes.RECT),
                    ('rcWork', wintypes.RECT), ('dwFlags', wintypes.DWORD)]
    info = MONITORINFO(cbSize=ctypes.sizeof(MONITORINFO))
    monitor = user32.MonitorFromWindow(hwnd, 2)
    if not user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
        return ''
    m = info.rcMonitor
    if (rect.left, rect.top, rect.right, rect.bottom) != (m.left, m.top, m.right, m.bottom):
        return ''
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    handle = kernel32.OpenProcess(0x1000, False, pid.value)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return '全屏程序'
    try:
        size = wintypes.DWORD(1024)
        path = ctypes.create_unicode_buffer(1024)
        if kernel32.QueryFullProcessImageNameW(handle, 0, path, ctypes.byref(size)):
            return os.path.basename(path.value).lower()
        return '全屏程序'
    finally:
        kernel32.CloseHandle(handle)


def parse_names(text: str) -> set[str]:
    names = set()
    for part in (text or '').replace('，', ',').replace('\n', ',').split(','):
        part = part.strip().lower()
        if part:
            names.add(part if part.endswith('.exe') else part + '.exe')
    return names


class GameDetector:
    """带缓存的检测：识别子进程每 0.25 秒问一次是否要让路，实际最多每 5 秒查一次系统。"""

    def __init__(self, ttl: float = 5):
        self.ttl = ttl
        self._at = 0.
        self._key = None
        self._reason = ''

    def reason(self, extra: str = '', fullscreen: bool = True) -> str:
        key = (extra, fullscreen)
        now = time.monotonic()
        if key == self._key and now - self._at < self.ttl:
            return self._reason
        names = _process_names()
        hit = sorted(names & (KNOWN_GAMES | parse_names(extra)))
        reason = f'检测到 {hit[0]} 正在运行' if hit else ''
        if not reason and fullscreen:
            exe = _fullscreen_process()
            if exe and exe not in FULLSCREEN_IGNORED:
                reason = f'检测到全屏程序 {exe}'
        self._key, self._at, self._reason = key, now, reason
        return reason


detector = GameDetector()
