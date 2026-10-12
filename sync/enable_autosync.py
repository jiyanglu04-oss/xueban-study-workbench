# -*- coding: utf-8 -*-
"""把工作台数据库里的「每日自动同步」开关打开。

由「注册自动同步.bat」在注册完计划任务后调用一次，让界面上的开关和
系统里的定时任务保持一致（否则会出现「明明每天在自动更新，设置页却显示已关闭」）。

为什么不只改前端默认值：浏览器每次保存状态都会把整个 S.settings 写回数据库，
库里那条如果还是 autoSync=false，前端默认值改成 true 也没用 —— 一刷新就被覆盖回来。

安全起见，只在数据库**已经初始化**（用户至少打开过一次工作台）时才写。
否则凭空插一条 settings 会让服务端以为状态已存在，可能覆盖浏览器的本地数据。
"""
from __future__ import annotations

import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "workbench.sqlite3"


def main() -> int:
    if not DB.exists():
        print("数据库还不存在，跳过。")
        print("（不影响定时同步，只是工作台里的开关需要你打开一次工作台后手动开启）")
        return 0

    con = sqlite3.connect(DB, timeout=10)
    con.row_factory = sqlite3.Row
    try:
        row = con.execute(
            "SELECT data_json FROM singleton_state WHERE name='settings'").fetchone()
        if row is None:
            print("数据库还没初始化，跳过。请打开一次工作台，再在「设置」页打开自动同步。")
            return 0
        try:
            settings = json.loads(row["data_json"])
            if not isinstance(settings, dict):
                settings = {}
        except (TypeError, ValueError):
            settings = {}

        settings["autoSync"] = True
        settings.setdefault("syncTimes", "08:00,20:00")
        con.execute(
            "INSERT INTO singleton_state(name,data_json,updated_at) VALUES('settings',?,?) "
            "ON CONFLICT(name) DO UPDATE SET data_json=excluded.data_json, "
            "updated_at=excluded.updated_at",
            (json.dumps(settings, ensure_ascii=False, separators=(",", ":")),
             datetime.now(timezone.utc).isoformat()),
        )
        con.commit()
        print("已打开工作台里的自动同步开关（autoSync=true，时间 %s）"
              % settings.get("syncTimes"))
        return 0
    finally:
        con.close()


if __name__ == "__main__":
    sys.exit(main())
