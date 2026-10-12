# -*- coding: utf-8 -*-
"""每日整合通知 —— 把「今天要做什么」压成一条系统弹窗推到你眼前。

为什么需要它：
    自动同步是在后台跑的，工作台页面不一定开着。待办要到期这件事，
    你不主动去看就等于不存在。所以每天固定时间弹一条整合通知，
    而不是让一堆零散提醒天天刷屏。

三种模式：
    morning  早报（默认）：逾期未处理 + 今天到期 + 今天的课
    evening  晚报：今天还没做完的 + 明天/后天到期的
    test     立刻发一条（内容同早报，不写防重复记录）

为什么不调 /api/state 而是直接读 SQLite：
    计划任务可能在开机后立刻执行，那时工作台服务还没起来。
    库文件是唯一数据源，直接读它最稳。

防打扰设计：
    1. 同一时段一天只发一次（记录在 state/digest-history.json），
       避免计划任务「错过补跑」把同一件事弹两遍。
    2. 真的没内容时也发，但只有一行 —— 你至少知道它还活着；
       「某天突然不响了」本身就成了一个能被察觉的信号。
    3. 全流程吞异常：通知发不出去绝不能让定时任务报错退出。
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
for _p in (str(ROOT), str(HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import notifier  # noqa: E402
from backend.database import Database  # noqa: E402

DB_PATH = ROOT / "data" / "workbench.sqlite3"
STATE = HERE / "state"
HISTORY = STATE / "digest-history.json"

MODE_MORNING = "morning"
MODE_EVENING = "evening"

# Toast 的正文大概只能显示 3 行左右，再多会被系统裁掉 —— 所以宁可少写、
# 也不能把关键信息放在会被吞掉的那一行。
MAX_LINES = 3           # 正文最多几行
MAX_TODO_LINES = 3      # 待办最多列几条，多了折叠成「等 N 件」
MAX_COURSES = 3         # 课程同理
TITLE_CUT = 16          # 单条待办标题在通知里最多显示几个字


# ---------------------------------------------------------------- 时间解析

def parse_dt(raw) -> datetime | None:
    """解析待办里的 due。格式是 `2026-10-10T08:50`（本地时间、无时区）。

    容错处理两件现实中会出现的脏数据：
      - 只写了日期没有时间的；
      - 教务/通知里常见的 `24:00`（datetime 不认）。
    """
    if not raw:
        return None
    s = str(raw).strip().replace("Z", "")
    if not s:
        return None
    s = s.replace("T24:00", "T23:59")
    if "T" not in s:
        s = s + "T23:59"
    s = s[:16]
    for fmt in ("%Y-%m-%dT%H:%M", "%Y/%m/%dT%H:%M"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    try:
        return datetime.strptime(s[:10], "%Y-%m-%d").replace(hour=23, minute=59)
    except ValueError:
        return None


def week_of(day: datetime, term_start: str) -> int:
    """教学周次：termStart 那周算第 1 周。"""
    try:
        st = datetime.strptime(str(term_start)[:10], "%Y-%m-%d")
    except Exception:
        return 1
    return (day.date() - st.date()).days // 7 + 1


# ---------------------------------------------------------------- 课表解析
# 规则与前端 src/js/01-core.js 的 parseWeeks / inWeek 完全一致，
# 免得「页面上显示有课、通知却说没课」这种自相矛盾。

def parse_weeks(spec) -> set | None:
    """'1-18' / '2-13双' / '1-16单' / '4' / '1-3,5-18' → 周次集合。None = 全周。"""
    if spec is None or spec == "" or spec == "all":
        return None
    s = str(spec)
    parity = 0
    if "单" in s:
        parity = 1
    if "双" in s:
        parity = 2
    for ch in ("单", "双", "周", " ", "\t"):
        s = s.replace(ch, "")
    if not s:
        return None
    out: set[int] = set()
    for part in s.replace("，", ",").replace("、", ",").replace("；", ",").replace(";", ",").split(","):
        part = part.strip()
        if not part:
            continue
        m = None
        for sep in ("-", "~", "至", "到"):
            if sep in part:
                a, _, b = part.partition(sep)
                if a.strip().isdigit() and b.strip().isdigit():
                    m = (int(a), int(b))
                break
        if m:
            lo, hi = min(m), max(m)
            out.update(range(lo, hi + 1))
        elif part.isdigit():
            out.add(int(part))
    if parity == 1:
        out = {w for w in out if w % 2 == 1}
    elif parity == 2:
        out = {w for w in out if w % 2 == 0}
    return out


def in_week(spec, week: int) -> bool:
    s = parse_weeks(spec)
    return s is None or week in s


def sessions_on(state: dict, day: datetime) -> list[dict]:
    """某一天有什么课。返回 [{name, start, end, room, section}] 按开始时间排。"""
    st = state.get("settings") or {}
    week = week_of(day, st.get("termStart") or "2026-09-07")
    wd = day.isoweekday()          # 1=周一 … 7=周日
    if week < 1 or week > int(st.get("totalWeeks") or 20):
        return []
    sections = st.get("sections") or []
    out = []
    for c in state.get("courses") or []:
        for s in c.get("sessions") or []:
            try:
                same_day = int(s.get("day")) == wd
            except (TypeError, ValueError):
                continue
            if not same_day or not in_week(s.get("weeks"), week):
                continue
            idx = int(s.get("start") or 0)
            span = sections[idx - 1] if 1 <= idx <= len(sections) else None
            out.append({
                "name": c.get("name") or "（未命名课程）",
                "start": span[0] if span else "",
                "end": span[1] if span else "",
                "room": s.get("room") or "",
                "section": idx,
                "len": int(s.get("len") or 1),
            })
    out.sort(key=lambda x: (x["start"] or "99:99"))
    return out


# ---------------------------------------------------------------- 内容组织

def _short(text: str, width: int = TITLE_CUT) -> str:
    t = " ".join(str(text or "").split())
    return t if len(t) <= width else t[:width - 1] + "…"


def _hhmm(dt: datetime) -> str:
    return dt.strftime("%H:%M")


def _fold(names: list[str], limit: int) -> str:
    if len(names) <= limit:
        return "、".join(names)
    return "、".join(names[:limit]) + " 等 %d 件" % len(names)


def classify(todos: list[dict], now: datetime) -> dict:
    """把未完成待办按「离截止多远」分桶。无截止时间的单独一桶。"""
    buckets = {"overdue": [], "today": [], "tomorrow": [], "dayafter": [], "later": [], "nodue": []}
    for t in todos:
        d = parse_dt(t.get("due"))
        if d is None:
            buckets["nodue"].append((None, t))
            continue
        delta = (d.date() - now.date()).days
        if d < now:
            buckets["overdue"].append((d, t))
        elif delta == 0:
            buckets["today"].append((d, t))
        elif delta == 1:
            buckets["tomorrow"].append((d, t))
        elif delta == 2:
            buckets["dayafter"].append((d, t))
        else:
            buckets["later"].append((d, t))
    for k in buckets:
        buckets[k].sort(key=lambda x: (x[0] or datetime.max))
    return buckets


def _todo_line(items: list[tuple], with_time: bool) -> str:
    parts = []
    for d, t in items:
        tag = _hhmm(d) + " " if (with_time and d) else ""
        parts.append(tag + _short(t.get("title")))
    return _fold(parts, MAX_TODO_LINES)


def _course_line(classes: list[dict]) -> str:
    """课程行要尽量短 —— 它总是和待办行拼在一起，长了会被系统裁掉。

    所以多节课时只给「最早几点开始」，而不是每节都带时间；课名也截到 8 字，
    反正完整信息在课表视图里，通知只负责让你知道「今天有课、几点开始」。
    """
    if not classes:
        return "今天没课"
    n = len(classes)
    if n == 1:
        c = classes[0]
        s = "今天 1 节课：%s" % _short(c["name"], 12)
        if c.get("start"):
            s += " " + c["start"]
        if c.get("room"):
            s += " " + c["room"]
        return s
    first = next((c["start"] for c in classes if c.get("start")), "")
    when = "，%s 开始" % first if first else ""
    names = _fold([_short(c["name"], 8) for c in classes], MAX_COURSES)
    return "今天 %d 节课%s：%s" % (n, when, names)


def build(mode: str, state: dict, now: datetime) -> tuple[str, str]:
    """返回 (标题, 正文)。正文控制在 4 行内 —— Toast 再长会被截断。"""
    todos = [t for t in (state.get("todos") or []) if not t.get("done")]
    b = classify(todos, now)
    lines: list[str] = []

    if mode == MODE_EVENING:
        title = "学伴 · 明天要做什么"
        if b["overdue"]:
            lines.append("逾期未处理 %d 件：%s" % (len(b["overdue"]), _todo_line(b["overdue"], False)))
        if b["today"]:
            lines.append("今天还没勾完：%s" % _todo_line(b["today"], True))
        # 明天和后天合成一行 —— 两行都是「接下来要做的」，没必要各占一行
        ahead = b["tomorrow"] + b["dayafter"]
        if ahead:
            lines.append("明天/后天到点：%s" % _todo_line(ahead, True))
        if not lines:
            nxt = sessions_on(state, now + timedelta(days=1))
            if nxt:
                lines.append("今天的事都清完了。明天有课，早点休息。")
                lines.append(_course_line(nxt))
            else:
                lines.append("今天的事都清完了，明天也没有安排。")
        return title, "\n".join(lines[:MAX_LINES])

    # ---- 早报
    title = "学伴 · 今天要做什么"
    if b["overdue"]:
        lines.append("逾期未处理 %d 件：%s" % (len(b["overdue"]), _todo_line(b["overdue"], False)))
    if b["today"]:
        lines.append("今天到点：%s" % _todo_line(b["today"], True))
    lines.append(_course_line(sessions_on(state, now)))
    if b["nodue"] and not (b["overdue"] or b["today"]):
        # 没有明确时间的待办，顺手提一句，别让它永远沉底
        lines.append("另有 %d 件没写截止时间，有空看一眼。" % len(b["nodue"]))
    if len(lines) == 1 and lines[0] == "今天没课":
        lines = ["今天没有待办，也没有课，放心。"]
    return title, "\n".join(lines[:MAX_LINES])


# ---------------------------------------------------------------- 防重复

def _slot(now: datetime, mode: str) -> str:
    return "%s:%s" % (now.strftime("%Y-%m-%d"), mode)


def read_history() -> dict:
    try:
        return json.loads(HISTORY.read_text(encoding="utf-8"))
    except Exception:
        return {}


def already_sent(now: datetime, mode: str) -> bool:
    return _slot(now, mode) in (read_history().get("slots") or {})


def mark_sent(now: datetime, mode: str, body: str) -> None:
    try:
        hist = read_history()
        slots = hist.get("slots") or {}
        slots[_slot(now, mode)] = now.strftime("%Y-%m-%dT%H:%M")
        # 只留最近 60 条，文件别无限涨
        keep = sorted(slots.items())[-60:]
        STATE.mkdir(parents=True, exist_ok=True)
        HISTORY.write_text(
            json.dumps({"slots": dict(keep), "lastBody": body},
                       ensure_ascii=False, indent=1),
            encoding="utf-8",
        )
    except Exception:
        pass


# ---------------------------------------------------------------- 入口

def run(mode: str = MODE_MORNING, now: datetime | None = None,
        dry: bool = False, force: bool = False) -> dict:
    now = now or datetime.now()
    out = {"mode": mode, "at": now.strftime("%Y-%m-%d %H:%M"), "sent": False,
           "title": "", "body": "", "reason": ""}
    try:
        if not dry and not force and already_sent(now, mode):
            out["reason"] = "该时段今天已经发过，跳过"
            return out

        state = Database(DB_PATH).load_state()
        title, body = build(mode, state, now)
        out["title"], out["body"] = title, body

        if dry:
            out["reason"] = "预演，未发送"
            return out

        ok = notifier.send(title, body)
        out["sent"] = bool(ok)
        out["reason"] = "已推送" if ok else "通知发送失败（可能被系统静默拦截）"
        # --force 是「我现在就想看一眼」，不该占掉今天这个时段的名额，
        # 否则手动试完，到点的那次定时提醒就被自己顶掉了。
        if ok and not force:
            mark_sent(now, mode, body)
    except Exception as e:   # 定时任务里宁可静默失败，也不能报错退出
        out["reason"] = "生成通知时异常：%r" % e
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="每天固定时间弹一条整合通知")
    ap.add_argument("--mode", choices=[MODE_MORNING, MODE_EVENING, "test", "auto"],
                    default="auto",
                    help="auto = 中午前当早报、之后当晚报（计划任务就用这个）")
    ap.add_argument("--auto", action="store_true",
                    help="按当前时间自动选早报/晚报（计划任务用；等同 --mode auto）")
    ap.add_argument("--at", default="", help="模拟某个时间点，如 2026-10-10T21:00（排查用）")
    ap.add_argument("--dry", action="store_true", help="只打印，不弹窗")
    ap.add_argument("--force", action="store_true", help="忽略「今天已发过」的限制")
    a = ap.parse_args()
    if a.auto:
        a.mode = "auto"

    now = None
    if a.at:
        now = parse_dt(a.at)
        if now is None:
            print("时间格式不对：", a.at)
            return 2
    clock = now or datetime.now()
    if a.mode == "auto":
        mode = MODE_MORNING if clock.hour < 12 else MODE_EVENING
    else:
        mode = MODE_MORNING if a.mode == "test" else a.mode
    r = run(mode, now, dry=a.dry or a.mode == "test", force=a.force)
    print("── 标题 ──")
    print(r["title"])
    print("── 正文 ──")
    print(r["body"])
    print("── 结果 ──")
    print("sent=%s  %s" % (r["sent"], r["reason"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
