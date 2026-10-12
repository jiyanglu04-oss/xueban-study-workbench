# -*- coding: utf-8 -*-
"""超星学习通适配器。

接口依据（社区实测，2026-08 仍有效）：
    课程列表  GET  https://mooc1-api.chaoxing.com/mycourse/backclazzdata?rss=1
    通知中心  POST https://notice.chaoxing.com/pc/notice/getNoticeList
    作业列表  GET  https://mooc1-api.chaoxing.com/work/stu-work  (返回 HTML)

注意：超星没有公开 API 文档，字段结构以实际返回为准。
本适配器对返回结构做了「通用发现」处理，并在 --debug 时把原始响应落盘到
sync/debug/chaoxing/，方便一次性确认字段。
"""
from __future__ import annotations

import json
import re

from .base import Adapter, is_browser_dead, stable_id, to_dt_local

NOTICE_URL = "https://notice.chaoxing.com/pc/notice/getNoticeList"
COURSE_URL = "https://mooc1-api.chaoxing.com/mycourse/backclazzdata?rss=1"
WORK_URL = "https://mooc1-api.chaoxing.com/work/stu-work"
WORK_API = "https://mooc1-api.chaoxing.com/work/getAllWork"

# 标题里出现这些词，基本可以认定是「要做的作业」而不是普通通知
WORK_HINT_RE = re.compile(r"(作业|测验|习题|测试|实验|报告|截止)")

# 通知列表里的一些常见字段名，做容错映射
T_TITLE = ("title", "noticeTitle", "name")
T_CONTENT = ("content", "noticeContent", "detail", "text")
T_TIME = ("createTime", "createtime", "publishTime", "insertTime", "time", "sendTime")
# 实测：通知条目里**没有** id/noticeId，真正的唯一键是 idCode（32 位大写 hex）和 uuid。
# 以前 T_ID 里只有 id/noticeId，永远取不到 → 退回 hash(title) → 每次同步都重复入库。
T_ID = ("id", "noticeId", "notice_id", "idCode", "uuid")
T_READ = ("isread", "isRead", "read", "status")


def _pick(d: dict, keys, default=None):
    for k in keys:
        if k in d and d[k] not in (None, ""):
            return d[k]
    return default


def _next_cursor(data) -> str:
    """从通知接口响应里取翻页游标；取不到就返回空串（表示没有下一页）。

    实测（2026-10-07 抓包）：游标在 `notices.lastGetId`，**不在顶层**。
    老代码只读顶层，永远取不到 → 翻页是死代码，只能拿第 1 页 20 条。
    那时 lastPage=0（总共就一页）所以看不出问题；等通知攒到 20 条以上，
    第 21 条起就永久抓不到了。所以这里顶层和嵌套一层都找。
    """
    if not isinstance(data, dict):
        return ""
    sources = [data]
    sources.extend(v for v in data.values() if isinstance(v, dict))
    for src in sources:
        for k in ("lastGetId", "lastValue", "lastId"):
            if src.get(k):
                return str(src[k])
    return ""


_WORK_PARENT = re.compile(r"[?&]courseId=(\d+).*?[?&]classId=(\d+)")

# 作业页真实结构（2026-10-07 抓包确认）：
#   <li data="...&type=work&enc_task=...">
#     <div role="option">
#       <p>C9—测验题</p><span>已完成</span><span>《高等数学2（...》</span>
#     </div>
#   </li>
_LI_BLOCK = re.compile(r"<li\b([^>]*)>(.*?)(?=<li\b|</ul>|$)", re.S)
_ITEM_TITLE = re.compile(r"<p[^>]*>\s*([^<]{1,150}?)\s*</p>")
_ITEM_STATE = re.compile(r"<span[^>]*>\s*([^<]{2,8}?)\s*</span>")
_ITEM_COURSE = re.compile(r"《([^》]{1,40})》")
# 这些状态说明学生这边已经不用再做了
DONE_STATES = ("已完成", "已提交", "已批阅", "待批阅", "已结束", "已过期")


def parse_work_list_html(html: str) -> list[dict]:
    """解析超星「作业列表」页，返回 [{title, url, status, course}]。"""
    out = []
    for m in _LI_BLOCK.finditer(html or ""):
        attrs, body = m.group(1), m.group(2)
        u = re.search(r'\bdata="([^"]+)"', attrs)
        url = u.group(1) if u else ""
        if "type=work" not in url:
            continue
        t = _ITEM_TITLE.search(body)
        if not t:
            continue
        title = re.sub(r"\s+", " ", t.group(1)).strip()
        if not title:
            continue
        status = ""
        for s in _ITEM_STATE.finditer(body):
            if s.group(1) in DONE_STATES or s.group(1) in ("未完成", "未提交", "未开始", "进行中"):
                status = s.group(1)
                break
        c = _ITEM_COURSE.search(body)
        out.append({"title": title, "url": url, "status": status,
                    "course": c.group(1).strip() if c else ""})
    return out


def _ids_from_content(content: dict) -> tuple[str, str] | None:
    """从课程 channel 里取 (courseId, classId)。

    实测（2026-10-07）这两个 id 不在 content 顶层，而在
    content.course.data[0].courseSquareUrl 的 query 里。
    """
    blobs = [str(content.get("courseSquareUrl") or "")]
    course = content.get("course")
    if isinstance(course, dict):
        for row in (course.get("data") or []):
            if isinstance(row, dict):
                blobs.append(str(row.get("courseSquareUrl") or ""))
                for k in ("courseId", "classId"):
                    if row.get(k):
                        blobs.append("?courseId=%s&classId=%s" % (row.get("courseId"), row.get("classId")))
    for b in blobs:
        m = _WORK_PARENT.search(b)
        if m:
            return m.group(1), m.group(2)
    # 兜底：顶层直接给了就用
    cid = content.get("courseId")
    clz = content.get("classId")
    if cid and clz:
        return str(cid), str(clz)
    return None


def find_dict_list(obj, need="title", depth=0):
    """在任意层级的 JSON 里找出「一批带 title 的字典」，兼容未知外层结构。"""
    if depth > 6:
        return []
    if isinstance(obj, list):
        if obj and isinstance(obj[0], dict) and any(k in obj[0] for k in ("title", "noticeTitle", "name")):
            return obj
        for it in obj:
            r = find_dict_list(it, need, depth + 1)
            if r:
                return r
    elif isinstance(obj, dict):
        # 优先看常见的 key
        for k in ("notices", "list", "data", "rows", "items", "content", "noticeList"):
            if k in obj:
                r = find_dict_list(obj[k], need, depth + 1)
                if r:
                    return r
        for v in obj.values():
            if isinstance(v, (list, dict)):
                r = find_dict_list(v, need, depth + 1)
                if r:
                    return r
    return []


class ChaoxingAdapter(Adapter):
    key = "chaoxing"
    name = "超星学习通"
    login_url = "https://passport2.chaoxing.com/login?fid=&newversion=true&refer=https%3A%2F%2Fi.chaoxing.com"
    home_url = "https://i.chaoxing.com"
    # _uid / _d 是登录后才下发的（游客也可能带 ttwid 之类，不能用作判据）
    login_cookies = ["_uid", "_d"]

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        # (courseId, classId, 课程名) 组合，作业接口要用
        self.pairs: list[tuple[str, str, str]] = []
        self._work_seen: set[str] = set()
        self.work_done = 0        # 已完成的作业数（只统计，不生成待办）

    async def fetch(self) -> dict:
        out = self.empty()
        page = await self.ctx.new_page()
        self.attach_xhr_recorder(page)
        try:
            await page.goto(self.home_url, wait_until="domcontentloaded", timeout=60000)
        except Exception as e:
            self.log("[%s] 打开首页失败：%s" % (self.name, e), level="warn")

        await self._fetch_courses(out)
        await self._fetch_notices(out)
        await self._fetch_work(page, out)

        # 记录一次登录态自检信息，方便排查
        jar = await self.cookies()
        self.log("[%s] cookie: _uid=%s fid=%s vc3=%s" % (
            self.name,
            "有" if jar.get("_uid") else "无",
            jar.get("fid", "-"),
            "有" if jar.get("vc3") else "无"), level="dim")

        if not page.is_closed():
            await page.close()
        return out

    # ---------- 课程 ----------
    async def _fetch_courses(self, out: dict):
        status, data = await self.req(COURSE_URL)
        if not isinstance(data, (dict, list)):
            self.log("[%s] 课程列表未返回 JSON（status=%s），已跳过" % (self.name, status), level="warn")
            return
        names = set()
        try:
            channels = data.get("channelList") or []
            if channels and isinstance(channels[0], dict):
                self.log("[%s] backclazzdata 字段：%s" % (self.name, sorted(channels[0].keys())), level="dim")
            for item in channels:
                content = item.get("content") or {}
                if not isinstance(content, dict):
                    continue
                cname = content.get("name") or ""
                if cname:
                    names.add(cname)
                # 作业接口要 (courseId, classId)。这两个 id 不在 content 顶层，
                # 而是藏在 content.course.data[0].courseSquareUrl 里：
                #   https://tsjy.chaoxing.com/plaza/app?courseId=266665695&classId=153555354&...
                ids = _ids_from_content(content)
                if ids:
                    self.pairs.append((ids[0], ids[1], cname))
        except Exception:
            pass
        for n in sorted(names):
            out["courses"].append({"syncKey": "chaoxing:" + n, "name": n,
                                   "platform": "chaoxing", "url": self.home_url})
        self.log("[%s] 课程 %d 门（拿到 %d 组课程 id）" % (self.name, len(names), len(self.pairs)))

    # ---------- 通知 ----------
    async def _fetch_notices(self, out: dict):
        cursor = ""
        total = 0
        dated = 0
        for page_no in range(1, 6):          # 最多翻 5 页，避免无限循环
            status, data = await self.req(
                NOTICE_URL, "POST",
                form={"type": "0", "notice_type": "0", "lastValue": cursor, "sort": "0"},
                headers={"Referer": "https://notice.chaoxing.com/pc/notice/noticeList",
                         "X-Requested-With": "XMLHttpRequest"})
            if not isinstance(data, (dict, list)):
                if page_no == 1:
                    self.log("[%s] 通知接口未返回 JSON（status=%s）；"
                             "可加 --debug 重新运行以记录真实接口" % (self.name, status), level="warn")
                break
            items = find_dict_list(data)
            if not items:
                break
            for it in items:
                if not isinstance(it, dict):
                    continue
                title = str(_pick(it, T_TITLE, "")).strip()
                if not title:
                    continue
                content = re.sub(r"<[^>]+>", "", str(_pick(it, T_CONTENT, ""))).strip()
                t = _pick(it, T_TIME)
                m = self.msg(
                    "chaoxing", title,
                    content=content,
                    url="https://notice.chaoxing.com/pc/notice/noticeList",
                    time_=t,
                    kind="notice",
                    mid="chaoxing-n-%s" % _pick(it, T_ID, stable_id("chaoxing-n", title, t)))
                # 通知正文里常带「结束时间：2026-07-03」这类信息，顺手解析成截止时间，
                # 还没过期的直接生成待办
                self.enrich_message(m, out)
                if m.get("deadline"):
                    dated += 1
                out["messages"].append(m)
                total += 1
            # 游标翻页
            nxt = _next_cursor(data)
            if not nxt or nxt == cursor:
                break
            cursor = nxt
        self.log("[%s] 通知 %d 条（其中 %d 条带截止时间）" % (self.name, total, dated))

    # ---------- 作业 ----------
    async def _fetch_work(self, page, out: dict):
        """作业 → 待办。

        超星没有公开的作业接口，所以这里不猜 URL，而是**让真实浏览器自己去加载作业页**：
        页面 JS 会向它自己的接口要列表，我们把那个响应截下来解析，再顺带从渲染后的
        DOM 里兜一层。比硬编接口路径稳得多，学校改版也不容易失效。
        """
        if not self.pairs:
            self.log("[%s] 没拿到 courseId/classId，跳过作业抓取" % self.name, level="warn")
            return

        before_seen = len(self._work_seen)
        for cid, clz, cname in self.pairs[:8]:
            url = "%s?courseId=%s&classId=%s&isOpen=0" % (WORK_URL, cid, clz)
            mark = len(self.recorded)
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=45000)
                await page.wait_for_timeout(2500)
                html = await page.content()
            except Exception as e:
                if is_browser_dead(e):
                    # 浏览器中途挂了。如果这里只是 warning 一下继续 for 循环，
                    # 后面几门课的作业就全都「抓不到」，最后一行照样打印
                    # 「作业 0 项待办」，看起来完全正常 —— 实测踩过这个坑。
                    # 直接抛出去，让 sync.py 重启浏览器把整个超星重跑一遍。
                    self.log("[%s]   作业页抓取时浏览器中断，将重启浏览器重试" % self.name, level="warn")
                    raise
                self.log("[%s]   作业页打开失败（%s）：%s" % (self.name, cname or cid, e), level="warn")
                continue
            n = self._harvest_work(html, url, out)
            n += self._harvest_recorded(out, mark, cname)
            if n:
                self.log("[%s]   %s：作业 %d 项" % (self.name, cname or cid, n), level="dim")

        added = len(self._work_seen) - before_seen
        self.log("[%s] 作业 %d 项待办（另有 %d 项已完成，不计入）"
                 % (self.name, added, self.work_done))
        if added == 0 and self.work_done == 0:
            self.log("[%s] 作业页没解析出条目；原始响应都在 sync/debug/chaoxing/ 里，"
                     "看一眼就能补上字段" % self.name, level="warn" if self.debug else "dim")

    def _harvest_recorded(self, out: dict, since: int, course: str = "") -> int:
        """从 recorder 截到的响应里找作业列表。

        require_hint=True：只认标题像作业的条目，否则课程列表、统计数字之类的
        JSON 也会被当成作业收进来。
        """
        cnt = 0
        for rec in self.recorded[since:]:
            body = rec.get("body") or ""
            if not body.lstrip().startswith(("{", "[")):
                continue
            try:
                data = json.loads(body)
            except Exception:
                continue
            cnt += self._harvest_work(data, rec.get("url") or WORK_URL, out,
                                      course=course, require_hint=True)
        return cnt

    def _harvest_work(self, data, url: str, out: dict, course: str = "",
                      require_hint: bool = False) -> int:
        """从 HTML 或 JSON 里抽作业条目。返回新增条数。"""
        cnt = 0
        if isinstance(data, str):
            if not data:
                return 0
            # 首选：按作业页真实结构解析，能拿到「已完成 / 未完成」状态
            items = parse_work_list_html(data)
            if items:
                for it in items:
                    if any(s in it["status"] for s in DONE_STATES):
                        self.work_done += 1
                        continue          # 已交的作业不该出现在待办里
                    if self._push_work(out, it["title"], it["url"] or url, "", it["course"]):
                        cnt += 1
                return cnt
            # 兜底：结构变了就退回宽匹配
            pats = (
                r'class="[^"]*(?:work|homework|job)[^"]*"[^>]*>\s*([^<]{4,120})',
                r'<a[^>]*>\s*([^<]{2,100}?(?:作业|测验|习题|测试)[^<]{0,60})\s*</a>',
                r'<div[^>]*>\s*([^<]{2,100}?(?:作业|测验|习题)\s*[:：][^<]{0,60})\s*</div>',
            )
            for p in pats:
                for t in re.findall(p, data):
                    if self._push_work(out, t, url, "", course):
                        cnt += 1
            return cnt

        items = find_dict_list(data, "title") or find_dict_list(data, "name")
        for it in items:
            if not isinstance(it, dict):
                continue
            title = str(_pick(it, ("title", "workName", "name", "jobName"), "")).strip()
            if not title:
                continue
            due_raw = _pick(it, ("endTime", "deadline", "endDate", "expireTime", "end_time"), "")
            if require_hint and not due_raw and not WORK_HINT_RE.search(title):
                continue          # 没有截止时间、标题也不像作业 → 大概率不是作业，别收
            cname = str(_pick(it, ("courseName", "coursename"), "") or course).strip()
            if self._push_work(out, title, url, due_raw, cname):
                cnt += 1
        return cnt

    def _push_work(self, out: dict, title: str, url: str, due_raw, course: str = "") -> bool:
        title = re.sub(r"\s+", " ", str(title or "")).strip(" 　:：-—")[:120]
        if not title or title in self._work_seen:
            return False
        self._work_seen.add(title)

        iso = ""
        if due_raw not in (None, ""):
            dt = to_dt_local(due_raw)
            if dt:
                iso = dt.strftime("%Y-%m-%dT%H:%M")

        m = self.msg("chaoxing", "作业 · " + title, content="来自学习通作业列表",
                     url=url, kind="homework",
                     mid="chaoxing-w-%s" % stable_id("chaoxing-w", title, course))
        if iso:
            m["deadline"] = iso
        if course:
            m["course"] = course
        # allow_todo=False：待办由本方法统一建，避免和 enrich_message 各建一条
        self.enrich_message(m, out, allow_todo=False)
        out["messages"].append(m)
        out["todos"].append(self.todo(
            "chaoxing", title, due=m.get("deadline") or "", course=course or m.get("course") or "",
            url=url, priority=1, note="来自学习通作业列表"))
        return True
