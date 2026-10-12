# -*- coding: utf-8 -*-
"""把 OCR 的文本行还原成「微信右侧聊天区」的一条条消息。

## 为什么这条路能走通（对比左侧会话列表）

左侧会话列表要滚动才能看全，而**微信不接受程序发来的滚动 / 点击**（实测彻底无效）。
但只要**微信停在某一个群上**，右侧聊天区的内容就是**当前可见的一屏消息**，
而且是**最新的一屏**（微信在底部时，新消息会自动追加并滚动到底）。

所以：**不用点、不用滚** —— 只要那个群一直开着，我就能一直读到最新消息。

## 微信聊天区的视觉规律（用于解析）

    ┌──────────────────────────────────┐
    │             15:30                │  ← 时间分隔线：水平居中
    ├──────────────────────────────────┤
    │ [头像] 张三                       │  ← 发送者名：靠左、短、灰色小字
    │        ┌──────────────┐          │
    │        │ 明天要交作业   │          │  ← 对方消息：靠左
    │        └──────────────┘          │
    │                     ┌──────────┐ │
    │                     │ 收到      │ │  ← 自己消息：靠右
    │                     └──────────┘ │
    └──────────────────────────────────┘

可用的判别信号只有**位置**（x / y）：
- **靠右**（x 起点明显偏大）→ 自己发的
- **靠左** → 别人发的；块内第一行若是短文本，多半是发送者名
- **水平居中** → 时间分隔线 / 系统提示

纯函数、不碰 IO，方便用固定 OCR 结果写测试。
"""
from __future__ import annotations

import re
from typing import NamedTuple

# --------------------------------------------------------------------------
# 版面参数
# --------------------------------------------------------------------------
# 左侧会话列表的物理宽度。本机 150% 缩放、窗口 1227px 宽时实测约 430px。
# 窗口如果被用户拖大/拖小，这个值需要跟着调（见 detect_list_width）。
DEFAULT_LIST_WIDTH = 430

# 同一「消息块」内允许的行间距。超过它就认为换了一条消息。
# 微信正文行高约 24px（物理），消息之间气泡还有约 10px 间隔。
MSG_GAP = 34

# 一行文字如果起点超过「聊天区左边界 + 此比例×聊天区宽」，判为「自己发的」
SELF_RIGHT_RATIO = 0.42

# 时间分隔线：纯时间 / 日期
_TIME_LINE_RE = re.compile(
    r"^(?:\d{1,2}\s*[:：°℃·。]\s*\d{1,2}"
    r"|昨天|前天|星期[一二三四五六日天]"
    r"|\d{1,2}\s*月\s*\d{1,2}\s*日"
    r"|\d{4}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日"
    r"|\d{1,2}[/-]\d{1,2})$")

# 系统提示（"XX撤回了一条消息""你已添加了XX"等）
_SYS_HINT_RE = re.compile(
    r"撤回了一条消息|你已添加了|以上是打招呼|加入了群聊|邀请.*加入了群聊|"
    r"开启了朋友验证|对方已|红包已|转账")

# --------------------------------------------------------------------------
# 独立聊天窗口（右键会话 →「在独立窗口中打开」）
#
# 这是「只抓一个群」的推荐形态：独立窗口常驻，用户还能正常用主窗口。
# 版面实测（824x948 的独立窗口）：
#     标题栏  y 0~105   （标题就是群名，可用来确认「是不是目标群」）
#     聊天区  y 110~875
#     输入框  y 880~948 （一排表情/文件/截图图标）
# 所以独立窗口模式要**裁掉头尾**，中间整块都是聊天区（没有左侧会话列表）。
# --------------------------------------------------------------------------
INDEPENDENT_TITLE_RATIO = 0.12   # 顶部标题栏占比
INDEPENDENT_FOOTER_RATIO = 0.07  # 底部输入框占比

# 头像区域的横向宽度占比：比这个位置更靠左的短文本基本是头像图案的误读
AVATAR_ZONE_RATIO = 0.10


class ChatMessage(NamedTuple):
    """聊天区里的一条消息。"""
    y: float           # 纵向位置（用于排序去重）
    text: str          # 消息正文（多行已拼成一段）
    sender: str        # 猜测的发送者名；自己发的为空
    side: str          # 'self' 自己 / 'other' 对方 / 'system' 系统/时间
    time_text: str     # 紧跟其上的时间分隔线（如果有）

    def one_line(self) -> str:
        if self.side == "system":
            return "—— %s ——" % self.text
        who = "我" if self.side == "self" else (self.sender or "对方")
        return "%s：%s" % (who, self.text)

    def blob(self) -> str:
        """喂给关键词判断用的纯文本。"""
        return " ".join(p for p in (self.sender, self.text) if p)


def detect_list_width(lines, size) -> float:
    """自动猜左侧会话列表宽度（找不到明显空隙时退回默认值）。

    做法：把右侧区域的文字行按 x 起点排序，找相邻行之间**最大的横向空隙** ——
    会话列表和聊天区之间天然有一段没人写字的空白带。
    只在空隙两侧都"有货"时才采纳，避免误判。
    """
    width, _ = size
    xs = sorted({round(getattr(l, "x", 0)) for l in lines if getattr(l, "x", 0) > 0})
    if len(xs) < 4:
        return DEFAULT_LIST_WIDTH
    best_gap, best_x = 0.0, DEFAULT_LIST_WIDTH
    for a, b in zip(xs, xs[1:]):
        gap = b - a
        # 空隙要落在窗口左半部分，且大小合理（60~400px），才算「列表/聊天区分界」
        if 60 <= gap <= 400 and a < width * 0.5 and gap > best_gap:
            best_gap, best_x = gap, a
    return float(best_x) if best_gap else DEFAULT_LIST_WIDTH


def _group_by_y(lines, gap: float) -> list[list]:
    groups: list[list] = []
    cur: list = []
    for l in sorted(lines, key=lambda x: x.y):
        if cur and l.y - cur[-1].y > gap:
            groups.append(cur)
            cur = []
        cur.append(l)
    if cur:
        groups.append(cur)
    return groups


def _is_time_line(text: str) -> bool:
    return bool(_TIME_LINE_RE.match((text or "").strip()))


def _is_system(text: str) -> bool:
    return bool(_SYS_HINT_RE.search(text or ""))


# 微信昵称：常见的 2~8 字，不含数字和标点（群昵称可能带 emoji，交给侧别判断兜底）
_NICK_RE = re.compile(r"^[\u4e00-\u9fffA-Za-z·．]{2,8}$")


def _looks_like_sender_name(text: str) -> bool:
    """粗判一行文字是不是「发送者昵称」而不是消息正文。"""
    t = (text or "").strip()
    if not t or _is_time_line(t):
        return False
    if re.search(r"\d", t):
        return False
    return bool(_NICK_RE.match(t))


def extract_title(lines, size, *, mode: str = "independent") -> str:
    """独立窗口：从顶部标题栏读群名（用来确认「当前开着的是不是目标群」）。"""
    if mode != "independent":
        return ""
    height = size[1]
    head = [l for l in lines if getattr(l, "y", 0) < height * INDEPENDENT_TITLE_RATIO]
    return "".join(l.text for l in sorted(head, key=lambda l: l.x)).strip()


def parse_chat(lines, size, *, mode: str = "main",
               list_width: float | None = None) -> list[ChatMessage]:
    """lines: wx_ocr.TextLine 列表；size: (宽, 高)。返回按 y 排序的消息列表。

    mode='main'        主窗口（左边有会话列表，按 x 切分左右）
    mode='independent' 独立聊天窗口（整窗都是聊天区，裁掉标题栏与输入框）
    """
    width, height = size
    if mode == "independent":
        chat_left, chat_right = 0.0, float(width)
        top = height * INDEPENDENT_TITLE_RATIO
        bottom = height * (1.0 - INDEPENDENT_FOOTER_RATIO)
    else:
        lw = list_width if list_width is not None else detect_list_width(lines, size)
        chat_left, chat_right = float(lw), float(width)
        top, bottom = 0.0, float(height)

    region = [l for l in lines
              if chat_left <= getattr(l, "x", 0) < chat_right
              and top <= getattr(l, "y", 0) <= bottom]
    # 头像图案常被误读成一两个孤立的字，直接丢掉
    avatar_x = chat_left + (chat_right - chat_left) * AVATAR_ZONE_RATIO
    right = [l for l in region
             if not (l.x < avatar_x and len((l.text or "").strip()) <= 1)]
    if not right:
        return []

    chat_w = max(chat_right - chat_left, 1)

    # 1) 先按 y 聚成「视觉行」（同一条消息里换的行也在内）
    rows = []
    for g in _group_by_y(right, 8):
        g = sorted(g, key=lambda l: l.x)
        rows.append({
            "y": min(l.y for l in g),
            "x": min(l.x for l in g),
            "right": max(l.right for l in g),
            "text": " ".join(l.text for l in g if l.text).strip(),
        })
    rows = [r for r in rows if r["text"]]

    # 2) 把视觉行聚成「消息块」
    blocks: list[list[dict]] = []
    cur: list[dict] = []
    for r in rows:
        if cur and r["y"] - cur[-1]["y"] > MSG_GAP:
            blocks.append(cur)
            cur = []
        cur.append(r)
    if cur:
        blocks.append(cur)

    # 2.5) 微信把「发送者名」单独画在气泡上方。遇到图片 / 文件这类高气泡时，
    #      名字与正文之间会拉开较大空隙、被切成独立的块。
    #      这里把这类「短、无标点、单独成块」的块，认作**下一块的发送者名**。
    tagged: list[tuple[str, list[dict]]] = []
    pending = ""
    for i, blk in enumerate(blocks):
        joined = " ".join(r["text"] for r in blk).strip()
        # 发送者名只可能出现在左边 —— 靠右的是自己发的消息，别被吃成别人的名字
        head_x = blk[0]["x"]
        is_left = (head_x - chat_left) / chat_w <= SELF_RIGHT_RATIO
        if (not pending and is_left and len(blk) == 1
                and _looks_like_sender_name(joined) and i + 1 < len(blocks)):
            pending = joined
            continue
        tagged.append((pending, blk))
        pending = ""
    # 末尾孤零零的一个名字，没有下文，直接丢掉（不产生消息）

    # 3) 逐个块判定：时间线 / 系统提示 / 自己 / 对方
    messages: list[ChatMessage] = []
    last_time = ""
    for hint, blk in tagged:
        head = blk[0]
        joined = " ".join(r["text"] for r in blk).strip()
        if not joined:
            continue

        # 整块就是一行时间 → 记为时间分隔，供后面的消息引用
        if len(blk) == 1 and _is_time_line(joined):
            last_time = joined
            messages.append(ChatMessage(y=head["y"], text=joined, sender="",
                                        side="system", time_text=""))
            continue

        # 整块在水平方向居中 → 系统提示
        center = (head["x"] + head["right"]) / 2.0
        if _is_system(joined) or abs(center - (chat_left + chat_w / 2)) < chat_w * 0.12:
            messages.append(ChatMessage(y=head["y"], text=joined, sender="",
                                        side="system", time_text=last_time))
            last_time = ""
            continue

        # 判断左右：用块内最小 x 相对聊天区的偏移
        offset = (head["x"] - chat_left) / chat_w
        if offset > SELF_RIGHT_RATIO and len(blk) == 1 and len(joined) <= 40:
            side = "self"
        else:
            side = "other"

        sender = hint
        body = joined
        if side == "other" and not sender and len(blk) >= 2:
            # 块内第一行短、且后面还有内容 → 大概率是发送者名
            first = blk[0]["text"]
            if len(first) <= 12 and not _is_time_line(first):
                sender = first
                body = " ".join(r["text"] for r in blk[1:]).strip()

        messages.append(ChatMessage(y=head["y"], text=body, sender=sender,
                                    side=side, time_text=last_time))
        last_time = ""

    return messages


def render_chat(messages) -> str:
    """给人看的聊天记录快照。"""
    if not messages:
        return "(右侧聊天区没有识别到内容)"
    out = []
    for m in messages:
        if m.side == "system":
            out.append("        —— %s ——" % m.text)
            continue
        who = "我" if m.side == "self" else (m.sender or "对方")
        pad = " " * max(0, 8 - len(who))
        out.append("%s%s：%s" % (who, pad, m.text))
    return "\n".join(out)


if __name__ == "__main__":
    import sys
    from PIL import Image
    from wx_ocr import recognize_file

    mode = "independent" if "--indep" in sys.argv else "main"
    paths = [a for a in sys.argv[1:] if not a.startswith("--")]
    for p in paths:
        img = Image.open(p)
        lines = recognize_file(p)
        print("=== %s ===" % p)
        if mode == "independent":
            print("窗口 %dx%d | 独立窗口 | 标题=%r" % (
                img.size[0], img.size[1],
                extract_title(lines, img.size, mode=mode)))
        else:
            print("窗口 %dx%d | 主窗口 | 会话列表宽 ≈ %.0f" % (
                img.size[0], img.size[1], detect_list_width(lines, img.size)))
        print(render_chat(parse_chat(lines, img.size, mode=mode)))
        print()
