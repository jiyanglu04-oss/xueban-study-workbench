# -*- coding: utf-8 -*-
"""把群里真正重要的通知手工录入工作台（来源归类为「微信 / QQ 群」）。

用法：
    python sync/import_notices.py --dry     # 只打印，不写库（先跑这个看效果）
    python sync/import_notices.py           # 正式写入 data/workbench.sqlite3

怎么把自己的群通知填进来
------------------------
1. 导出微信聊天记录（群里右键 → 导出聊天记录），或者直接复制几段；
2. 交给 AI 说「按下面 MESSAGES / TODOS 的格式整理成 Python 常量」，
   或自己照着示例抄；
3. 先 `--dry` 看一眼，确认无误再去掉 `--dry` 正式写入。

模型对齐项目自身的思路：
    messages（消息中心）= 通知的完整流水，可搜索、可「转待办」
    todos（待办）      = 从通知里挑出来的「要你动手」的事

幂等：只动 id 以 wechat- 开头的记录，平台同步来的消息 / 待办一根汗毛都不动。
重复导入会**保留**你已读 / 已完成的勾选状态，不会把看过的消息又变回未读。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

from backend.database import Database  # noqa: E402

DB_PATH = ROOT / "data" / "workbench.sqlite3"

WECHAT_PREFIX = "wechat-"

# 记录首次创建时间。改成你自己的导入日期即可。
NOW = "2026-01-01T00:00:00+08:00"

# ---------------------------------------------------------------------------
# 消息中心：群里值得留档的通知
#   read=True  这条已经过期 / 只是备查，不占未读角标
#   deadline   有截止时间就填（ISO 格式），没有就删掉这一行
#   todo       这条通知对应下面哪条待办。只要还有待办要补救，
#              即使截止时间已过也**保持未读**（否则提醒就消失了）
# ---------------------------------------------------------------------------
MESSAGES: list[dict] = [
    # ⬇️ 示例，换成你自己的；不用就把整个列表清空成 []
    {
        "id": "wechat-m-1",                    # 唯一即可，必须以 wechat-m- 开头
        "title": "【示例】某某竞赛报名通知",
        "content": "在 XXX 平台填报，材料打包发到 xxx@example.com。",
        "url": "",                             # 有链接就填，没有留空
        "time": "2026-01-01T10:00:00+08:00",   # 消息发布时间
        "deadline": "2026-01-31T23:59",        # 截止时间
        "read": False,                         # 想直接算已读就写 True
        "todo": "wechat-t-1",                  # 关联的待办 id，见下面 TODOS
    },
]

# ---------------------------------------------------------------------------
# 待办：从通知里挑出来的、真的要你动手的事
# ---------------------------------------------------------------------------
TODOS: list[dict] = [
    {
        "id": "wechat-t-1",                # 必须以 wechat-t- 开头
        "title": "某某竞赛报名",
        "due": "2026-01-31T23:59",         # 截止时间；没有就删掉这一行
        "priority": 1,                     # 1 高 / 2 中 / 3 低
        "note": "平台填报 + 材料打包发邮件",
    },
]

def _message_record(item: dict) -> dict:
    """补齐 normMsg 需要的字段，别塞额外字段（前端 normalize 会把多余的丢掉）。"""
    return {
        "id": item["id"],
        "platform": "wechat",
        "course": "",
        "courseId": "",
        "title": item["title"],
        "content": item.get("content", ""),
        "url": item.get("url", ""),
        "time": item["time"],
        "read": bool(item.get("read", False)),
        "kind": item.get("kind", "notice"),
        "deadline": item.get("deadline", ""),
    }


def _todo_record(item: dict) -> dict:
    """补齐 normTodo 需要的字段。"""
    return {
        "id": item["id"],
        "title": item["title"],
        "course": "",
        "courseId": "",
        "due": item.get("due", ""),
        "priority": int(item.get("priority", 2)),
        "done": False,
        "doneAt": None,
        "note": item.get("note", ""),
        "source": "wechat",
        "url": item.get("url", ""),
        "createdAt": NOW,
    }


def build(state: dict) -> tuple[list[dict], list[dict]]:
    """把 NOTICES 合并进现有状态，保留用户已读 / 已完成的状态。

    和同步层保持同一套规矩：用户在界面上删过的条目记在 settings.dismissed，
    这里也照单跳过 —— 否则重跑一次就把人家删掉的又拉回来了。
    """
    raw = state.get("settings", {}).get("dismissed")
    dismissed = set(raw) if isinstance(raw, list) else set()

    old_msgs = {m.get("id"): m for m in state.get("messages", [])
                if isinstance(m, dict) and str(m.get("id", "")).startswith(WECHAT_PREFIX)}
    old_todos = {t.get("id"): t for t in state.get("todos", [])
                 if isinstance(t, dict) and str(t.get("id", "")).startswith(WECHAT_PREFIX)}

    messages = []
    for item in MESSAGES:
        rec = _message_record(item)
        if rec["id"] in dismissed:
            continue
        old = old_msgs.get(rec["id"])
        if old:                       # 保留用户读过的状态
            rec["read"] = bool(old.get("read", rec["read"]))
        messages.append(rec)

    todos = []
    for item in TODOS:
        rec = _todo_record(item)
        if rec["id"] in dismissed:
            continue
        old = old_todos.get(rec["id"])
        if old:                       # 保留用户勾选完成的状态和完成时间
            rec["done"] = bool(old.get("done", False))
            rec["doneAt"] = old.get("doneAt")
        todos.append(rec)

    return messages, todos


def run(db_path: str | Path = DB_PATH, dry: bool = False) -> dict:
    db = Database(str(db_path))
    state = db.load_state()
    if state is None:
        raise SystemExit("数据库里还没有状态，请先启动一次工作台再导入。")

    messages, todos = build(state)

    keep_msgs = [m for m in state.get("messages", [])
                 if not str(m.get("id", "")).startswith(WECHAT_PREFIX)]
    keep_todos = [t for t in state.get("todos", [])
                  if not str(t.get("id", "")).startswith(WECHAT_PREFIX)]

    summary = {
        "messages_before": len(state.get("messages", [])),
        "messages_after": len(keep_msgs) + len(messages),
        "messages_imported": len(messages),
        "messages_unread": sum(1 for m in messages if not m["read"]),
        "todos_before": len(state.get("todos", [])),
        "todos_after": len(keep_todos) + len(todos),
        "todos_imported": len(todos),
    }

    if dry:
        return summary

    state["messages"] = keep_msgs + messages
    state["todos"] = keep_todos + todos
    db.save_state(state)
    return summary


def main() -> int:
    ap = argparse.ArgumentParser(description="把班群重要通知录入工作台")
    ap.add_argument("--dry", action="store_true", help="只打印，不写数据库")
    args = ap.parse_args()

    print("数据库：%s" % DB_PATH)
    print("\n将录入的消息（来源=微信 / QQ 群，共 %d 条）：" % len(MESSAGES))
    for item in MESSAGES:
        mark = "已读" if item.get("read") else "未读"
        due = ("  截止 " + item["deadline"]) if item.get("deadline") else ""
        print("  [%s] %-11s %s%s" % (mark, item["time"][:10], item["title"], due))

    print("\n将录入的待办（source=wechat，共 %d 条）：" % len(TODOS))
    for item in TODOS:
        pri = ["", "高", "中", "低"][item.get("priority", 2)]
        due = item.get("due") or "无截止"
        print("  [%s] %-16s %s" % (pri, due, item["title"]))

    s = run(dry=args.dry)
    print("\n消息 %d → %d（新录 %d，其中未读 %d）"
          % (s["messages_before"], s["messages_after"], s["messages_imported"], s["messages_unread"]))
    print("待办 %d → %d（新录 %d）"
          % (s["todos_before"], s["todos_after"], s["todos_imported"]))
    print("\n--dry：没有写库。" if args.dry else "\n已写入数据库，刷新工作台页面即可看到。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
