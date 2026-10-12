# -*- coding: utf-8 -*-
"""OCR：把截图转成「带坐标的文本行」。

用 Windows 自带的识别引擎（`Windows.Media.Ocr`）：
- 离线、免费、无需额外模型文件
- 本机可用语言实测为 `zh-Hans-CN`（简体中文）
- 通过 PyWinRT 从 Python 调用

**必须保留坐标**：后续要靠 x 坐标把「左侧会话列表」和「右侧聊天区」分开，
靠 y 坐标把文本行还原成一条条会话。只给纯文本是没用的。
"""
from __future__ import annotations

import asyncio
from typing import NamedTuple


class TextLine(NamedTuple):
    """一行 OCR 结果，带外接矩形。"""
    x: float
    y: float
    right: float
    bottom: float
    text: str

    @property
    def w(self) -> float:
        return self.right - self.x

    @property
    def h(self) -> float:
        return self.bottom - self.y

    @property
    def cy(self) -> float:
        return (self.y + self.bottom) / 2.0


class OcrUnavailable(RuntimeError):
    """系统没有可用的 OCR 引擎（缺中文语言包）。"""


async def _recognize_file(path: str) -> list[TextLine]:
    from winrt.windows.media.ocr import OcrEngine
    from winrt.windows.graphics.imaging import BitmapDecoder
    from winrt.windows.storage import StorageFile, FileAccessMode

    engine = OcrEngine.try_create_from_user_profile_languages()
    if engine is None:
        raise OcrUnavailable(
            "系统没有可用的 OCR 引擎。请在「设置 → 时间和语言 → 语言」里"
            "安装简体中文的语言包（含「光学字符识别」可选功能）。")

    f = await StorageFile.get_file_from_path_async(path)
    stream = await f.open_async(FileAccessMode.READ)
    decoder = await BitmapDecoder.create_async(stream)
    bitmap = await decoder.get_software_bitmap_async()
    result = await engine.recognize_async(bitmap)

    lines: list[TextLine] = []
    for line in result.lines:
        words = [(wd.text, wd.bounding_rect) for wd in line.words]
        if not words:
            continue
        x = min(r.x for _, r in words)
        y = min(r.y for _, r in words)
        right = max(r.x + r.width for _, r in words)
        bottom = max(r.y + r.height for _, r in words)
        lines.append(TextLine(x, y, right, bottom,
                              "".join(t for t, _ in words)))
    lines.sort(key=lambda l: (l.y, l.x))
    return lines


def recognize_file(path: str) -> list[TextLine]:
    """识别图片文件。path 必须是**绝对路径** —— WinRT 的 StorageFile 不认相对路径。"""
    import os
    if not os.path.isabs(path):
        path = os.path.abspath(path)
    return asyncio.run(_recognize_file(path))


def recognize_image(img, tmp_path: str) -> list[TextLine]:
    """识别 PIL.Image：先落盘再识别（Windows OCR 只吃文件/流）。"""
    img.save(tmp_path)
    return recognize_file(tmp_path)


if __name__ == "__main__":
    import sys
    for p in sys.argv[1:]:
        lines = recognize_file(p)
        print("=== %s ： %d 行 ===" % (p, len(lines)))
        for l in lines:
            print("y=%4d x=%4d | %s" % (l.y, l.x, l.text))
