# -*- coding: utf-8 -*-
"""中国大学 MOOC (icourse163.org) 适配器。

接口依据：**实测抓包**（2026-10-08，实测抓包）。

## 课程内容页的真实地址

    https://www.icourse163.org/spoc/learn/<schoolId>-<courseId>

⚠️ **必须带 schoolId**。只写 courseId（/learn/<courseId>）或漏掉学校 ID
   一律 404。老版本注释里写「本账号没有可访问的课程内容页」，就是因为
   URL 拼错了 —— 课程其实一直好好地在。

## 实测验证过的接口

全部 POST。**参数平铺在表单里**（`termId=1476735617`），csrfKey 放 URL：

    courseBean.getLastLearnCourse.rpc              {}          → 课程列表
        result[].mocCourseBaseCardVo =
            {id, name, schoolId, schoolName, currentTermId,
             startTime, endTime, teacherName, mode, ...}

    courseBean.getLastLearnedMocTermDto.rpc        {termId}    → 课程结构
        result.mocTermDto.chapters[].lessons[]     ← 每讲（viewStatus 表是否看过）
        result.mocTermDto.chapters[].quizs[]       ← 章节测验
        result.mocTermDto.chapters[].homeworks[]   ← 章节作业
        result.mocTermDto.exams[]                  ← 期末考试（带 deadline）

    mocCourseV2RpcBean.getMemberLearningRate.rpc   {termId}    → 学习进度
        result = {lessonLearned: 0, lessonsCount: 59}

DWR 接口（返回的是 JS 片段而不是 JSON，要另解析）：

    POST /dwr/call/plaincall/CourseBean.getAllAnnouncementByTerm.dwr
        c0-param0=number:<termId>   c0-param1=number:1

## ⚠️ 老实现的两个硬伤（这次修掉）

1. **参数格式错了**。老代码把参数包成 `form={"bizType":"json","json":"{\\"termId\\":…}"}`，
   服务端直接回 `-1007 不含有该参数 :bizType`。正确做法是**平铺**：
   表单里就是 `termId=1476735617`。所以以前连课程结构都拿不到。

2. **只调了 getLastLearnCourse**，拿到一个课程名就收工了。
   于是工作台里那门课永远「只有名字、点进去什么都没有」——
   不是抓取失败，是**根本没去读**。
"""
from __future__ import annotations

import asyncio
import json
import re
import time
from datetime import datetime
from urllib.parse import quote

from .base import Adapter, stable_id

BASE = "https://www.icourse163.org"
RPC = BASE + "/web/j/"

_TAG_RE = re.compile(r"<[^>]+>")


def _plain(s) -> str:
    return _TAG_RE.sub("", str(s or "")).strip()


def _iso(ms) -> str:
    """毫秒时间戳 → 本地 ISO 字符串（前端 new Date() 直接能读）。"""
    try:
        v = int(ms) / 1000
    except (TypeError, ValueError):
        return ""
    if v <= 0:
        return ""
    try:
        return datetime.fromtimestamp(v).isoformat(timespec="minutes")
    except (OverflowError, OSError, ValueError):
        return ""


def learn_url(school_id, course_id) -> str:
    """课程内容页。必须带学校 ID，否则 404。"""
    course_id = str(course_id or "").strip()
    if not course_id:
        return ""
    school_id = str(school_id or "").strip()
    if school_id:
        return "%s/spoc/learn/%s-%s" % (BASE, school_id, course_id)
    return "%s/course/%s" % (BASE, course_id)


# ==================== 响应解析 ====================

def parse_course_list(data) -> list[dict]:
    """从 getLastLearnCourse 响应里取出课程。

    响应形状（实测）：

        {"code":0,"result":[{"id":1471660166,"type":306,
          "mocCourseBaseCardVo":{"id":1471660166,"name":"创业基础：原理与训练",
             "schoolId":1001195001,"schoolName":"示例大学",
             "currentTermId":1476735617,"teacherName":"王勇",
             "startTime":…,"endTime":…}}]}

    注意课程名藏在 `mocCourseBaseCardVo` 里，**顶层元素没有 name 字段** ——
    所以这里不能用 find_dict_list（它只会返回顶层就带 title/name 的列表）。
    """
    if not isinstance(data, dict):
        return []
    items = data.get("result")
    if not isinstance(items, list):
        inner = data.get("data")
        items = inner.get("result") if isinstance(inner, dict) else []
    out = []
    for it in items if isinstance(items, list) else []:
        if not isinstance(it, dict):
            continue
        card = it.get("mocCourseBaseCardVo")
        card = card if isinstance(card, dict) else {}
        name = str(card.get("name") or it.get("name") or "").strip()
        if not name:
            continue
        out.append({
            "name": name,
            "courseId": card.get("id") or it.get("id") or "",
            "schoolId": card.get("schoolId") or "",
            "schoolName": card.get("schoolName") or "",
            "termId": card.get("currentTermId") or "",
            "teacher": card.get("teacherName") or "",
            "startTime": card.get("startTime") or 0,
            "endTime": card.get("endTime") or 0,
        })
    return out


def parse_term_detail(data) -> dict:
    """从 getLastLearnedMocTermDto 响应里解析出课程结构。

    返回 {termId, startAt, endAt, chapters[], quizzes[], homeworks[], exams[]}。
    chapters 里每项带 lessons/done，用于算「这一章看了几讲」。
    """
    if not isinstance(data, dict):
        return {}
    result = data.get("result")
    term = result.get("mocTermDto") if isinstance(result, dict) else None
    if not isinstance(term, dict):
        return {}

    chapters, quizzes, homeworks = [], [], []
    for ch in term.get("chapters") or []:
        if not isinstance(ch, dict):
            continue
        cname = str(ch.get("name") or "").strip()
        lessons = [x for x in (ch.get("lessons") or []) if isinstance(x, dict)]
        ch_quiz = [x for x in (ch.get("quizs") or [])
                   if isinstance(x, dict) and str(x.get("name") or "").strip()]
        ch_hw = [x for x in (ch.get("homeworks") or [])
                 if isinstance(x, dict) and str(x.get("name") or "").strip()]
        # MOOC 会把「期末考试」也塞成一条 chapter（它本身没有任何课时）。
        # 那种空章在章节列表里显示成「《创业基础》考试 · 0 讲」很怪，
        # 而考试本身已经由 term.exams 单独给出了，所以这里跳过。
        if not (lessons or ch_quiz or ch_hw):
            continue
        done = sum(1 for x in lessons if x.get("viewStatus"))
        chapters.append({"name": cname, "lessons": len(lessons), "done": done})
        for q in ch_quiz:
            quizzes.append({"name": str(q["name"]).strip(), "chapter": cname,
                            "due": _iso(q.get("deadline"))})
        for h in ch_hw:
            homeworks.append({"name": str(h["name"]).strip(), "chapter": cname,
                              "due": _iso(h.get("deadline"))})

    exams = []
    for e in term.get("exams") or []:
        if isinstance(e, dict) and str(e.get("name") or "").strip():
            exams.append({
                "name": str(e["name"]).strip(),
                "due": _iso(e.get("deadline")),
                "totalScore": e.get("totalScore"),
                "userScore": e.get("userScore"),
                "description": _plain(e.get("description"))[:300],
            })

    return {
        "termId": term.get("id") or "",
        "courseId": term.get("courseId") or "",
        "startAt": _iso(term.get("startTime")),
        "endAt": _iso(term.get("endTime")),
        "chapters": chapters,
        "quizzes": quizzes,
        "homeworks": homeworks,
        "exams": exams,
    }


def parse_learning_rate(data) -> dict:
    """学习进度：{lessonLearned, lessonsCount} → {"done":0,"total":59}。"""
    result = data.get("result") if isinstance(data, dict) else None
    if not isinstance(result, dict):
        return {"done": 0, "total": 0}
    try:
        done = int(result.get("lessonLearned") or 0)
    except (TypeError, ValueError):
        done = 0
    try:
        total = int(result.get("lessonsCount") or 0)
    except (TypeError, ValueError):
        total = 0
    return {"done": done, "total": total}


def online_course_todo(course: dict, detail: dict, url: str,
                       now: datetime | None = None) -> dict:
    """把 MOOC 在线课程表示成待办，而不是课表里的课程。

    MOOC 课程没有固定上课时段，真正要做的是持续在线学习。待办 id 只跟课程/
    学期有关，不把进度写进 id，保证每次同步更新同一条记录而不是不断新增。
    """
    name = str(course.get("name") or "中国大学 MOOC").strip()
    progress = detail.get("progress") if isinstance(detail, dict) else {}
    progress = progress if isinstance(progress, dict) else {}
    try:
        done = int(progress.get("done") or 0)
    except (TypeError, ValueError):
        done = 0
    try:
        total = int(progress.get("total") or 0)
    except (TypeError, ValueError):
        total = 0

    due = str(detail.get("endAt") or "") if isinstance(detail, dict) else ""
    if due:
        try:
            deadline = datetime.fromisoformat(due)
            if deadline <= (now or datetime.now()):
                due = ""
        except ValueError:
            due = ""

    note_parts = ["中国大学 MOOC 在线刷课"]
    if total:
        note_parts.append("当前进度 %d/%d 讲" % (done, total))
    chapters = detail.get("chapters") if isinstance(detail, dict) else []
    if isinstance(chapters, list) and chapters:
        note_parts.append("共 %d 章" % len(chapters))

    item = Adapter.todo(
        "icourse163", "在线学习《%s》" % name, due=due, course="", url=url,
        priority=1, note=" · ".join(note_parts))
    item["id"] = "icourse163-course-" + stable_id(
        course.get("courseId") or name,
        course.get("termId") or (detail.get("termId") if isinstance(detail, dict) else ""))
    return item


def online_course_message(course: dict, detail: dict, url: str) -> dict:
    """生成一条可反复更新的 MOOC 学习进度通知。"""
    name = str(course.get("name") or "中国大学 MOOC").strip()
    progress = detail.get("progress") if isinstance(detail, dict) else {}
    progress = progress if isinstance(progress, dict) else {}
    try:
        done = int(progress.get("done") or 0)
    except (TypeError, ValueError):
        done = 0
    try:
        total = int(progress.get("total") or 0)
    except (TypeError, ValueError):
        total = 0
    chapters = detail.get("chapters") if isinstance(detail, dict) else []
    chapter_count = len(chapters) if isinstance(chapters, list) else 0

    if total:
        content = "在线刷课进度：%d/%d 讲" % (done, total)
    else:
        content = "这是一门需要在线完成的 MOOC 课程"
    if chapter_count:
        content += "，共 %d 章" % chapter_count
    content += "。点击进入中国大学 MOOC 继续学习。"

    item = Adapter.msg(
        "icourse163", "在线课程进度：《%s》" % name,
        content=content, url=url, time_=detail.get("fetchedAt") if detail else None,
        course="", kind="notice")
    item["id"] = "icourse163-course-update-" + stable_id(
        course.get("courseId") or name,
        course.get("termId") or (detail.get("termId") if isinstance(detail, dict) else ""))
    return item


# DWR 的返回长这样（注意：对象键**没有引号**，日期是 new Date(ms)）：
#   //#DWR-INSERT
#   //#DWR-REPLY
#   dwr.engine._remoteHandleCallback('1791445681593','0',[{id:1,title:"公告",…}]);
_DWR_CB_RE = re.compile(r"_remoteHandleCallback\((.*)\)\s*;?\s*$", re.S)


def _js_to_py(raw: str):
    """把 DWR 的 JS 字面量降级成 Python 对象；读不懂返回 None。"""
    if not isinstance(raw, str):
        return None
    try:
        return json.loads(raw)
    except Exception:
        pass
    s = re.sub(r"new\s+Date\((\d+)\)", r"\1", raw)
    s = re.sub(r"([{,]\s*)([A-Za-z_$][\w$]*)\s*:", r'\1"\2":', s)
    try:
        return json.loads(s)
    except Exception:
        return None


def parse_dwr_result(text):
    """从 DWR 响应文本里取出回调参数（通常是个数组）。"""
    if not isinstance(text, str) or "remoteHandleCallback" not in text:
        return None
    m = _DWR_CB_RE.search(text.strip())
    if not m:
        return None
    payload = m.group(1)
    # 去掉开头的 'batchId','0', 两个参数（它们本身不含逗号，所以直接切两刀）
    parts = payload.split(",", 2)
    if len(parts) < 3:
        return None
    obj = _js_to_py(parts[2].strip().rstrip(");").strip())
    return obj


class Mooc163Adapter(Adapter):
    key = "icourse163"
    name = "中国大学 MOOC"
    login_url = "https://www.icourse163.org/"
    # 首页会带上登录态。不要用 /member/learn.htm（无权访问），
    # 也不要用 /spoc/schoolcloud/index.htm（那页只发学校统计接口，一个课程接口都不发）。
    home_url = "https://www.icourse163.org/"

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self._page = None
        self._csrf = ""
        self._courses: list[dict] = []
        # 每次同步只取一次当前时间，避免同一批数据里时间基准抖动
        self._now = datetime.now()

    # ---------- 登录态 ----------
    #
    # 这里必须用「功能性检查」，不能看 cookie。原因实测过：
    #   * STUDY_SESS / STUDY_INFO 是**会话级** cookie，浏览器一关就没了，
    #     永远不会写进持久化 profile —— 所以每次冷启动都「看起来没登录」，
    #     而实际上登录得好好的。
    #   * 反过来，页面一加载就会下发 STUDY_SESS（游客也有），
    #     所以「看 cookie」还会**误报登录成功**。
    # 结论：能读到课程 = 登录着。这是唯一可靠的判据。

    async def _open_home(self) -> str:
        if self._page is None or self._page.is_closed():
            self._page = await self.ctx.new_page()
            self.attach_xhr_recorder(self._page)
            try:
                await self._page.goto(self.home_url, wait_until="domcontentloaded",
                                      timeout=60000)
            except Exception as e:
                self.log("[%s] 打开首页失败：%s" % (self.name, e), level="warn")
        jar = await self.cookies([BASE])
        self._csrf = jar.get("NTESSTUDYSI", "")
        if not self._csrf:
            self.log("[%s] 未找到 NTESSTUDYSI，接口调用可能被拒" % self.name, level="warn")
        return self._csrf

    async def probe_courses(self) -> list[dict]:
        """能拿到课程就说明登录着；顺带把结果缓存下来给 fetch 用。"""
        if not await self._open_home():
            return []
        self._courses = await self._fetch_courses(self._csrf)
        return self._courses

    async def is_logged_in(self) -> bool:
        try:
            return bool(await self.probe_courses())
        except Exception as e:
            self.log("[%s] 登录态探测失败：%r" % (self.name, e), level="warn")
            return False

    async def ensure_login(self, force: bool = False, timeout: int = 360) -> bool:
        if not force and await self.probe_courses():
            self.log("[%s] 登录态有效（已能读到课程），跳过扫码" % self.name)
            return True

        if not self.interactive:
            self.log("[%s] 登录态已过期。定时同步不会弹窗等扫码，本次跳过 —— "
                     "请手动双击一次「一键同步数据.bat」重新登录。" % self.name, level="warn")
            return False

        page = await self.ctx.new_page()
        await page.goto(self.login_url, wait_until="domcontentloaded", timeout=60000)
        self.log("")
        self.log("=" * 62)
        self.log("【%s】需要在弹出的浏览器窗口里登录一次" % self.name)
        self.log("  登录成功后会自动继续，不需要你按任何键，最多等 %d 秒" % timeout)
        self.log("=" * 62)

        started = time.time()
        while time.time() - started < timeout:
            await asyncio.sleep(3)
            if page.is_closed():
                break
            try:
                await page.bring_to_front()
            except Exception:
                pass
            if await self.probe_courses():
                self.log("[%s] 登录成功 ✓" % self.name)
                try:
                    await page.close()
                except Exception:
                    pass
                return True
        self.log("[%s] 登录超时或未检测到登录态 ✗" % self.name, level="warn")
        if not page.is_closed():
            await page.close()
        return False

    # ---------- 抓取 ----------

    async def fetch(self) -> dict:
        out = self.empty()
        csrf = await self._open_home()
        courses = self._courses or await self._fetch_courses(csrf)
        if not courses:
            self.log("[%s] 未取到课程列表；账号可能没在 MOOC 上报过课" % self.name, level="warn")
            return out

        self.log("[%s] 课程 %d 门" % (self.name, len(courses)))
        notice_count = 0
        for c in courses:
            nm = c["name"]
            school_id, course_id, term_id = c.get("schoolId"), c.get("courseId"), c.get("termId")
            url = learn_url(school_id, course_id)
            detail = await self._fetch_detail(c, term_id, csrf)
            if detail:
                p = detail.get("progress") or {}
                self.log("[%s]   %s：进度 %s/%s · %d 章 · %d 个章节测验 · %d 场考试"
                         % (self.name, nm, p.get("done", 0), p.get("total", 0),
                            len(detail.get("chapters") or []),
                            len(detail.get("quizzes") or []),
                            len(detail.get("exams") or [])),
                         level="dim")
            elif url:
                self.log("[%s]   %s：课程结构没取到（接口返回空）" % (self.name, nm), level="dim")
            # MOOC 没有固定课表时段，本质是需要持续完成的在线学习任务。
            # 因此只生成待办，不把它混进「课程管理」里的课程池。
            out["todos"].append(online_course_todo(
                c, detail or {}, url or self.home_url, now=self._now))
            out["messages"].append(online_course_message(
                c, detail or {}, url or self.home_url))

            notice_count += await self._fetch_notices(term_id, nm, url, csrf, out)

        if not notice_count:
            self.log("[%s] 这门课目前没有平台公告（DWR 接口返回空，不是抓取失败）"
                     % self.name, level="dim")

        # 页面留着不关：本次会话后面还要用同一套 cookie / csrf，
        # 整个浏览器上下文由 sync.py 在结束时统一关掉。
        return out

    async def _fetch_detail(self, course: dict, term_id, csrf: str) -> dict:
        """课程结构 + 学习进度。

        这两个接口都不需要真的打开课程页 —— 用 context.request 直接调，
        省掉一次页面加载（约 5~8 秒）。
        """
        if not term_id:
            return {}
        _, td = await self._rpc("courseBean.getLastLearnedMocTermDto",
                                {"termId": term_id}, csrf)
        detail = parse_term_detail(td)
        if not detail:
            return {}

        _, lr = await self._rpc("mocCourseV2RpcBean.getMemberLearningRate",
                                {"termId": term_id}, csrf)
        detail["progress"] = parse_learning_rate(lr)
        detail["school"] = course.get("schoolName") or ""
        detail["fetchedAt"] = self._now.isoformat(timespec="minutes")
        return detail

    async def _rpc(self, method: str, payload: dict | None = None, csrf: str = ""):
        """调 .rpc 接口。

        ⚠️ 参数必须**平铺**在表单里。包成 `json={"termId":…}` 会被服务端
           判成「缺少 bizType 参数」直接拒掉（-1007）—— 这是老实现拿不到
           课程结构的根本原因。
        """
        url = "%s%s.rpc?csrfKey=%s" % (RPC, method, quote(csrf or ""))
        form = {}
        for k, v in (payload or {}).items():
            form[k] = v if isinstance(v, str) else str(v)
        status, data = await self.req(
            url, "POST", form=form,
            headers={"Referer": BASE + "/",
                     "Content-Type": "application/x-www-form-urlencoded"})
        return status, data

    async def _dwr(self, script: str, method: str, params: list[str], csrf: str = ""):
        """调 DWR 接口。返回原始文本（JS 片段，需要另外解析）。"""
        lines = [
            "callCount=1",
            "scriptSessionId=${scriptSessionId}190",
            "httpSessionId=%s" % (csrf or ""),
            "c0-scriptName=%s" % script,
            "c0-methodName=%s" % method,
            "c0-id=0",
        ]
        for i, p in enumerate(params):
            lines.append("c0-param%d=%s" % (i, p))
        lines.append("batchId=%d" % int(time.time() * 1000))
        url = "%s/dwr/call/plaincall/%s.%s.dwr" % (BASE, script, method)
        status, data = await self.req(
            url, "POST", headers={"Referer": BASE + "/",
                                  "Content-Type": "text/plain"},
            json_body="\n".join(lines))
        return data if isinstance(data, str) else ""

    async def _fetch_courses(self, csrf: str):
        """课程列表 —— 走实测验证过的接口。

        getLastLearnCourse 是个很轻的接口：表单为空，csrfKey 放 URL 上，
        返回「最近在学的课程」。对只有一门 SPOC 的学生来说它就等于课程列表。
        """
        _, data = await self._rpc("courseBean.getLastLearnCourse", {}, csrf)
        courses = parse_course_list(data)
        if courses:
            return courses
        # 拿不到就退回老的两条猜测（历史上从没成功过，留着只是兜底）
        for method, payload in (
            ("courseBean.getCoursePanelList", {"pageIndex": 1, "pageSize": 50}),
            ("courseBean.getLastLearnedMocTermDto", {}),
        ):
            _, data = await self._rpc(method, payload, csrf)
            courses = parse_course_list(data)
            if courses:
                return courses
        return []

    async def _fetch_notices(self, term_id, course_name: str, course_url: str,
                             csrf: str, out: dict) -> int:
        """课程公告 —— 走 DWR。

        实测：本课当前没有公告（接口返回 []）。空就是空，不编数据出来。
        """
        if not term_id:
            return 0
        text = await self._dwr("CourseBean", "getAllAnnouncementByTerm",
                               ["number:%s" % term_id, "number:1"], csrf)
        items = parse_dwr_result(text)
        if not isinstance(items, list):
            return 0
        n = 0
        for it in items:
            if not isinstance(it, dict):
                continue
            title = str(it.get("title") or it.get("name") or "").strip()
            if not title:
                continue
            t = it.get("releaseTime") or it.get("publishTime") or it.get("gmtCreate")
            m = self.msg(
                "icourse163", title,
                content=_plain(it.get("content") or it.get("description") or ""),
                url=course_url or self.home_url, time_=t, course=course_name,
                kind="notice",
                mid="icourse163-%s-%s" % (term_id, it.get("id")
                                          or stable_id("icourse163", term_id, title, t)))
            self.enrich_message(m, out)
            out["messages"].append(m)
            n += 1
        if n:
            self.log("[%s]   %s：公告 %d 条" % (self.name, course_name, n), level="dim")
        return n
