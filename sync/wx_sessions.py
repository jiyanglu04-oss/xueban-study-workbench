# -*- coding: utf-8 -*-
"""把 OCR 的文本行还原成「微信左侧会话列表」。

## 布局实测（窗口 818x639）

    会话名      x ≈ 188        时间戳  x ≈ 329（右对齐）
    消息预览    x ≈ 188 ~ 206
    相邻会话的纵向间隔 ≈ 95px
    同一会话内「名字行 → 预览行」间隔 ≈ 27px
    右侧聊天区文字 x ≥ 395  →  用窗口宽度的 0.46 倍做分界

所以解析分三级：**先按 x 切出左侧列表 → 再按 y 聚成视觉行 → 最后按 y 聚成会话块**。

纯函数、不碰 IO，方便用固定 OCR 结果写测试。
"""
from __future__ import annotations

import re
from typing import NamedTuple

# 左侧会话列表宽度占窗口比例（818px 窗口实测：列表文本最右到 x=333，聊天区从 x≈395 起）
SESSION_AREA_RATIO = 0.46
# 同一视觉行内允许的 y 偏移（名字 y=145 与时间 y=149 属同一行）
ROW_GAP = 15
# 相邻会话块之间的最小 y 间隔（实测会话间距 95，名字→预览 27）
BLOCK_GAP = 45
# 名字与时间戳之间的横向距离超过这个值，就认为右端那个是时间
TIME_X_GAP = 60

# 时间戳（含 OCR 常见误读：冒号被认成 ℃ / ° / 句点）
_TIME_RE = re.compile(
    r"^(?:\d{1,2}\s*[:：°℃·。]\s*\d{1,2}"      # 17:20 / 17℃7
    r"|昨天|前天|星期[一二三四五六日天]|周[一二三四五六日天]"
    r"|\d{1,2}\s*月\s*\d{1,2}\s*日"
    r"|\d{1,2}[/-]\d{1,2})$")

# 微信对被 @ 的会话会加这类前缀
AT_MARKERS = ("有人@我", "@我", "[有人@我]", "@所有人")


class SessionItem(NamedTuple):
    """一条会话（左侧列表里的一行卡片）。"""
    name: str          # 会话名（群名 / 联系人名）
    preview: str       # 最后一条消息的预览（可能含「发送者: 内容」）
    time_text: str     # 时间戳原文（右对齐那个）
    y: float           # 纵向位置，用于排序
    at_me: bool        # 是否带「有人@我」类标记
    badge: str         # 左侧短数字（疑似未读角标），可能为空

    @property
    def is_group(self) -> bool:
        """粗判是不是群（群名通常较长或是「20XX级…」）。"""
        return len(self.name) >= 5 or bool(re.search(r"级|班|群", self.name))

    def summary(self) -> str:
        bits = [self.name]
        if self.at_me:
            bits.append("[有人@我]")
        if self.time_text:
            bits.append(self.time_text)
        return " ".join(bits)

    def full_text(self) -> str:
        """名字 + 预览 + 标记，喂给关键词判断用。"""
        return " ".join(p for p in (self.name, self.preview) if p)


def looks_like_time(text: str) -> bool:
    return bool(_TIME_RE.match((text or "").strip()))


def _group_by_y(lines, gap: float) -> list[list]:
    """按 y 间隔聚组。lines 需带 .y。"""
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


def parse_sessions(lines, size) -> list[SessionItem]:
    """lines: wx_ocr.TextLine 列表；size: (宽, 高)。"""
    width, _height = size
    left = [l for l in lines if getattr(l, "x", 0) < width * SESSION_AREA_RATIO]
    if not left:
        return []

    visual_rows = _group_by_y(left, ROW_GAP)

    # 再把视觉行聚成会话块：用每组的首行 y 代表该行
    row_y = [min(l.y for l in g) for g in visual_rows]
    blocks: list[list[int]] = []
    cur: list[int] = [0]
    for i in range(1, len(row_y)):
        if row_y[i] - row_y[cur[-1]] > BLOCK_GAP:
            blocks.append(cur)
            cur = []
        cur.append(i)
    blocks.append(cur)

    sessions: list[SessionItem] = []
    for blk in blocks:
        head = sorted(visual_rows[blk[0]], key=lambda l: l.x)   # 标题视觉行
        if not head:
            continue
        # 标题行里最靠右的、且与左边拉开距离的 → 时间戳
        name_parts = [head[0].text]
        time_text = ""
        rest = head[1:]
        if rest and (rest[-1].x - head[0].x) > TIME_X_GAP:
            time_text = rest[-1].text
            name_parts += [l.text for l in rest[:-1]]
        else:
            name_parts += [l.text for l in rest]
        name = "".join(name_parts).strip()

        preview_parts = []
        for gi in blk[1:]:
            preview_parts += [l.text for l in sorted(visual_rows[gi], key=lambda l: l.x)]
        preview = " ".join(p for p in preview_parts if p).strip()

        # 左侧的小短数字（疑似未读角标）：x 明显靠左且是纯数字
        badge = ""
        for l in left:
            if abs(l.y - head[0].y) <= ROW_GAP and l.x < head[0].x - 40 and l.text.strip().isdigit():
                badge = l.text.strip()

        blob = name + " " + preview
        at_me = any(m in blob for m in AT_MARKERS)
        if not name:
            continue
        sessions.append(SessionItem(name=name, preview=preview, time_text=time_text,
                                    y=head[0].y, at_me=at_me, badge=badge))

    return sessions


def render(sessions) -> str:
    """给人看的纯文本快照，便于人工核对。"""
    if not sessions:
        return "(左侧会话列表没有识别到任何条目)"
    out = []
    for s in sessions:
        flag = " @" if s.at_me else "  "
        badge = (" [%s]" % s.badge) if s.badge else ""
        out.append("%s%-14s %-6s%s\n              %s" % (
            flag, s.name[:14], s.time_text, badge, s.preview[:46]))
    return "\n".join(out)


if __name__ == "__main__":
    import sys
    from PIL import Image
    from wx_ocr import recognize_file

    for p in sys.argv[1:]:
        img = Image.open(p)
        lines = recognize_file(p)
        print("=== %s ===" % p)
        print(render(parse_sessions(lines, img.size)))
        print()
