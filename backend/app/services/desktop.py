"""在资源管理器里打开文件夹，并把窗口拉到前台。

后端是后台进程，没有前台权限：直接启动 explorer 时 Windows 会把新窗口压在浏览器后面，
同一文件夹已打开时也只是在任务栏闪一下。这里等窗口出现后用 Alt 键解除前台锁再激活它。
"""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import threading
import time


def open_folder(path: Path) -> None:
    if os.name != 'nt':
        return
    subprocess.Popen(['explorer.exe', str(path)], creationflags=subprocess.CREATE_NO_WINDOW)
    threading.Thread(target=bring_to_front, args=(Path(path),), daemon=True,
                     name='explorer-focus').start()


def find_window(path: Path):
    """资源管理器窗口标题是文件夹名；开了「标题栏显示完整路径」时是完整路径。"""
    import ctypes
    from ctypes import wintypes
    user32 = ctypes.windll.user32
    titles = {path.name, str(path)}
    found = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def visit(hwnd, _):
        buf = ctypes.create_unicode_buffer(1024)
        user32.GetClassNameW(hwnd, buf, 1024)
        if buf.value == 'CabinetWClass' and user32.IsWindowVisible(hwnd):
            user32.GetWindowTextW(hwnd, buf, 1024)
            # Win11 标题带「 - 文件资源管理器」这类后缀
            if buf.value in titles or any(buf.value.startswith(t + ' - ') for t in titles):
                found.append(hwnd)
        return True

    user32.EnumWindows(visit, 0)
    return found[0] if found else None


def bring_to_front(path: Path, timeout: float = 6.) -> bool:
    try:
        import ctypes
        user32 = ctypes.windll.user32
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            hwnd = find_window(path)
            if hwnd:
                if user32.IsIconic(hwnd):
                    user32.ShowWindow(hwnd, 9)  # SW_RESTORE
                # 模拟按下并松开 Alt，系统才允许后台进程切换前台窗口
                user32.keybd_event(0x12, 0, 0, 0)
                user32.keybd_event(0x12, 0, 2, 0)
                user32.SetForegroundWindow(hwnd)
                user32.BringWindowToTop(hwnd)
                return user32.GetForegroundWindow() == hwnd
            time.sleep(.15)
    except Exception:
        pass
    return False
