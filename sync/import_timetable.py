# -*- coding: utf-8 -*-
"""把自己的课表批量导入工作台（不走教务系统抓取）。

用法：
    python sync/import_timetable.py           # 写入 data/workbench.sqlite3
    python sync/import_timetable.py --dry     # 只打印，不写库

怎么填
------
改下面 TIMETABLE 常量即可。同一门课一周上多次，就在 sessions 里写多段。
也可以完全不用这个脚本 —— 直接在界面的「我的课表」里点空格子加课，
改过的课表不会被平台同步覆盖。

字段说明（对应前端数据模型）：
    day    周几，1=周一 … 6=周六，7=周日
           （课表默认只显示周一到周五；某周有周末课时会自动展开周六周日两列）
    start  起始节次，1..13
    len    连上几节
    weeks  周次写法，支持 "1-18" / "1-3,5-18"（跳过第 4 周）
           / "2-13双"（仅双周）/ "2-13单"（仅单周）
    room   教室
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

# id 固定以 c-tt- 开头，便于重复导入时整体替换（只换课表课，不动平台同步来的课程）
TIMETABLE: list[dict] = [
    # ⬇️ 这是一条示例，把它换成你自己的课；不想要就在界面里删掉。
    {
        "id": "c-tt-01",
        "name": "高等数学",
        "teacher": "某某",
        "code": "",                  # 课程号，可留空
        "section": "",               # 班号，可留空
        "color": "#2E7BF6",
        "platform": "课表",           # 固定写「课表」
        "note": "",                  # 备注，可留空
        "sessions": [
            {"day": 1, "start": 1, "len": 2, "weeks": "1-18", "room": "教101"},
            {"day": 3, "start": 3, "len": 2, "weeks": "1-18", "room": "教203"},
        ],
    },
]

WD = ["一", "二", "三", "四", "五", "六", "日"]


def parse_weeks(spec: str) -> set[int]:
    """和前端 parseWeeks 保持一致，用来做导入后的自检。"""
    s = str(spec)
    parity = 0
    if "单" in s:
        parity = 1
    if "双" in s:
        parity = 2
    for ch in "单双周 ":
        s = s.replace(ch, "")
    out: set[int] = set()
    for part in s.replace("，", ",").replace("、", ",").split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            out.update(range(int(a), int(b) + 1))
        elif part.isdigit():
            out.add(int(part))
    if parity == 1:
        out = {w for w in out if w % 2 == 1}
    elif parity == 2:
        out = {w for w in out if w % 2 == 0}
    return out


def import_into(db_path: str | Path) -> tuple[int, int]:
    """把 TIMETABLE 写进指定数据库。返回（课表课程数, 被替换掉的旧课表课数）。

    幂等：只动 id 以 c-tt- 开头的课程，平台同步来的课程原样保留。
    """
    db = Database(str(db_path))
    state = db.load_state()
    before = state.get("courses", [])
    kept = [c for c in before if not str(c.get("id", "")).startswith("c-tt-")]
    removed = len(before) - len(kept)
    state["courses"] = kept + [dict(c) for c in TIMETABLE]
    db.save_state(state)
    return len(TIMETABLE), removed


def main() -> int:
    ap = argparse.ArgumentParser(description="导入机阳的课表")
    ap.add_argument("--dry", action="store_true", help="只打印，不写数据库")
    args = ap.parse_args()

    db = Database(str(DB_PATH))
    state = db.load_state()

    before = state.get("courses", [])
    kept = [c for c in before if not str(c.get("id", "")).startswith("c-tt-")]
    removed = len(before) - len(kept)

    print("数据库：%s" % DB_PATH)
    print("原有课程 %d 门，其中课表课 %d 门被替换，平台同步课 %d 门保持不动"
          % (len(before), removed, len(kept)))
    print("导入课表课程 %d 门 / %d 个上课时段："
          % (len(TIMETABLE), sum(len(c["sessions"]) for c in TIMETABLE)))
    for c in TIMETABLE:
        for s in c["sessions"]:
            print("  周%s 第%2d-%2d节  %-14s %-4s  %-8s  %s"
                  % (WD[s["day"] - 1], s["start"], s["start"] + s["len"] - 1,
                     c["name"], c["teacher"], s["weeks"], s["room"]))

    if args.dry:
        print("\n--dry：没有写库。")
        return 0

    import_into(DB_PATH)
    print("\n已写入数据库。")

    # 自检：重新读回来，按周统计课时
    again = db.load_state()
    tt = [c for c in again["courses"] if str(c.get("id", "")).startswith("c-tt-")]
    print("回读校验：课表课程 %d 门，时段 %d 个"
          % (len(tt), sum(len(c.get("sessions", [])) for c in tt)))
    for w in (4, 5, 6):
        n = 0
        for c in tt:
            for s in c.get("sessions", []):
                if w in parse_weeks(s["weeks"]):
                    n += s["len"]
        print("  第 %d 周共 %d 节课" % (w, n))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
