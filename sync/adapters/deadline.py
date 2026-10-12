# -*- coding: utf-8 -*-
"""从通知 / 作业文本里解析「截止时间」，用于把通知自动变成待办。

这些规则不是凭空写的，是对着**真实抓到的学习通通知**反推的：

    作业:《高等数学2（经4）》C9—测验题
        ... 开始时间：2026-06-21 11:20   结束时间：2026-07-03
        -> 2026-07-03 23:59

    考试通知
        ... 考试时间：06-25 20:00 至 06-25 20:35
        -> 2026-06-25 20:35

    C9-测验题：截止时间7月3日（本周五）晚12点前。
        -> 2026-07-03 23:59

    2026年大学生数学竞赛报名通知，截止日期9月21日
        -> 2026-09-21 23:59

设计原则：
  * 宁可解析不出（返回空），也不要解析出错误的时间——错误的待办比没有待办更烦人。
  * 时间缺省按当天 23:59 处理（「前完成」在中文语境里通常就是当天结束前）。
  * 没写年份时，如果算出来的日期比现在早 60 天以上，认为说的是下一年。
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta

# 「截止」类关键词：出现这些词**后面**的日期才是我们要的
KEYWORDS = (
    "截止时间", "截止日期", "截止", "截至",
    "结束时间", "结束日期", "到期时间",
    "不迟于", "最迟", "须于", "务必于", "应于", "请于",
    "deadline", "Due", "due",
)

# 反过来：日期在关键词**前面**的说法。
#   请务必于 10月20日 前完成      -> 日期在「前完成」之前
#   本周五 之前提交
# 这类如果只照 KEYWORDS 那样往后看 40 个字，永远抓不到日期。
BEFORE_KEYWORDS = (
    "前完成", "前提交", "前交", "前回复", "前上传", "前截止",
    "之前完成", "之前提交", "之前交", "之前上传",
    "以前完成", "以前提交",
)

# 「A 至 B」这种区间，取 B（结束时间更接近真实 DDL）
_RANGE = re.compile(r"(?:至|到)\s*([^\s，,。;；、]{2,24})")

_FULL = re.compile(r"(20\d{2})\s*[-/.年]\s*(\d{1,2})\s*[-/.月]\s*(\d{1,2})\s*[日号]?")
_MD = re.compile(r"(?<!\d)(\d{1,2})\s*月\s*(\d{1,2})\s*[日号]")
_MMDD = re.compile(r"(?<!\d)(\d{1,2})\s*[-/.]\s*(\d{1,2})(?!\d)")
_TIME = re.compile(r"(凌晨|早上|上午|中午|下午|傍晚|晚上|晚|夜)?\s*(\d{1,2})\s*[:：点时]\s*(\d{1,2})?\s*分?")


def _time_of(frag: str, default=(23, 59)) -> tuple[int, int]:
    """从片段里取时间；有区间时取结束时间。"""
    ms = list(_TIME.finditer(frag or ""))
    if not ms:
        return default
    first = ms[0]
    pre = first.group(1) or ""
    hh = int(first.group(2))
    mm = int(first.group(3) or 0)

    # 紧跟在后面的 「-8:35」「一8:35」「至 8:35」 之类，取结束端
    after = frag[first.end(): first.end() + 14]
    rm = re.match(r"\s*[-—~一至到]\s*(\d{1,2})\s*[:：点时]?\s*(\d{1,2})?", after)
    if rm:
        hh2 = int(rm.group(1))
        mm2 = int(rm.group(2) or mm)
        if hh2 < hh:          # 12 小时制跨段
            hh2 += 12
        if 0 <= hh2 <= 23:
            hh, mm = hh2, mm2

    if pre in ("下午", "晚上", "傍晚", "晚", "夜") and hh < 12:
        hh += 12
    elif pre in ("晚", "夜") and hh == 12:
        return 23, 59          # 「晚12点前」= 当天结束前
    elif pre == "凌晨" and hh == 12:
        hh = 0

    if not (0 <= hh <= 23) or not (0 <= mm <= 59):
        return default
    return hh, mm


def _parse(frag: str, now: datetime, strict: bool = False, anchor: datetime | None = None):
    """片段 → datetime；解析不出返回 None。

    strict=True 时只认「2026-07-03」「7月3日」这类明确写法，不认裸的「06-25」。
    整段兜底扫描用 strict，避免把「第8—9章」里的 "8-9" 当成 8 月 9 日。

    anchor：年份消歧的基准。**必须传通知的发布时间**，不要用 now。
    一条 2025-12 发的通知写「考试时间：12-25」，按 now 消歧会落到 2026-12-25
    （未来）→ 平白生成一条一年后的假待办；按发布时间消歧才是 2025-12-25（已过期）。
    这个问题在只抓第 1 页通知时看不出来，一旦开始翻历史页就会冒出一堆。
    """
    frag = (frag or "").strip()
    if not frag:
        return None
    y = m = d = None
    explicit_year = False

    hit = _FULL.search(frag)
    if hit:
        y, m, d, explicit_year = int(hit.group(1)), int(hit.group(2)), int(hit.group(3)), True
    else:
        hit = _MD.search(frag)
        if hit:
            m, d = int(hit.group(1)), int(hit.group(2))
        elif not strict:
            hit = _MMDD.search(frag)
            if hit:
                m, d = int(hit.group(1)), int(hit.group(2))
        y = (anchor or now).year

    if not m or not d or not (1 <= m <= 12) or not (1 <= d <= 31):
        return None

    hh, mm = _time_of(frag)

    # 没写年份时：在 y-1 / y / y+1 里挑「离基准最近」的那个。
    # 这比「过去就加一年」稳得多 —— 一条 6 月的旧通知不会被算成明年的 6 月，
    # 而 12 月底收到的「1月5日截止」也能正确落到下一年。
    if not explicit_year:
        pivot = anchor or now
        best = None
        for yy in (y - 1, y, y + 1):
            try:
                cand = datetime(yy, m, d, hh, mm)
            except ValueError:
                continue
            if best is None or abs(cand - pivot) < abs(best - pivot):
                best = cand
        return best

    try:
        return datetime(y, m, d, hh, mm)
    except ValueError:
        return None


def extract_deadline(text: str, now: datetime | None = None,
                     anchor: datetime | None = None) -> tuple[str, str]:
    """返回 (ISO 时间字符串 'YYYY-MM-DDTHH:MM', 命中的原文片段)。

    解析不出返回 ("", "")。

    anchor 是年份消歧的基准，语义上应该是**这条通知的发布时间**。
    不传就退回 now（手工录入、临时调用这类没有发布时间的场景）。
    """
    if not text:
        return "", ""
    # 内部一律按「本机墙上时间」计算。调用方传带时区的 now 进来是很容易发生的
    # （同步链路里到处是 aware 时间），而 _parse 里要做 abs(cand - now) 比较，
    # naive 和 aware 混在一起会直接 TypeError。
    now = now or datetime.now()
    if now.tzinfo is not None:
        now = now.replace(tzinfo=None)
    if anchor is not None and anchor.tzinfo is not None:
        anchor = anchor.replace(tzinfo=None)
    t = re.sub(r"[\s\u3000]+", " ", str(text))

    cands: list[tuple[int, int, str, bool]] = []

    # 1) 关键词后面的片段优先
    for kw in KEYWORDS:
        for rm in re.finditer(re.escape(kw), t):
            frag = t[rm.end(): rm.end() + 40].split("。")[0]
            cands.append((0, rm.end(), frag, False))

    # 2) 日期在关键词前面的说法：「10月20日前完成」取关键词**之前**的一段
    for kw in BEFORE_KEYWORDS:
        for rm in re.finditer(re.escape(kw), t):
            frag = t[max(0, rm.start() - 30): rm.end() + 4]
            cands.append((0, rm.start(), frag, False))

    # 3) 「A 至 B」取 B
    for rm in _RANGE.finditer(t):
        cands.append((1, rm.start(), rm.group(1), False))

    # 4) 兜底：整段里只要出现过日期类字样，就整体试一次（严格模式）
    if re.search(r"(日期|时间|前完成|前提交|之前完成|将于)", t):
        cands.append((2, 0, t, True))

    cands.sort(key=lambda x: (x[0], x[1]))

    for _prio, _pos, frag, strict in cands:
        dt = _parse(frag, now, strict=strict, anchor=anchor)
        if dt:
            return dt.strftime("%Y-%m-%dT%H:%M"), frag.strip()[:36]
    return "", ""


def is_future(iso: str, now: datetime | None = None, grace_days: int = 1) -> bool:
    """这个截止时间还算「待办」吗？

    历史通知里翻出来的过期 DDL 不再生成待办 —— 否则待办列表会被一堆早就结束的
    作业塞满，反而看不见真正要做的事。留 1 天宽限，避免今天凌晨的 DDL 被漏掉。
    """
    if not iso:
        return False
    now = now or datetime.now()
    try:
        dt = datetime.fromisoformat(iso)
    except ValueError:
        return False
    # extract_deadline 产出的是**不带时区**的本地时间（'YYYY-MM-DDTHH:MM'）。
    # now 如果带时区，直接比较会 TypeError —— 统一按本机墙上时间比。
    if dt.tzinfo is not None and now.tzinfo is None:
        dt = dt.replace(tzinfo=None)
    elif dt.tzinfo is None and now.tzinfo is not None:
        now = now.replace(tzinfo=None)
    return dt >= now - timedelta(days=grace_days)
