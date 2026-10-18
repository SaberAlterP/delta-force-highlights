"""无需常驻浏览器的 Windows 完成通知；失败由网页显示，可重试。"""
import base64
import json
import os
import subprocess
from xml.sax.saxutils import escape


def send(title: str, body: str, tag: str = 'complete') -> dict:
    if os.name != 'nt':
        return dict(sent=False, error='仅 Windows 支持桌面通知')
    xml = (f'<toast activationType="protocol" launch="http://127.0.0.1:8000/">'
           f'<visual><binding template="ToastGeneric"><text>{escape(title)}</text>'
           f'<text>{escape(body)}</text></binding></visual>'
           '<actions><action content="查看集锦" activationType="protocol" '
           'arguments="http://127.0.0.1:8000/"/></actions></toast>')
    payload = base64.b64encode(xml.encode('utf-8')).decode('ascii')
    # 仅固定程序和 base64 XML 入脚本，不把文件名/游戏 ID 作为 PowerShell 代码。
    script = r'''
$ErrorActionPreference = 'Stop'
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType=WindowsRuntime] > $null
[Windows.UI.Notifications.ToastNotification, Windows.UI.Notifications, ContentType=WindowsRuntime] > $null
[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType=WindowsRuntime] > $null
$AppId = '{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe'
$Notifier = [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($AppId)
if ([int]$Notifier.Setting -ne 0) { throw ('Windows 通知被关闭，状态=' + $Notifier.Setting) }
$Document = New-Object Windows.Data.Xml.Dom.XmlDocument
$Document.LoadXml([Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('PAYLOAD')))
$Toast = [Windows.UI.Notifications.ToastNotification]::new($Document)
$Toast.Tag = 'delta-complete'
$Toast.Group = 'delta-clips'
$Notifier.Show($Toast)
'''.replace('PAYLOAD', payload)
    command = base64.b64encode(script.encode('utf-16-le')).decode('ascii')
    try:
        proc = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-WindowStyle',
                               'Hidden', '-EncodedCommand', command], capture_output=True,
                              timeout=20, encoding='utf-8', errors='replace',
                              creationflags=subprocess.CREATE_NO_WINDOW)
        return dict(sent=proc.returncode == 0,
                    error='' if proc.returncode == 0 else proc.stderr[-600:])
    except (OSError, subprocess.TimeoutExpired) as exc:
        return dict(sent=False, error=str(exc))
