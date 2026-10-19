"""开机自启：在当前用户的「启动」文件夹放一个静默启动后端的快捷方式。只用系统自带的 PowerShell。"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess

from .. import config

ROOT = config.BASE_DIR.parent
SCRIPT = ROOT / 'start-monitor.ps1'
LINK_NAME = '三角洲多杀集锦.lnk'
_NO_WINDOW = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0


def _ps(command: str, env: dict | None = None) -> str:
    out = subprocess.run(['powershell', '-NoProfile', '-NonInteractive', '-Command', command],
                         capture_output=True, text=True, encoding='utf-8', timeout=30,
                         creationflags=_NO_WINDOW, env={**os.environ, **(env or {})})
    if out.returncode:
        raise RuntimeError(out.stderr.strip() or 'PowerShell 执行失败')
    return out.stdout


def _links() -> list[dict]:
    """启动文件夹里所有指向本项目 start-monitor.ps1 的快捷方式（包括别处建的）。"""
    script = r'''
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$dir = [Environment]::GetFolderPath('Startup'); $sh = New-Object -ComObject WScript.Shell
$items = @(Get-ChildItem -LiteralPath $dir -Filter *.lnk -ErrorAction SilentlyContinue | ForEach-Object {
  $l = $sh.CreateShortcut($_.FullName); @{ path = $_.FullName; args = $l.Arguments } })
ConvertTo-Json -InputObject $items -Compress
'''
    items = json.loads(_ps(script) or '[]') or []
    target = str(SCRIPT).lower()
    return [i for i in items if target in (i.get('args') or '').lower()]


def status() -> dict:
    if os.name != 'nt':
        return dict(supported=False, enabled=False, links=[])
    links = _links()
    return dict(supported=True, enabled=bool(links), links=[Path(i['path']).name for i in links])


def set_enabled(enabled: bool) -> dict:
    if os.name != 'nt':
        raise RuntimeError('开机自启只支持 Windows')
    if not SCRIPT.is_file():
        raise RuntimeError(f'找不到启动脚本：{SCRIPT}')
    links = _links()
    if enabled and not links:
        # 路径经环境变量传入，避免引号和中文路径的转义问题
        _ps(r'''
$link = Join-Path ([Environment]::GetFolderPath('Startup')) $env:DF_LINK
$s = (New-Object -ComObject WScript.Shell).CreateShortcut($link)
$s.TargetPath = "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe"
$s.Arguments = '-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "' + $env:DF_SCRIPT + '"'
$s.WorkingDirectory = $env:DF_ROOT
$s.WindowStyle = 7
$s.Description = '三角洲多杀集锦：开机后在后台监控录像'
$s.Save()
''', env=dict(DF_LINK=LINK_NAME, DF_SCRIPT=str(SCRIPT), DF_ROOT=str(ROOT)))
    elif not enabled:
        for item in links:
            # 只删指向本项目启动脚本的快捷方式
            Path(item['path']).unlink(missing_ok=True)
    return status()
