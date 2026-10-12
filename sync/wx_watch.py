# -*- coding: utf-8 -*-
"""盯住微信里「某一个群」的独立窗口，把新消息识别出来写进工作台。

## 为什么是这个方案

微信 4.x **不接受程序发来的任何操作**（点击 / 滚动 / 键盘，实测全部无效），
所以「自动翻群、点开聊天」这条路是死的。

但只要**那个群一直开着**，它的聊天内容就是「当前可见的一屏」，
而且是**最新的一屏**（微信停在底部时新消息会自动追加）。
于是：**不用点、不用滚** —— 定时截一张图、识别文字，就够了。

推荐把这个群**开成独立窗口**（右键会话 →「在独立窗口中打开」）：
独立窗口常驻屏幕一角，你还能正常用微信主窗口，互不干扰。

## 用法

    python sync/wx_watch.py --list                 # 先看看微信现在有哪些窗口
    python sync/wx_watch.py --dry                  # 只识别不写库
    python sync/wx_watch.py                        # 识别并写进工作台
    python sync/wx_watch.py --all                  # 连闲聊也一起入库（默认只留「要做事」的）
    python sync/wx_watch.py --group 金融工程2班      # 指定群名关键词

## 边界（必须知道）

- 只能读到**屏幕上一屏**的消息（约十几条）。两次抓取之间如果刷了更多，会漏掉中间部分。
- OCR 对小字有误差（实测形近字会被认错），所以**关键词匹配用宽松规则**。
- 图片 / 二维码里的文字会被识别成乱码，已用质量分过滤，但不保证 100% 干净。
"""
from __future__ import annotations

import argparse
import ctypes
import ctypes.wintypes as wt
import hashlib
import re
import sys
import time
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
for p in (str(ROOT), str(HERE)):
    if p not in sys.path:
        sys.path.insert(0, p)

from backend.database import Database            # noqa: E402
from adapters.keywords import classify_action    # noqa: E402
import wx_capture as C                           # noqa: E402
import wx_chat as CH                             # noqa: E402
from wx_ocr import recognize_file                # noqa: E402

DB_PATH = ROOT / "data" / "workbench.sqlite3"
DEBUG_DIR = HERE / "debug" / "wx_capture"
WECHAT_PREFIX = "wechat-"
DEFAULT_GROUP_KEY = "金融工程2班"

# 群聊里的「通知 / 文件」信号。
#
# 平台通知那套规则（作业 / 考试 / 报名 / 加群，见 adapters/keywords.py）覆盖不到
# 班群里最常见的一类：「甩个文件 + 一句要求」（"附件2：…汇总表.xlsx""请大家填一下"）。
# 所以这里再补一层 —— 宁可多留，也别把要紧的东西漏掉。
GROUP_NOTICE_RE = re.compile(
    r"@所有人|@全体成员|@全体|"
    r"附件\d*|请查收|通知|公告|须知|汇总表|申报书|申请表|报名表|登记表|统计表|名单|"
    r"截止|务必|记得|别忘|需要交|提交|上交|抓紧|按时|尽快|尽快|"
    r"填写|填报|回复|确认|领取|缴费|签到|打卡|面试|开会|班会|讲座|宣讲")

_u32 = ctypes.windll.user32


# --------------------------------------------------------------------------
# 窗口查找（不限类名 —— 独立窗口的类名不一定跟主窗口一样）
# --------------------------------------------------------------------------

class GroupWindowNotFound(RuntimeError):
    """没找到那个群的窗口。"""


def list_wechat_windows() -> list[dict]:
    """列出所有属于微信进程、且带标题的顶层窗口。"""
    out: list[dict] = []

    def cb(hwnd, _lparam):
        n = _u32.GetWindowTextLengthW(hwnd)
        if n <= 0:
            return True
        buf = ctypes.create_unicode_buffer(n + 2)
        _u32.GetWindowTextW(hwnd, buf, n + 2)
        title = buf.value.strip()
        if not title:
            return True
        proc = C._process_name_of(hwnd)
        if proc not in C.WECHAT_PROCESS_NAMES:
            return True
        r = wt.RECT()
        _u32.GetWindowRect(hwnd, ctypes.byref(r))
        out.append({
            "hwnd": hwnd,
            "title": title,
            "process": proc,
            "visible": bool(_u32.IsWindowVisible(hwnd)),
            "minimized": bool(_u32.IsIconic(hwnd)),
            "size": (r.right - r.left, r.bottom - r.top),
        })
        return True

    _u32.EnumWindows(ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)(cb), 0)
    return out


def find_group_window(keyword: str) -> dict:
    """按群名关键词找窗口。找不到时抛出带人话提示的异常。"""
    wins = list_wechat_windows()
    hit = [w for w in wins if keyword and keyword in w["title"]]
    if not hit:
        titles = "、".join("「%s」" % w["title"] for w in wins) or "（没有）"
        raise GroupWindowNotFound(
            "没找到标题含「%s」的微信窗口。当前微信窗口：%s\n"
            "请把那个群打开（推荐右键会话 →「在独立窗口中打开」），"
            "并保持窗口**不要最小化、不要收进托盘**。" % (keyword, titles))
    # 优先可见的、不是最小化的
    hit.sort(key=lambda w: (not w["visible"], w["minimized"], -w["size"][0]))
    return hit[0]


# --------------------------------------------------------------------------
# 文本清洗 / 去重
# --------------------------------------------------------------------------

# 明显是图片噪声的：纯符号、或符号占比过高
_SYMBOL_ONLY_RE = re.compile(r"^[\W_]+$", re.UNICODE)


def _looks_like_noise(text: str) -> bool:
    """粗筛图片 / 二维码被误读出来的乱码。"""
    t = (text or "").strip()
    if len(t) < 2:
        return True
    if _SYMBOL_ONLY_RE.match(t):
        return True
    good = sum(1 for c in t if c.isalnum() or "\u4e00" <= c <= "\u9fff")
    if good / len(t) < 0.5:
        return True
    # 单个汉字反复出现（"回：回"）大概率是图案
    letters = [c for c in t if "\u4e00" <= c <= "\u9fff"]
    if len(letters) >= 2 and len(set(letters)) == 1:
        return True
    return False


def _normalize(text: str) -> str:
    """归一化后再做 id —— 同一句话在不同截图里 OCR 结果要能对上。"""
    return re.sub(r"[\s\u3000:：，,。.、!！?？\"'“”‘’()（）\[\]【】<>《》~～\-—_|/\\]+", "",
                  text or "").lower()


def stable_id(*parts: str) -> str:
    """跨进程稳定的 id（绝不用内置 hash()，它每进程加随机盐）。"""
    blob = "\x1f".join(_normalize(p) for p in parts if p)
    return WECHAT_PREFIX + hashlib.sha1(blob.encode("utf-8")).hexdigest()[:16]


# --------------------------------------------------------------------------
# 抓取
# --------------------------------------------------------------------------

def collect(group_key: str = DEFAULT_GROUP_KEY, *, save_debug: bool = False) -> dict:
    """截一张图 → 识别 → 还原成消息列表。不写库。"""
    win = find_group_window(group_key)
    hwnd = win["hwnd"]
    if not C.is_renderable(hwnd):
        raise C.WindowNotRenderable(
            "群「%s」的窗口现在是「%s」，截不到内容。"
            "请把它打开（可以被别的窗口挡住，但不能最小化或收进托盘）。"
            % (win["title"], C.describe_state(hwnd)))

    img = C.capture_window(hwnd)
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    shot = DEBUG_DIR / "latest.png"
    img.save(shot)

    return _analyze(img, str(shot), window_title=win["title"])


def analyze_image(path: str | Path) -> dict:
    """不截图，直接从一张现成的图跑（用于验证 / 测试）。"""
    from PIL import Image
    img = Image.open(path)
    return _analyze(img, str(Path(path).resolve()), window_title="(来自图片)")


def _analyze(img, shot_path: str, *, window_title: str) -> dict:
    lines = recognize_file(shot_path)
    title = CH.extract_title(lines, img.size, mode="independent")
    messages = CH.parse_chat(lines, img.size, mode="independent")
    messages = [m for m in messages
                if not _looks_like_noise(m.text) or m.side == "system"]
    return {
        "window_title": window_title,
        "title_from_shot": title,
        "size": img.size,
        "messages": messages,
        "shot": shot_path,
    }


def to_records(messages, group: str, now: str, *, include_all: bool) -> tuple[list[dict], list[str]]:
    """把识别到的消息转成工作台消息记录。返回 (记录, 被跳过的原因)。"""
    records: list[dict] = []
    skipped: list[str] = []
    seen: set[str] = set()

    for m in messages:
        if m.side == "system":
            continue
        text = m.text.strip()
        if _looks_like_noise(text):
            skipped.append(text[:30])
            continue

        hit = classify_action(text)
        if hit is None and GROUP_NOTICE_RE.search(text):
            hit = ("notice", 2)
        if hit is None and not include_all:
            skipped.append(text[:30])
            continue

        kind = hit[0] if hit else "chat"
        who = m.sender or "群友"
        # 标题：把发送者带上，界面上更清楚
        title = text if len(text) <= 42 else text[:41] + "…"
        rid = stable_id(group, who, text)
        if rid in seen:
            continue
        seen.add(rid)

        records.append({
            "id": rid,
            "platform": "wechat",
            "course": "",
            "courseId": "",
            "title": title,
            "content": text,
            "url": "",
            "time": now,
            "read": False,
            "kind": kind,
            "deadline": "",
            "group": group,
            "sender": who,
        })
    return records, skipped


def merge_into_state(state: dict, records: list[dict], *, now: str) -> dict:
    """按 id 去重合并；尊重用户在界面上删过的条目。"""
    raw = state.get("settings", {}).get("dismissed")
    dismissed = set(raw) if isinstance(raw, list) else set()

    existing = {m.get("id"): m for m in state.get("messages", [])
                if isinstance(m, dict) and str(m.get("id", "")).startswith(WECHAT_PREFIX)}

    added = 0
    for rec in records:
        if rec["id"] in dismissed:
            continue
        if rec["id"] in existing:
            continue                      # 已经入过，保持用户已读状态不动
        existing[rec["id"]] = rec
        added += 1

    others = [m for m in state.get("messages", [])
              if not (isinstance(m, dict) and str(m.get("id", "")).startswith(WECHAT_PREFIX))]
    state["messages"] = others + list(existing.values())
    return {"added": added, "total_wechat": len(existing)}


# --------------------------------------------------------------------------
# 主流程
# --------------------------------------------------------------------------

def run(db_path: str | Path = DB_PATH, group_key: str = DEFAULT_GROUP_KEY, *,
        include_all: bool = False, dry: bool = False,
        image: str | None = None) -> dict:
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    data = analyze_image(image) if image else collect(group_key)
    group = data["title_from_shot"] or data["window_title"]
    records, skipped = to_records(data["messages"], group, now, include_all=include_all)

    result = {
        "window_title": data["window_title"],
        "title_from_shot": data["title_from_shot"],
        "size": data["size"],
        "found": len(data["messages"]),
        "records": len(records),
        "skipped": len(skipped),
        "shot": data["shot"],
        "added": 0,
        "total_wechat": 0,
    }
    if dry:
        return result

    db = Database(str(db_path))
    state = db.load_state()
    if state is None:
        raise SystemExit("数据库里还没有状态，请先启动一次工作台（启动工作台.bat）。")
    merged = merge_into_state(state, records, now=now)
    db.save_state(state)
    result["added"] = merged["added"]
    result["total_wechat"] = merged["total_wechat"]
    return result


def main() -> int:
    ap = argparse.ArgumentParser(description="抓取微信某个群的新消息并写进工作台")
    ap.add_argument("--group", default=DEFAULT_GROUP_KEY,
                    help="群名关键词（默认「%s」）" % DEFAULT_GROUP_KEY)
    ap.add_argument("--all", action="store_true",
                    help="连闲聊也一起入库（默认只留通知 / 要做事类的）")
    ap.add_argument("--dry", action="store_true", help="只识别，不写库")
    ap.add_argument("--list", action="store_true", help="列出微信当前所有窗口后退出")
    ap.add_argument("--image", help="不截屏，直接用一张现成图片跑（验证用）")
    args = ap.parse_args()

    if args.list:
        wins = list_wechat_windows()
        print("微信窗口共 %d 个：" % len(wins))
        for w in wins:
            print("  hwnd=%#010x 可见=%-5s 最小化=%-5s %dx%d | %s" % (
                w["hwnd"], w["visible"], w["minimized"],
                w["size"][0], w["size"][1], w["title"]))
        return 0

    try:
        data = analyze_image(args.image) if args.image else collect(args.group)
    except (GroupWindowNotFound, C.WindowNotRenderable) as e:
        print("!! %s" % e)
        return 2
    except FileNotFoundError as e:
        print("!! 图片不存在：%s" % e)
        return 2

    print("窗口标题 : %s" % data["window_title"])
    print("图内标题 : %s" % (data["title_from_shot"] or "(没读到)"))
    print("截图尺寸 : %dx%d" % data["size"])

    records, skipped = to_records(data["messages"], data["title_from_shot"] or data["window_title"],
                                  datetime.now().astimezone().isoformat(timespec="seconds"),
                                  include_all=args.all)

    print("\n--- 识别到的消息（%d 条）---" % len(data["messages"]))
    print(CH.render_chat(data["messages"]))
    print("\n--- 判定为「值得入库」（%d 条）---" % len(records))
    for r in records:
        print("  [%s] %s：%s" % (r["kind"], r["sender"], r["title"]))
    if skipped:
        print("\n--- 跳过（闲聊 / 噪声，%d 条）---" % len(skipped))
        for s in skipped[:10]:
            print("  · %s" % s)

    if args.dry:
        print("\n--dry：没有写库。")
        return 0

    if not records:
        print("\n没有需要入库的消息（当前这一屏没有通知类内容）。")
        return 0

    r = run(group_key=args.group, image=args.image)
    print("\n已入库 %d 条（微信来源共 %d 条）。刷新工作台页面即可看到。" % (r["added"], r["total_wechat"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
