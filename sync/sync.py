# -*- coding: utf-8 -*-
"""
学伴 · 数据同步脚本

作用：用你自己的登录态，把 超星学习通 / 雨课堂 / 中国大学MOOC / 教务系统
上的通知、作业、DDL 抓下来，写进同目录的「学伴.html」。

用法（直接双击 一键同步数据.bat 即可，下面是手动用法）：
    python sync/sync.py                    # 全部平台（会弹出浏览器窗口）
    python sync/sync.py --only chaoxing    # 只同步学习通
    python sync/sync.py --login            # 只走一遍登录，不抓数据
    python sync/sync.py --debug            # 记录所有 JSON 接口到 sync/debug/
    python sync/sync.py --force-login      # 强制重新扫码
    python sync/sync.py --headless         # 后台模式：不弹窗口，登录过期就跳过

设计要点：
  * 用 Playwright 持久化 profile 保存登录态，扫码一次之后长期有效。
  * 抓取走 context.request（共用 cookie，不受 CORS 限制），比扒 DOM 稳。
  * 抓到的数据同时写到 sync/sync-data.json 和注入 HTML，两条路都能用。
  * 结果优先通过本机 API 入库；**接口不通时直接写 SQLite** —— 定时同步多半在
    工作台没开着的时候跑，如果只在接口可用时入库，等用户晚上打开工作台看到的还是旧数据。
  * 全程只允许一个实例在跑（锁文件）。否则定时任务和工作台里的「立即同步」
    会同时抢同一个 Chromium profile，表现就是随机崩溃。
"""
from __future__ import annotations

import argparse
import asyncio
import io
import json
import os
import re
import shutil
import sys
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from urllib import error as urlerror
from urllib import request as urlrequest

# ---- 让 Windows 控制台能正常输出中文和方框字符 ----
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
HTML = ROOT / "学伴.html"
HTML_BAK = ROOT / "学伴.原始备份.html"
DATA_JSON = HERE / "sync-data.json"
STATE = HERE / "state"
PROFILE = STATE / "profile"
LOCK = STATE / "sync.lock"
SERVER_URL = os.environ.get("LWB_SERVER_URL", "http://127.0.0.1:8765").rstrip("/")

# 访问**本机**工作台接口用的 opener：显式清空代理表。
# 为什么必须这么做：urllib 默认走 getproxies()，只要系统里设了 HTTP_PROXY
# （Clash / v2ray / 公司代理都会设），连 127.0.0.1:8765 的请求也会被塞给代理，
# 代理自然不认识这个地址，于是接口永远失败 —— 表现为每次同步都静默退化成
# 「直接写库」。回环地址本来就不该经过代理，这里直接禁掉。
LOCAL_OPENER = urlrequest.build_opener(urlrequest.ProxyHandler({}))


# 本机已装好的浏览器内核优先（避免重复下载几百 MB）
CANDIDATE_BROWSERS = [
    Path.home() / ".workbuddy" / "binaries" / "ms-playwright",
    Path(os.environ.get("LOCALAPPDATA", "")) / "ms-playwright",
]

# 默认只同步「消息通知 + 待办」这三家。
# 教务系统（jw）**不在**默认列表里：课表按约定由手动录入，教务要过统一身份认证
# 加短信验证码，每次自动跑都会白等一轮。需要时用 --only jw 单独跑。
ADAPTER_ORDER = ["chaoxing", "yuketang", "icourse163"]
ADAPTER_LABEL = {
    "chaoxing": "超星学习通",
    "yuketang": "雨课堂",
    "icourse163": "中国大学 MOOC",
    "jw": "教务系统",
}


# ==================== 输出 ====================

class Log:
    """同时写控制台和**当天的日志文件**。

    日志文件是给定时同步准备的：它在你上课的时候无人值守地跑，
    事后唯一能回看「昨晚那次到底成功了没」的地方就是这个文件。
    而且定时任务用的是 pythonw.exe，压根没有控制台 —— 不落盘就什么都查不到。
    """

    LOG_DIR = HERE / "logs"
    KEEP_DAYS = 30

    def __init__(self):
        self.t0 = time.time()
        self.path = self.LOG_DIR / ("sync-%s.log" % datetime.now().strftime("%Y-%m-%d"))
        self._fh = None
        self._pruned = False

    def __call__(self, msg: str, level: str = "info"):
        mark = {"info": " ", "warn": "!", "err": "x", "dim": ".", "ok": "+"}.get(level, " ")
        prefix = "  " if level == "dim" else ""
        self._write("%s%s %s" % (prefix, mark, msg))

    def head(self, msg: str):
        self._write("")
        self._write("=" * 62)
        self._write(" " + msg)
        self._write("=" * 62)

    def elapsed(self) -> str:
        return "%.1f 秒" % (time.time() - self.t0)

    def _write(self, line: str) -> None:
        """往控制台写一行，同时也写进当天的日志文件。

        用 pythonw.exe（无窗口）跑的时候 sys.stdout / sys.stderr 都是 None，
        不判一下会直接抛 AttributeError。定时同步走的就是这条路。
        """
        stream = sys.stdout
        if stream is not None:
            try:
                print(line, flush=True)
            except UnicodeEncodeError:
                try:
                    print(line.encode("ascii", "replace").decode(), flush=True)
                except Exception:
                    pass
            except Exception:
                pass

        fh = self._file()
        if fh is not None:
            try:
                fh.write("%s %s\n" % (datetime.now().strftime("%H:%M:%S"), line))
                fh.flush()
            except Exception:
                pass

    def _file(self):
        if self._fh is not None:
            return self._fh
        try:
            self.LOG_DIR.mkdir(parents=True, exist_ok=True)
            if not self._pruned:
                self._pruned = True
                cutoff = time.time() - self.KEEP_DAYS * 86400
                for old in self.LOG_DIR.glob("sync-*.log"):
                    try:
                        if old.stat().st_mtime < cutoff:
                            old.unlink()
                    except OSError:
                        pass
            self._fh = open(self.path, "a", encoding="utf-8")
        except OSError:
            self._fh = None
        return self._fh


log = Log()


# ==================== 环境 ====================

def pin_browsers_path():
    if os.environ.get("PLAYWRIGHT_BROWSERS_PATH"):
        return
    for p in CANDIDATE_BROWSERS:
        try:
            if p and p.is_dir() and any(p.iterdir()):
                os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(p)
                return
        except Exception:
            continue


def find_local_chromium():
    """在本机已有的 playwright 浏览器目录里找一个能用的 Chromium。

    这样可以避免为了版本号对齐而重新下载 200MB 内核。
    """
    roots = []
    env = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
    if env:
        roots.append(Path(env))
    roots.extend(CANDIDATE_BROWSERS)
    for root in roots:
        try:
            for d in sorted(root.glob("chromium-*"), reverse=True):
                for rel in ("chrome-win64/chrome.exe", "chrome-win/chrome.exe",
                            "chrome-linux/chrome", "chrome-mac/Chromium.app/Contents/MacOS/Chromium"):
                    exe = d / rel
                    if exe.exists():
                        return exe
        except Exception:
            continue
    return None


def find_system_browser():
    """找本机已经装好的 Edge / Chrome 可执行文件。

    给发布包用：别人电脑上多半没有 Playwright 自带的内核（要另下 150MB），
    但 Windows 10/11 出厂就带 Edge。直接借来用，第一次打开就能抓，不用等下载。
    """
    rels = (
        ("Microsoft", "Edge", "Application", "msedge.exe"),
        ("Google", "Chrome", "Application", "chrome.exe"),
    )
    for env in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
        base = os.environ.get(env)
        if not base:
            continue
        for rel in rels:
            exe = Path(base).joinpath(*rel)
            if exe.exists():
                return exe
    return None


async def launch_browser(p, log, headless: bool = False):
    """按「自带内核 → 系统 Edge/Chrome → 本机 Chromium」的顺序挑一个能用的。

    headless=True 用于定时同步：不弹窗口，不会在你上课/写作业的时候
    突然跳出来一个浏览器挡住屏幕。实测过这个内核在无窗口模式下一样能读到
    已保存的登录态、也能正常跑通学习通的页面抓取。

    为什么要按顺序试：你自己的电脑上 Playwright 内核早就装好了，走第一条最快；
    而别人刚拿到发布包时可能一个内核都没有 —— 那就借他电脑里现成的 Edge，
    免得为了 150MB 卡在第一次打开。用的始终是项目内的独立配置目录，
    不会碰对方日常浏览器的书签、密码和登录状态。
    """
    kw = dict(
        user_data_dir=str(PROFILE),
        headless=headless,
        viewport={"width": 1280, "height": 880},
        locale="zh-CN",
        timezone_id="Asia/Shanghai",
        args=["--disable-blink-features=AutomationControlled",
              "--no-first-run", "--no-default-browser-check"],
    )

    errors = []

    # ① Playwright 自带内核
    try:
        return await p.chromium.launch_persistent_context(**kw)
    except Exception as e:
        errors.append("自带内核：%s" % str(e).split("\n")[0][:60])

    # ② 系统 Edge / Chrome
    for channel in ("msedge", "chrome"):
        try:
            ctx = await p.chromium.launch_persistent_context(channel=channel, **kw)
            log("改用你电脑上已装的 %s 来抓取（不需要额外下载内核）。" % channel, level="dim")
            return ctx
        except Exception as e:
            errors.append("%s：%s" % (channel, str(e).split("\n")[0][:60]))

    # ③ 本机已有的 Chromium（别人手动跑过 playwright install 的情况）
    exe = find_local_chromium()
    if exe:
        try:
            ctx = await p.chromium.launch_persistent_context(executable_path=str(exe), **kw)
            log("改用本机已有的 Chromium：%s" % exe, level="warn")
            return ctx
        except Exception as e:
            errors.append("本地 Chromium：%s" % str(e).split("\n")[0][:60])

    raise RuntimeError(
        "没有找到可用的浏览器内核。请先安装 Microsoft Edge 或 Google Chrome"
        "（Win10/11 一般自带 Edge），或者执行  python -m playwright install chromium  。"
        "详情：" + " | ".join(errors)
    )


# ==================== 注入 ====================

SYNC_RE = re.compile(
    r'(<script id="sync-payload" type="application/json">)(.*?)(</script>)',
    re.S,
)


def inject_into_html(payload: dict) -> str:
    if not HTML.exists():
        return "未找到 %s，跳过注入" % HTML.name
    html = HTML.read_text(encoding="utf-8")
    if not HTML_BAK.exists():
        shutil.copy2(HTML, HTML_BAK)

    block = json.dumps(payload, ensure_ascii=False, indent=2)
    block = block.replace("</script>", "<\\/script>")

    new_html, n = SYNC_RE.subn(
        lambda m: m.group(1) + "\n" + block + "\n" + m.group(3),
        html, count=1)
    if n == 0:
        return "未在工作台 HTML 里找到同步数据槽，注入失败（HTML 未被修改）"

    # 先写临时文件再替换，避免中途失败把原文件写坏
    tmp = HTML.with_suffix(".html.tmp")
    tmp.write_text(new_html, encoding="utf-8")
    tmp.replace(HTML)
    return "已写入 %s" % HTML.name


def post_to_server(payload: dict) -> tuple[bool, str]:
    """If the local API is running, persist the result directly to SQLite.

    返回 (是否成功, 原因)。原因要能区分「服务没开」和「服务开了但报错」——
    不然日志里一律只说「没开着」，出问题时根本看不出到底卡在哪。
    """
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urlrequest.Request(
        SERVER_URL + "/api/sync/import", data=body, method="POST",
        headers={"Content-Type": "application/json; charset=utf-8"},
    )
    try:
        # 本地回环实测约 0.45s。给到 5s 是留出 SQLite 冷启动 checkpoint
        # 的余量；2s 在磁盘忙的时候会偶发超时，然后白跑一次兜底写入。
        with LOCAL_OPENER.open(req, timeout=5) as res:
            data = json.loads(res.read().decode("utf-8"))
    except urlerror.HTTPError as exc:
        return False, "接口返回 %s" % exc.code
    except urlerror.URLError as exc:
        reason = getattr(exc, "reason", exc)
        # 10061 / ConnectionRefused：服务压根没在跑，属于正常情况
        if "refused" in str(reason).lower() or "10061" in str(reason):
            return False, "服务没在运行"
        return False, "连不上接口（%s）" % reason
    except TimeoutError:
        return False, "接口超时"
    except (ValueError, UnicodeDecodeError) as exc:
        return False, "接口返回了非 JSON 内容（%s）" % exc
    if not data.get("ok"):
        return False, "接口拒绝了这次写入：%s" % (data.get("error") or "未知原因")
    return True, ""


def save_to_database(payload: dict) -> tuple[bool, str]:
    """接口不通时直接写 SQLite。

    定时同步大多发生在「工作台没开着」的时候（比如早上 8 点）。如果这时候
    只把结果写进 sync-data.json / 注入 HTML，等晚上打开工作台读到的还是旧库，
    用户会觉得「自动同步根本没生效」。所以这里走和 API 完全一样的合并逻辑：
    backend.server.merge_payload + backend.database.Database。
    """
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    try:
        from backend.database import Database
        from backend.server import merge_payload
    except ImportError as exc:
        return False, "导入后端模块失败：%s" % exc
    db = Database(ROOT / "data" / "workbench.sqlite3")
    state = db.load_state()
    if state is None:
        return False, "数据库还没初始化（先打开一次工作台再试）"
    db.save_state(merge_payload(state, payload))
    db.record_sync(payload)
    return True, ""


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        try:
            import ctypes
            handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
            if not handle:
                return False
            ctypes.windll.kernel32.CloseHandle(handle)
            return True
        except Exception:
            return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


@contextmanager
def single_instance(log):
    """一次只让一个同步在跑。

    定时任务和网页上的「立即同步」很容易撞车，而两边用的是**同一个
    Chromium profile 目录** —— 同时启动的结果是其中一个随机崩掉，
    表现出来就是「有时候抓得到、有时候抓不到」这种最难查的毛病。

    yield True 表示拿到锁可以继续；False 表示已经有别人在跑，本次直接退出。
    """
    STATE.mkdir(parents=True, exist_ok=True)
    fd = None
    for attempt in (1, 2):
        try:
            fd = os.open(str(LOCK), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            break
        except FileExistsError:
            pid, age = 0, 1e9
            try:
                info = json.loads(LOCK.read_text(encoding="utf-8"))
                pid = int(info.get("pid") or 0)
                age = max(0.0, time.time() - float(info.get("at") or 0))
            except Exception:
                pass
            if attempt == 1 and pid and _pid_alive(pid) and age < 3 * 3600:
                log("已经有一个同步在跑了（PID %d），本次跳过。" % pid, level="warn")
                yield False
                return
            log("清理上次残留的同步锁（PID %s，%.0f 分钟前）" % (pid or "?", age / 60), level="warn")
            try:
                os.remove(LOCK)
            except OSError:
                pass
        except OSError as exc:
            log("无法创建同步锁（%s），本次不加锁继续跑。" % exc, level="warn")
            yield True
            return
    else:
        yield False
        return

    try:
        os.write(fd, json.dumps({"pid": os.getpid(), "at": time.time()}).encode("utf-8"))
        yield True
    finally:
        try:
            os.close(fd)
        except OSError:
            pass
        try:
            os.remove(LOCK)
        except OSError:
            pass


# ==================== 抓取 ====================

async def run(args) -> int:
    """入口：先抢单实例锁，抢到才真正开跑。"""
    with single_instance(log) as acquired:
        if not acquired:
            return 0
        return await _sync(args)


async def _sync(args) -> int:
    pin_browsers_path()
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        log("没有找到 playwright。请先双击「安装环境.bat」。", level="err")
        return 2

    from adapters import BY_KEY
    from adapters.base import is_browser_dead as _is_browser_dead
    from login_health import check_all as check_login_health
    from alerting import maybe_notify as notify_login_health
    from push_to_cloud import run as push_to_cloud_run

    keys = [k.strip() for k in (args.only or "").split(",") if k.strip()] or ADAPTER_ORDER
    keys = [k for k in keys if k in BY_KEY]
    if not keys:
        log("没有可用的适配器（--only 写错了吗？可选：%s）" % ", ".join(ADAPTER_ORDER), level="err")
        return 2

    PROFILE.mkdir(parents=True, exist_ok=True)
    (HERE / "debug").mkdir(exist_ok=True)

    started_at = datetime.now().astimezone().isoformat()
    payload = {
        "startedAt": started_at,
        "syncedAt": started_at,
        "note": "",
        "courses": [], "messages": [], "todos": [], "connections": [],
    }

    log.head("学伴 · 数据同步")
    log("本次平台：%s" % "、".join(ADAPTER_LABEL[k] for k in keys))
    if args.headless:
        log("后台模式：不弹浏览器窗口；登录过期会跳过并在工作台里标注「需要登录」")
    if args.debug:
        log("调试模式：所有 JSON 接口会记录到 sync/debug/")
    log("")

    summary = []

    async with async_playwright() as p:
        ctx = await launch_browser(p, log, headless=args.headless)
        try:
            for k in keys:
                cls = BY_KEY[k]
                ad = cls(ctx, log, debug=args.debug, dry=False,
                         interactive=not args.headless)
                log.head("%s" % ADAPTER_LABEL[k])
                for attempt in (1, 2):
                    try:
                        ok = await ad.ensure_login(force=args.force_login)
                        if not ok:
                            summary.append((k, "未登录", 0, 0, 0))
                            break
                        if args.login:
                            summary.append((k, "仅登录", 0, 0, 0))
                            break
                        res = await ad.fetch()
                        payload["courses"].extend(res.get("courses", []))
                        payload["messages"].extend(res.get("messages", []))
                        payload["todos"].extend(res.get("todos", []))
                        summary.append((k, "成功", len(res.get("courses", [])),
                                        len(res.get("messages", [])), len(res.get("todos", []))))
                        break
                    except Exception as e:
                        if attempt == 1 and _is_browser_dead(e):
                            log("[%s] 浏览器异常退出，重启后重试一次…" % ADAPTER_LABEL[k], level="warn")
                            try:
                                await ctx.close()
                            except Exception:
                                pass
                            try:
                                ctx = await launch_browser(p, log, headless=args.headless)
                            except Exception as e2:
                                log("[%s] 重启浏览器失败：%r" % (ADAPTER_LABEL[k], e2), level="err")
                                summary.append((k, "出错", 0, 0, 0))
                                break
                            ad = cls(ctx, log, debug=args.debug, dry=False,
                                     interactive=not args.headless)
                            continue
                        log("[%s] 抓取出错：%r" % (ADAPTER_LABEL[k], e), level="err")
                        summary.append((k, "出错", 0, 0, 0))
                        break
        finally:
            try:
                await ctx.close()
            except Exception:
                pass

    # ---- 汇总 ----
    log.head("抓取结果")
    for k, st, c, m, t in summary:
        log("%-16s %-6s 课程 %d · 通知 %d · 待办 %d" % (ADAPTER_LABEL[k], st, c, m, t))

    # 各平台各抓各的，同一条通知可能被重复带进来（老师重发通知、翻页时跨页重复）。
    # id 是内容哈希，按它去掉最准。放在汇总之后做，顺便把「去掉了几条」说清楚 ——
    # 否则用户看到「平台统计 3 条、总量 2 条」会以为哪里算错了。
    _before = (len(payload["messages"]), len(payload["todos"]))
    payload["messages"] = _dedupe(payload["messages"])
    payload["todos"] = _dedupe(payload["todos"])
    if (len(payload["messages"]), len(payload["todos"])) != _before:
        log("去重：通知 %d→%d，待办 %d→%d（同一条通知被重复抓到）"
            % (_before[0], len(payload["messages"]), _before[1], len(payload["todos"])))

    total = len(payload["courses"]) + len(payload["messages"]) + len(payload["todos"])
    payload["syncedAt"] = datetime.now().astimezone().isoformat()
    payload["note"] = "%d 门课程 / %d 条通知 / %d 项待办%s" % (
        len(payload["courses"]), len(payload["messages"]), len(payload["todos"]),
        "（定时自动）" if args.reason == "schedule" else "")
    status_map = {"成功": "connected", "仅登录": "connected", "未登录": "needs_login", "出错": "error"}
    payload["connections"] = [
        {"key": k, "status": status_map.get(st, "error"),
         "lastSync": payload["syncedAt"] if st in ("成功", "仅登录") else None,
         "error": "抓取失败，请使用 --debug 重试" if st == "出错" else ""}
        for k, st, _c, _m, _t in summary
    ]

    # ---- 登录态体检 ----
    # 超星 / 雨课堂的 cookie 带服务端写死的到期时间，反复同步并不会续期
    # （实测：访问前后 _uid 都停在 2026-10-15，一动不动）。既然躲不掉，就提前
    # 告诉用户还剩几天，别等他某天发现数据不更新了再回来排查。
    # 必须在浏览器关掉之后再读 —— cookie 要等 Chromium flush 到磁盘。
    health = check_login_health(profile=PROFILE)
    payload["loginHealth"] = health
    for conn in payload["connections"]:
        h = (health.get("platforms") or {}).get(conn["key"])
        if h:
            conn["expiresAt"] = h.get("expiresAt")
            conn["daysLeft"] = h.get("daysLeft")
            conn["loginStatus"] = h.get("status")

    payload["status"] = "partial" if any(st == "出错" for _k, st, _c, _m, _t in summary) else "success"

    log.head("登录态体检")
    for _pid, p in (health.get("platforms") or {}).items():
        st = p.get("status")
        when = (p.get("expiresAt") or "")[:10]
        if st == "ok":
            log("%-16s 有效，还剩 %s 天（%s）" % (p["label"], p["daysLeft"], when))
        elif st == "expiring":
            log("%-16s 快到期，只剩 %s 天 —— 双击「重新登录.bat」即可续期"
                % (p["label"], p["daysLeft"]), level="warn")
        elif st == "expired":
            log("%-16s 已过期，需要重新扫码登录" % p["label"], level="warn")
        elif st == "unknown":
            log("%-16s 找不到登录凭证，需要登录一次" % p["label"], level="warn")
        else:
            log("%-16s 会话级凭证，本次同步自动重建，无需处理" % p["label"], level="dim")

    # --only 是排障用的单平台抓取，载荷**不完整**，不能当成完整快照落盘：
    # 一旦覆盖 sync-data.json 和单文件 HTML 里的注入块，其余平台的数据就直接消失了
    # （看着像「同步把数据弄丢了」）。数据库那边走的是合并入库，所以那条路仍然安全。
    if args.only:
        log("")
        log("--only 只抓了 %s：跳过写 %s 与工作台 HTML，避免把完整快照覆盖成残缺的。"
            % (args.only, DATA_JSON.name), level="warn")
    else:
        DATA_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        log("")
        log("已生成 %s" % DATA_JSON.name, level="ok")
        log(inject_into_html(payload), level="ok")
    served, why = post_to_server(payload)
    if served:
        log("已同步到本机 SQLite 数据库（经接口）", level="ok")
    else:
        # 工作台没开着是定时同步的常态，这条路必须能走通
        log("接口没走通（%s），改为直接写数据库" % why)
        ok, err = save_to_database(payload)
        if ok:
            log("已直接写入本机数据库，打开工作台就能看到", level="ok")
        else:
            log("写入数据库失败：%s" % err, level="warn")
            log("  数据仍保存在 %s 与工作台 HTML 里，下次打开工作台会走接口入库。"
                % DATA_JSON.name, level="warn")

    # ---- 登录态提醒 ----
    # 排障用的 --only 不打扰用户；只有完整同步才按策略决定要不要弹通知。
    if not args.only:
        alert = notify_login_health(health)
        if alert.get("sent"):
            log("已弹出系统通知，提醒你处理登录态（同一状态不会反复弹）", level="warn")
        elif alert.get("signature"):
            log("登录态提醒：%s" % alert.get("reason"), level="dim")

    # ---- 推送到手机 ----
    # 单独一步，且**失败只写日志**：本机同步的核心承诺是「数据一定落到工作台」，
    # 手机推送只是多开一条通道。它因为网络、密钥、云端配额出问题都很正常，
    # 不该让计划任务报失败，更不该让人以为「同步坏了」。
    if not args.only:
        try:
            pr = push_to_cloud_run()
        except Exception as e:  # 兜底：这里再出问题就真的不该影响主流程了
            pr = {"ok": False, "message": "推送模块异常：%r" % e, "count": 0}
        if pr.get("ok") and pr.get("count"):
            log(pr["message"], level="ok")
        elif pr.get("code", 0) >= 1:
            log("手机推送未完成：%s（本机数据不受影响）" % pr.get("message", ""), level="warn")
        else:
            # 未配置 / 内容没变 —— 都是正常状态，不要用告警的语气
            log("手机推送：%s" % pr.get("message", ""), level="dim")

    if total == 0:
        log("")
        log("这次没有抓到任何数据。常见原因：", level="warn")
        log("  1. 某个平台跳过了登录（重新运行并完成扫码）", level="warn")
        log("  2. 平台改版导致接口变了 —— 用 --debug 重新运行，", level="warn")
        log("     然后把 sync/debug/ 里的文件发给助手，一次就能修好", level="warn")

    log("")
    log("总耗时 %s。现在刷新一下工作台页面（F5）就能看到。" % log.elapsed())
    return 0


def _dedupe(items: list) -> list:
    """按 id 去重，保留先出现的。

    id 是「平台 + 标题 + 截止时间」的哈希（见 adapters/base.py 的 todo()），
    所以同一条通知被老师重发、或者翻页时跨页重复，id 会一模一样 —— 按 id 去
    既准又不会误伤「同名但不同课」的通知（那种 id 不同）。

    为什么必须在汇总这一层做：各平台是各抓各的然后 extend 到一起的，
    以前没有这一步，同一条《创业基础》通知在列表里出现了两次。
    """
    seen = set()
    out = []
    for it in items:
        k = str(it.get("id") or "")
        if not k:
            out.append(it)
            continue
        if k in seen:
            continue
        seen.add(k)
        out.append(it)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="学伴数据同步")
    ap.add_argument("--only", default="", help="只同步指定平台，逗号分隔：chaoxing,yuketang,icourse163,jw")
    ap.add_argument("--login", action="store_true", help="只完成登录，不抓数据")
    ap.add_argument("--force-login", action="store_true", help="强制重新登录")
    ap.add_argument("--debug", action="store_true", help="记录所有 JSON 接口，便于排查")
    ap.add_argument("--no-pause", action="store_true", help="结束后不等待按键（给自动化调用）")
    ap.add_argument("--headless", action="store_true",
                    help="后台模式：不开浏览器窗口；登录态过期时直接跳过，不干等扫码")
    ap.add_argument("--reason", default="manual",
                    help="本次同步的触发方式：manual / schedule（只影响日志与备注）")
    args = ap.parse_args()

    code = 0
    try:
        code = asyncio.run(run(args))
    except KeyboardInterrupt:
        log("已取消", level="warn")
        code = 130
    except Exception as e:
        log("运行失败：%r" % e, level="err")
        code = 1

    if not args.no_pause:
        try:
            input("\n按回车键关闭这个窗口…")
        except Exception:
            pass
    return code


if __name__ == "__main__":
    sys.exit(main())
