# -*- coding: utf-8 -*-
"""Windows 系统通知（Toast）。

为什么要单独写这个：
    登录态是有硬到期的（实测超星 10-15、雨课堂 10-21，反复同步不会续期），
    而工作台里的橙色提示只有「打开了页面」才看得见。定时同步是在后台跑的，
    如果不主动弹一下，用户往往要等到某天发现数据不更新才知道出了事。

设计取舍：
    - 发通知这件事交给 PowerShell 的 WinRT Toast —— Windows 上唯一不需要装
      第三方库、也不需要常驻托盘进程的官方姿势。
    - 中文走命令行参数会被 PowerShell 5.1 按 ANSI 解析成乱码，所以标题/正文
      一律写进 UTF-8 的 JSON 文件，命令行只传路径。
    - notify.ps1 内部刻意只用 ASCII，避免脚本自己被编码坑到。
    - 通知失败绝不能影响同步主流程，所以全程吞异常 + 短超时 + 有开关。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
STATE = HERE / "state"
PAYLOAD = STATE / "notify.json"
RESULT = STATE / "notify-result.txt"
PS1 = HERE / "notify.ps1"

# 用系统自带的 PowerShell AppID 发通知是稳的；自定义 AppID 需要注册开始菜单
# 快捷方式，在无窗口的定时任务里容易静默失败。
_ENV_OFF = ("WB_NO_NOTIFY", "1")


def enabled() -> bool:
    """允许用环境变量临时关掉通知（排查同步问题时很有用）。"""
    return os.environ.get("WB_NO_NOTIFY", "") not in _ENV_OFF


def _powershell() -> str:
    cand = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / \
        "WindowsPowerShell" / "v1.0" / "powershell.exe"
    if cand.exists():
        return str(cand)
    return "powershell"


def send(title: str, body: str, timeout: int = 25) -> bool:
    """弹一条系统通知。返回是否成功——调用方不该因此改变主流程。"""
    if not enabled():
        return False
    try:
        STATE.mkdir(parents=True, exist_ok=True)
        if RESULT.exists():
            RESULT.unlink()
        PAYLOAD.write_text(
            json.dumps({"title": title, "body": body}, ensure_ascii=False),
            encoding="utf-8",
        )
        flags = 0
        if sys.platform == "win32":
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        subprocess.run(
            [_powershell(), "-NoProfile", "-NonInteractive",
             "-ExecutionPolicy", "Bypass", "-File", str(PS1),
             "-Payload", str(PAYLOAD)],
            capture_output=True, timeout=timeout, creationflags=flags,
        )
        if RESULT.exists():
            return RESULT.read_text(encoding="utf-8", errors="ignore").strip() == "OK"
        return False
    except Exception:
        return False


if __name__ == "__main__":
    t = sys.argv[1] if len(sys.argv) > 1 else "学伴"
    b = sys.argv[2] if len(sys.argv) > 2 else "通知测试"
    print("sent =", send(t, b))
