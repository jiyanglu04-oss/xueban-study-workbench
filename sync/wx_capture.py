# -*- coding: utf-8 -*-
"""截图微信窗口（不注入、不解密、不碰微信进程内存）。

## 为什么是「截图」而不是「读数据库」

微信 4.1 起，数据库密钥不再常驻内存，纯内存扫描彻底失效，读库只剩
DLL 注入 + Hook 一条路。而本机有腾讯电脑管家 + Windows Defender 双杀软，
注入必被拦；且注入本身会导致微信崩溃，微信一升级特征码还可能失效。

截图走的是完全不同的路子：**只读屏幕像素**。
微信侧没有任何可检测的技术痕迹，也不需要账号密码。

## 实测出来的两条硬事实（别改错）

1. `PrintWindow(..., PW_RENDERFULLCONTENT=2)` 能拿到 Qt 自绘窗口的内容，
   而且**窗口被其他窗口完全遮挡时照样能拿到**（走的是窗口自己的绘制缓冲区，
   不是屏幕像素）。这一点比 ImageGrab 截屏可靠得多。
2. **窗口必须是「显示」状态**：最小化 / 收进托盘时微信停止渲染，
   截出来是纯色。实测内容方差：显示 58.2 / 最小化 0.0 / 托盘 0.0。
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import time

# 微信 4.x 主窗口类名。4.x 改用 Qt（3.x 是 WeChatMainWndForPC）。
WECHAT_WINDOW_CLASS = "Qt51514QWindowIcon"
WECHAT_PROCESS_NAMES = ("weixin.exe", "wechat.exe")

_u32 = ctypes.windll.user32
_g32 = ctypes.windll.gdi32
_k32 = ctypes.windll.kernel32

SW_SHOW = 5
SW_MINIMIZE = 6
SW_HIDE = 0


def enable_dpi_awareness() -> str:
    """让本进程 DPI 感知 —— 这一步必须在取任何坐标 / 截图之前做。

    为什么关键：本机屏幕是 **150% 缩放**。非 DPI 感知的进程调 GetWindowRect
    拿到的是「虚拟坐标」（818x639），而窗口实际是 1227x959 物理像素。
    后果有两个：① 截图被系统拉伸、糊；② 算出来的点击坐标整体偏小 1.5 倍，
    点哪儿都不对。实测过：这就是「点击无效」的真凶，不是前台锁定。

    返回实际生效的级别串，便于排障。
    """
    # 1) Per-Monitor v2（Win10 1703+）：DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = -4
    try:
        _u32.SetProcessDpiAwarenessContext.argtypes = [ctypes.c_void_p]
        _u32.SetProcessDpiAwarenessContext.restype = ctypes.c_bool
        if _u32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)):
            return "per-monitor-v2"
    except Exception:
        pass
    # 2) Per-Monitor（Win8.1+）：PROCESS_PER_MONITOR_DPI_AWARE = 2
    try:
        import ctypes as _c
        if _c.windll.shcore.SetProcessDpiAwareness(2) == 0:
            return "per-monitor"
    except Exception:
        pass
    # 3) System DPI aware（Vista+）
    try:
        if _u32.SetProcessDPIAware():
            return "system"
    except Exception:
        pass
    return "failed"


# 进程级一次性设置。已设置过时再调会返回失败，属正常，忽略即可。
DPI_AWARENESS = enable_dpi_awareness()

# --------------------------------------------------------------------------
# 64 位句柄声明（不声明会直接崩：默认 restype=c_int 会把句柄值截断成负数）
# --------------------------------------------------------------------------
_g32.CreateCompatibleDC.argtypes = [ctypes.c_void_p]
_g32.CreateCompatibleDC.restype = ctypes.c_void_p
_g32.CreateCompatibleBitmap.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int]
_g32.CreateCompatibleBitmap.restype = ctypes.c_void_p
_g32.SelectObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
_g32.SelectObject.restype = ctypes.c_void_p
_g32.GetDIBits.argtypes = [ctypes.c_void_p, ctypes.c_void_p, wt.UINT, wt.UINT,
                           ctypes.c_void_p, ctypes.c_void_p, wt.UINT]
_g32.GetDIBits.restype = ctypes.c_int
_g32.DeleteObject.argtypes = [ctypes.c_void_p]
_g32.DeleteDC.argtypes = [ctypes.c_void_p]
_u32.GetWindowDC.argtypes = [wt.HWND]
_u32.GetWindowDC.restype = ctypes.c_void_p
_u32.ReleaseDC.argtypes = [wt.HWND, ctypes.c_void_p]
_u32.PrintWindow.argtypes = [wt.HWND, ctypes.c_void_p, wt.UINT]
_u32.PrintWindow.restype = ctypes.c_bool


class WindowNotFound(RuntimeError):
    """没找到微信主窗口（微信没开 / 被卸载 / 类名变了）。"""


class WindowNotRenderable(RuntimeError):
    """窗口存在但没在渲染（最小化或收进托盘），截出来会是黑屏。"""


# --------------------------------------------------------------------------
# 窗口查找
# --------------------------------------------------------------------------

def _process_name_of(hwnd: int) -> str:
    """拿到窗口所属进程的可执行文件名（小写）。失败返回空串。"""
    pid = wt.DWORD()
    _u32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    if not pid.value:
        return ""
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    h = _k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
    if not h:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(1024)
        size = wt.DWORD(len(buf))
        if _k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
            return buf.value.rsplit("\\", 1)[-1].lower()
        return ""
    finally:
        _k32.CloseHandle(h)


def _window_text(hwnd: int) -> str:
    n = _u32.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(n + 2)
    _u32.GetWindowTextW(hwnd, buf, n + 2)
    return buf.value


def _class_name(hwnd: int) -> str:
    buf = ctypes.create_unicode_buffer(256)
    _u32.GetClassNameW(hwnd, buf, 256)
    return buf.value


def list_candidate_windows() -> list[dict]:
    """列出所有「像微信主窗口」的窗口，供排障用。"""
    found: list[dict] = []

    def cb(hwnd, _lparam):
        cls = _class_name(hwnd)
        if cls != WECHAT_WINDOW_CLASS:
            return True
        proc = _process_name_of(hwnd)
        found.append({
            "hwnd": hwnd,
            "class": cls,
            "title": _window_text(hwnd),
            "process": proc,
            "visible": bool(_u32.IsWindowVisible(hwnd)),
            "minimized": bool(_u32.IsIconic(hwnd)),
        })
        return True

    _u32.EnumWindows(ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)(cb), 0)
    return found


def find_wechat_window() -> int:
    """找微信主窗口句柄。

    优先认进程名（weixin.exe），拿不到进程名时退化为「类名 + 标题含微信」。
    多个候选时取标题精确等于「微信」的那个（微信会另开一个隐藏的 'Weixin' 窗口）。
    """
    cands = [w for w in list_candidate_windows()
             if w["process"] in WECHAT_PROCESS_NAMES or not w["process"]]
    if not cands:
        raise WindowNotFound(
            "没找到微信窗口（类名 %s）。微信可能没在运行。" % WECHAT_WINDOW_CLASS)

    for w in cands:
        if w["title"] == "微信":
            return w["hwnd"]
    return cands[0]["hwnd"]


def is_renderable(hwnd: int) -> bool:
    """窗口是否处于「能截到内容」的状态。

    只有「显示」才算。收进托盘（不可见）和最小化都会截到纯色。
    """
    if not _u32.IsWindowVisible(hwnd):
        return False
    if _u32.IsIconic(hwnd):
        return False
    return True


def describe_state(hwnd: int) -> str:
    if not _u32.IsWindowVisible(hwnd):
        return "收进托盘（不可见）"
    if _u32.IsIconic(hwnd):
        return "最小化"
    return "正常显示"


# --------------------------------------------------------------------------
# 截图
# --------------------------------------------------------------------------

class _BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wt.DWORD), ("biWidth", wt.LONG), ("biHeight", wt.LONG),
        ("biPlanes", wt.WORD), ("biBitCount", wt.WORD),
        ("biCompression", wt.DWORD), ("biSizeImage", wt.DWORD),
        ("biXPelsPerMeter", wt.LONG), ("biYPelsPerMeter", wt.LONG),
        ("biClrUsed", wt.DWORD), ("biClrImportant", wt.DWORD),
    ]


class _BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", _BITMAPINFOHEADER),
                ("bmiColors", wt.DWORD * 3)]


def capture_window(hwnd: int):
    """把窗口画面抓成 PIL.Image。

    用 PW_RENDERFULLCONTENT(2)：对 Qt / Chromium 这类自绘窗口必须带这个标志，
    否则只能拿到空白。窗口被遮挡也能截。
    """
    from PIL import Image

    rect = wt.RECT()
    if not _u32.GetWindowRect(hwnd, ctypes.byref(rect)):
        raise RuntimeError("GetWindowRect 失败")
    w = rect.right - rect.left
    h = rect.bottom - rect.top
    if w <= 0 or h <= 0:
        raise RuntimeError("窗口尺寸非法：%dx%d" % (w, h))

    hdc = _u32.GetWindowDC(hwnd)
    mdc = _g32.CreateCompatibleDC(hdc)
    bmp = _g32.CreateCompatibleBitmap(hdc, w, h)
    _g32.SelectObject(mdc, bmp)
    try:
        ok = _u32.PrintWindow(hwnd, mdc, 2)   # PW_RENDERFULLCONTENT
        if not ok:
            raise RuntimeError("PrintWindow 失败（窗口可能没在渲染）")
        bi = _BITMAPINFO()
        bi.bmiHeader.biSize = ctypes.sizeof(_BITMAPINFOHEADER)
        bi.bmiHeader.biWidth = w
        bi.bmiHeader.biHeight = -h          # 负数 = 自上而下
        bi.bmiHeader.biPlanes = 1
        bi.bmiHeader.biBitCount = 32
        bi.bmiHeader.biCompression = 0      # BI_RGB
        buf = ctypes.create_string_buffer(w * h * 4)
        _g32.GetDIBits(mdc, bmp, 0, h, buf, ctypes.byref(bi), 0)
        return Image.frombuffer("RGBA", (w, h), buf, "raw", "BGRA", 0, 1).convert("RGB")
    finally:
        _g32.DeleteObject(bmp)
        _g32.DeleteDC(mdc)
        _u32.ReleaseDC(hwnd, hdc)


def content_variance(img) -> float:
    """粗略衡量画面「有没有内容」。纯色（黑屏/托盘）接近 0。"""
    import statistics
    px = list(img.getdata())
    sample = px[:: max(1, len(px) // 4000)]
    flat = [c for p in sample for c in p]
    return round(statistics.pstdev(flat), 1) if flat else 0.0


def capture_full(hwnd: int | None = None, *, require_renderable: bool = True):
    """找窗口 → 截图。返回 (PIL.Image, 窗口信息 dict)。

    窗口没在渲染时抛 WindowNotRenderable，让调用方给出人话提示，
    而不是默默拿到一张黑图当成「没有新消息」。
    """
    if hwnd is None:
        hwnd = find_wechat_window()
    state = describe_state(hwnd)
    if require_renderable and not is_renderable(hwnd):
        raise WindowNotRenderable(
            "微信窗口当前是「%s」状态，截不到内容。"
            "请把微信窗口打开（可以被其他窗口挡住，但不能最小化或收进托盘）。" % state)
    img = capture_window(hwnd)
    info = {"hwnd": hwnd, "state": state, "size": img.size,
            "variance": content_variance(img)}
    return img, info


if __name__ == "__main__":
    import sys
    wins = list_candidate_windows()
    print("候选窗口 %d 个：" % len(wins))
    for w in wins:
        print("  hwnd=%#010x visible=%s minimized=%s process=%r title=%r" % (
            w["hwnd"], w["visible"], w["minimized"], w["process"], w["title"]))
    if not wins:
        sys.exit(1)
    img, info = capture_full()
    out = "sync/debug/wx_probe/cli_capture.png"
    img.save(out)
    print("已截图：%s  %dx%d  内容方差=%s  状态=%s" % (
        out, info["size"][0], info["size"][1], info["variance"], info["state"]))
