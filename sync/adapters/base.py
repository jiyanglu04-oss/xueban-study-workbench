# -*- coding: utf-8 -*-
"""适配器基类：统一的登录检测、抓取接口、XHR 调试落盘。"""
from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import re
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

DEBUG_DIR = Path(__file__).resolve().parent.parent / "debug"

# 发布超过这么多天的通知，导入时直接算「已读」。
# 定时同步会翻到通知中心的最后一页，一次带回上百条旧通知；全算未读的话
# 未读角标就没意义了（实测 23 → 103，几乎全是上学期的事）。
# 它们仍然完整保留在消息中心、能搜索、也不影响待办识别，只是不堆在未读里。
# 想全部保留成未读，把这个值改成 None 即可。
HISTORY_READ_DAYS = 30


async def _maybe_await(x):
    """兼容 playwright 里同一方法在不同版本可能返回协程或直接返回值。"""
    if inspect.isawaitable(x):
        return await x
    return x


def stable_id(*parts, n: int = 12) -> str:
    """跨进程稳定的短 id。

    ⚠️ 千万不要用内置 `hash()`：Python 对字符串的 hash 每个进程都带随机盐，
    同一条通知两次运行会算出不同 id，于是**每同步一次就重复入库一次**。
    实测过：连跑几次之后消息从 20 条涨到 87 条全是重复。
    """
    s = "\u0000".join("" if p is None else str(p) for p in parts)
    return hashlib.sha1(s.encode("utf-8")).hexdigest()[:n]


def is_browser_dead(exc: BaseException) -> bool:
    """异常是不是「浏览器 / 上下文已经没了」。

    Chromium 崩溃、profile 被别的窗口占用、标签页被关掉都会走到这里。
    放在基类里，是为了让**适配器内部**也能认出这种情况并往外抛：
    适配器如果自己把这类错误吞掉（只是 log 一条 warning 继续跑），
    外层「重启浏览器重试一次」的逻辑就永远不会触发，结果就是**静默的残缺数据**——
    实测过：作业列表抓到一半浏览器挂掉，最后报「0 项待办」，看起来像正常结果。
    """
    s = str(exc).lower()
    return any(w in s for w in (
        "has been closed", "target closed", "targetclosed", "browser closed",
        "browser has been closed", "connection closed", "crashed", "disconnected",
        "protocol error",
    ))


class Adapter:
    """一个平台的抓取适配器。

    子类需要覆写：
        key / name / login_url
        login_cookies   —— 只有登录后才会下发的 cookie 名列表（用于判断登录态）
        fetch()         —— 返回 {"courses": [...], "messages": [...], "todos": [...]}
    """

    key: str = ""
    name: str = ""
    login_url: str = ""
    home_url: str = ""
    login_cookies: list[str] = []
    # 打开首页后，页面上出现这些文字之一就认为已登录
    login_text_hint: list[str] = []
    # 每次抓取前的固定等待（秒），避免打太快
    throttle: float = 1.5

    def __init__(self, ctx, log, debug: bool = False, dry: bool = False,
                 interactive: bool = True):
        self.ctx = ctx
        self.log = log
        self.debug = debug
        self.dry = dry
        # interactive=False 是「后台/定时」模式：没有真人坐在电脑前，
        # 所以登录态过期时不能傻等 360 秒扫码，而是直接跳过并如实标注「需要登录」。
        self.interactive = interactive
        self._xhr_logged = 0
        self.recorded: list[dict] = []      # 本次会话记录到的 JSON 接口

    # ---------- 登录 ----------

    async def cookies(self, urls: list[str] | None = None) -> dict[str, str]:
        try:
            jar = await self.ctx.cookies(urls) if urls else await self.ctx.cookies()
        except Exception:
            return {}
        out = {}
        for c in jar:
            if c.get("name") and c.get("value"):
                out[c["name"]] = c["value"]
        return out

    async def is_logged_in(self) -> bool:
        """默认实现：检查关键 cookie 是否都已下发。"""
        if not self.login_cookies:
            return False
        jar = await self.cookies()
        return all(jar.get(n) for n in self.login_cookies)

    async def ensure_login(self, force: bool = False, timeout: int = 360) -> bool:
        if not force and await self.is_logged_in():
            self.log("[%s] 登录态有效，跳过扫码" % self.name)
            return True

        if not self.interactive:
            # 定时同步是无人值守的：这时候弹窗口干等是没意义的，
            # 而且会一直卡到超时，把整轮同步拖死。
            self.log("[%s] 登录态已过期。定时同步不会弹窗等扫码，本次跳过 —— "
                     "请手动双击一次「一键同步数据.bat」重新登录。" % self.name, level="warn")
            return False

        page = await self.ctx.new_page()
        await page.goto(self.login_url, wait_until="domcontentloaded", timeout=60000)
        self.log("")
        self.log("=" * 62)
        self.log("【%s】需要在弹出的浏览器窗口里登录一次" % self.name)
        self.log("  支持扫码 / 账号密码，登录方式随平台")
        self.log("  登录成功后会自动继续，不需要你按任何键")
        self.log("  最多等待 %d 秒" % timeout)
        self.log("=" * 62)

        started = time.time()
        ok = False
        while time.time() - started < timeout:
            await asyncio.sleep(2)
            if await self.is_logged_in():
                ok = True
                break
            # 有些平台 cookie 名不确定，用页面文案兜底
            if self.login_text_hint:
                try:
                    txt = await page.inner_text("body")
                    if any(h in txt for h in self.login_text_hint) and "登录" not in txt[:120]:
                        ok = True
                        break
                except Exception:
                    pass
            if page.is_closed():
                break

        if ok:
            self.log("[%s] 登录成功 ✓" % self.name)
            await asyncio.sleep(1.5)
            if not page.is_closed():
                await page.close()
            return True

        self.log("[%s] 登录超时或未检测到登录态 ✗" % self.name, level="warn")
        if not page.is_closed():
            await page.close()
        return False

    # ---------- 抓取 ----------

    async def fetch(self) -> dict[str, Any]:
        raise NotImplementedError

    # ---------- 工具 ----------

    def empty(self) -> dict[str, Any]:
        return {"courses": [], "messages": [], "todos": []}

    async def req(self, url: str, method: str = "GET", *, form=None, json_body=None,
                  headers: dict | None = None, timeout: int = 25000):
        """用 Playwright 的 context.request 发请求。

        它和浏览器共用同一套 cookie，但**不受 CORS 限制**，
        比在页面里 fetch 更稳、更快、也不依赖页面 DOM。

        返回 (status, data)；data 是解析后的 dict/list，或原始文本，或 None。
        """
        hdr = {"Accept": "application/json, text/plain, */*"}
        hdr.update(headers or {})
        kw = {"method": method.upper(), "headers": hdr, "timeout": timeout}
        if form is not None:
            kw["form"] = form
        if json_body is not None:
            kw["data"] = json_body
        try:
            resp = await self.ctx.request.fetch(url, **kw)
        except Exception as e:
            if is_browser_dead(e):
                # 浏览器没了，别装作「这个接口没数据」——往外抛，让外层重启浏览器重跑。
                raise
            self.log("[%s] 请求异常 %s -> %s" % (self.name, url, e), level="warn")
            return None, None

        status = resp.status
        text = await _maybe_await(resp.text())
        # 自己发的请求也落盘 —— 否则 --debug 只能看到页面自己发的接口，
        # 适配器调了什么、返回了什么完全查不到。
        self._write_debug(url, method.upper(), text)
        if status >= 400:
            self.log("[%s] HTTP %s  %s" % (self.name, status, url), level="warn")
            return status, None
        try:
            return status, json.loads(text)
        except Exception:
            return status, text

    # ---------- 调试落盘 ----------

    def _write_debug(self, url: str, method: str, text: str) -> None:
        if not self.debug or text is None:
            return
        try:
            self._xhr_logged += 1
            d = DEBUG_DIR / self.key
            d.mkdir(parents=True, exist_ok=True)
            name = "%03d_%s.json" % (self._xhr_logged, re.sub(r"[^0-9A-Za-z]+", "_", url)[-90:])
            (d / name).write_text(
                json.dumps({"url": url, "method": method, "body": str(text)[:400000]},
                           ensure_ascii=False),
                encoding="utf-8")
        except Exception:
            pass

    def attach_xhr_recorder(self, page):
        """记录页面上所有 JSON / HTML 响应，用于确认未知接口。

        之所以连 HTML 一起记：像学习通的作业列表是**服务端直出的 HTML**，
        只记 JSON 会什么都看不到，作业解析也就无从下手。
        """
        if not self.debug:
            return

        async def _on_response(resp):
            try:
                ct = ((resp.headers or {}).get("content-type") or "").lower()
                url = resp.url
                if any(x in url for x in ("/log", "/report", "/track", "/collect",
                                          "beacon", "sentry", ".png", ".jpg", ".jpeg",
                                          ".gif", ".css", ".woff", ".ico")):
                    return
                if not any(k in ct for k in ("json", "html", "text/plain")):
                    return
                body = await resp.text()
                self.recorded.append({"url": url, "method": resp.request.method,
                                      "body": body, "kind": "html" if "html" in ct else "json"})
                self._write_debug(url, resp.request.method, body)
                self.log("  [debug] 记录 %s" % url, level="dim")
            except Exception:
                pass

        page.on("response", _on_response)

    # ---------- 输出构造 ----------

    def enrich_message(self, m: dict, out: dict, platform: str = "",
                       allow_todo: bool = True, now: datetime | None = None) -> None:
        """给一条通知补上课程名 / 截止时间，并按需把它变成待办。

        这是「通知 → 待办」的核心，三条规则按优先级来：

          1. 正文里解析出**还没到**的截止时间 → 建一条带日期的待办。
             超星/雨课堂的通知正文本来就写着「结束时间：2026-07-03」
             「截止日期9月21日」，只是以前没人去读它。
          2. 解析出的截止时间**已经过去** → 不建。
             把几个月前的旧 DDL 翻出来只会把列表塞满，而错误的待办比没有待办更烦人。
          3. 没有截止时间，但标题/正文命中动作词（作业、考试、报名、加群、问卷…）
             而且**发布时间在 LOOKBACK_DAYS 天之内** → 建一条无日期待办。

        第 3 条的发布时间限制是必须的：第一次同步会把几个月的历史通知一起拉进来，
        不卡时间窗口的话待办列表直接爆炸，全是早就做完的事。

        allow_todo=False 用于「作业列表」那条路径 —— 那里调用方自己会建待办，
        否则同一条作业会被建两次。
        """
        from .deadline import extract_deadline, is_future
        from .keywords import KIND_OF, LOOKBACK_DAYS, action_label, classify_action

        now = now or datetime.now()
        blob = (m.get("title") or "") + " " + (m.get("content") or "")
        if not m.get("course"):
            c = extract_course_name(blob)
            if c:
                m["course"] = c

        # 年份消歧必须拿**这条通知的发布时间**当基准，不能拿 now。
        # 否则一条 2025-12 发的「考试时间：12-25」会被当成 2026-12-25（未来），
        # 平白生成一条一年后的假待办。只抓第 1 页时看不到，一翻历史页就成片出现。
        anchor = None
        try:
            anchor = datetime.fromisoformat(str(m.get("time")))
        except (TypeError, ValueError):
            anchor = None

        iso, snip = extract_deadline(blob, now=now, anchor=anchor)
        if iso:
            m["deadline"] = iso

        # 顺手把消息角标修正一下：「考试通知」以前只显示「公告」，现在能显示「考试」。
        # 只升级、不降级 —— adapter 自己判出来的 homework/exam 不动。
        action = classify_action(blob)
        if action and m.get("kind") in (None, "", "notice"):
            m["kind"] = KIND_OF.get(action[0], "notice")

        if not allow_todo:
            return

        plat = platform or m.get("platform") or ""

        if iso:
            if not is_future(iso, now=now):
                return
            out["todos"].append(self.todo(
                plat, m.get("title") or "", due=iso, course=m.get("course") or "",
                url=m.get("url") or "", priority=1,
                note="自动识别到截止时间" + ("：%s" % snip if snip else "")))
            return

        if not action:
            return
        if not published_recently(m.get("time"), now, LOOKBACK_DAYS):
            return
        kind, priority = action
        out["todos"].append(self.todo(
            plat, m.get("title") or "", due="", course=m.get("course") or "",
            url=m.get("url") or "", priority=priority,
            note="自动识别：通知里提到「%s」但没写截止时间，建议自己确认一下"
                 % action_label(kind)))

    @staticmethod
    def msg(platform: str, title: str, *, content: str = "", url: str = "",
            time_: Any = None, course: str = "", kind: str = "notice",
            deadline: str = "", mid: str = "", read: bool | None = None) -> dict:
        t = time_
        if isinstance(t, (int, float)):
            # 兼容秒 / 毫秒时间戳
            if t > 1e11:
                t = t / 1000.0
            t = datetime.fromtimestamp(t)
        if not isinstance(t, datetime):
            # 很多平台给的是字符串，比如超星的 sendTime='2026-09-23 11:51:33'。
            # 旧代码直接落到 now()，于是 id 每次都变 —— 也是重复入库的一个来源。
            t = to_dt_local(t)
        has_time = isinstance(t, datetime)
        if not has_time:
            t = datetime.now()
        iso = t.astimezone().isoformat()
        # id 必须**跨进程稳定**。拿不到时间时就不要把「此刻」算进 id，
        # 否则同步几次就多几条重复；宁可退回 platform+title 这一稳定键。
        uid = mid or "%s-%s" % (platform, stable_id(platform, title, iso if has_time else ""))
        item = {
            "id": uid, "platform": platform, "title": (title or "").strip()[:200],
            "content": (content or "").strip()[:1200], "url": url,
            "time": iso, "course": course, "kind": kind, "deadline": deadline,
        }
        if read is None:
            read = _is_history(iso)
        if read:
            item["read"] = True
        return item

    @staticmethod
    def todo(platform: str, title: str, *, due: str = "", course: str = "",
             url: str = "", priority: int = 1, note: str = "") -> dict:
        uid = "%s-t-%s" % (platform, stable_id(platform, title, due))
        return {
            "id": uid, "title": title.strip()[:200], "due": due, "course": course,
            "url": url, "priority": priority, "note": note[:600],
            "source": platform, "done": False,
        }


_COURSE_NAME_RES = (
    re.compile(r"课程名称[:：]\s*([^\r\n]{1,40})"),
    re.compile(r"所属课程[:：]\s*([^\r\n]{1,40})"),
    re.compile(r"《([^》\r\n]{1,40})》"),
)
# 正文压缩成一行时，课程名后面可能直接跟着下一个字段，要在这里切断
_COURSE_NAME_CUT = re.compile(
    r"\s*(?:作业名称|考试名称|试卷名称|活动名称|结束时间|开始时间|答题时长|考试时间).*$")


def extract_course_name(text: str) -> str:
    """从通知正文里猜课程名。

    真实通知里长这样：「课程名称：高等数学2（经4）」，所以这一步命中率很高；
    猜不到就返回空，不要硬凑。
    """
    t = str(text or "")
    for rx in _COURSE_NAME_RES:
        m = rx.search(t)
        if m:
            name = _COURSE_NAME_CUT.sub("", m.group(1)).strip(" 　:：-—")
            if name:
                return name
    return ""


def _is_history(iso: str, now: datetime | None = None,
                days: int = HISTORY_READ_DAYS) -> bool:
    """这条通知算「历史」吗？历史通知导入时直接当已读。

    定时同步会一直翻到通知中心的最后一页，一次能带回来上百条旧通知
    （实测超星从 20 条变成 100 条）。全部算未读的话，未读角标立刻失去意义：
    23 会变成 103，而且几乎全是上学期的东西。

    旧通知照样完整留在消息中心、照样能搜索、也不影响待办识别，
    只是不再往未读角标里堆。
    """
    if days is None:
        return False
    now = now or datetime.now()
    try:
        t = datetime.fromisoformat(str(iso))
    except (TypeError, ValueError):
        return False
    if t.tzinfo is not None:
        t = t.replace(tzinfo=None)
    if now.tzinfo is not None:
        now = now.replace(tzinfo=None)
    return (now - t).days > days


def published_recently(value, now: datetime, days: int) -> bool:
    """这条通知是不是最近 `days` 天内发布的（决定要不要自动转待办）。

    留 5 分钟的前向余量，免得刚发出来的通知因为几秒的时钟误差被判成「未来」。
    """
    try:
        t = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return False
    if t.tzinfo is not None and now.tzinfo is None:
        t = t.replace(tzinfo=None)
    elif t.tzinfo is None and now.tzinfo is not None:
        t = t.replace(tzinfo=now.tzinfo)
    delta = now - t
    return -timedelta(minutes=5) <= delta <= timedelta(days=days)


def to_dt_local(value) -> datetime | None:
    """把各种时间格式尽量解析成 datetime。"""
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        v = value / 1000.0 if value > 1e11 else value
        try:
            return datetime.fromtimestamp(v)
        except Exception:
            return None
    if isinstance(value, str):
        s = value.strip()
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y/%m/%d %H:%M:%S",
                    "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d", "%Y年%m月%d日 %H:%M"):
            try:
                return datetime.strptime(s, fmt)
            except ValueError:
                continue
        try:
            return datetime.fromisoformat(s.replace("Z", "+00:00")).replace(tzinfo=None)
        except Exception:
            return None
    return None


def to_local_input(dt: datetime | None, fallback_hour: int = 23, fallback_minute: int = 59) -> str:
    """转成工作台 input[type=datetime-local] 认的 'YYYY-MM-DDTHH:mm'。"""
    if dt is None:
        return ""
    return dt.strftime("%Y-%m-%dT%H:%M")


def days_later(n: int) -> datetime:
    return datetime.now() + timedelta(days=n)
