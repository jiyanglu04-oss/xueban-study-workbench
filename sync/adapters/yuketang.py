# -*- coding: utf-8 -*-
"""雨课堂适配器。

接口依据（社区实测）：
    课程列表  GET {host}/v2/api/web/courses/list?identity=2
    活动日志  GET {host}/v2/api/web/logs/learn/{classroom_id}?actype=-1&page=0&offset=500&sort=-1
              Type=6 是公告，14 是教学活动

host 按学校不同，常见 www / changjiang / pro / huanghe.yuketang.cn，脚本会自动探测。
"""
from __future__ import annotations

import re

from .base import Adapter, stable_id
from .chaoxing import find_dict_list

HOSTS = ["https://www.yuketang.cn", "https://changjiang.yuketang.cn",
         "https://pro.yuketang.cn", "https://huanghe.yuketang.cn"]

# 实测（2026-10-07，www.yuketang.cn）：
#   type 14 = 上课 / 课件活动
#   type  9 = 课程公告   ← 公告是 9，不是 6！之前只认 6，所以一条公告都抓不到
#   type 4/5 = 其他课程活动
NOTICE_TYPES = {"9"}
WORK_HINT_RE = re.compile(r"(作业|测验|测试|考试|实验|报告|习题|截止)")


def _cid(d: dict):
    for k in ("classroom_id", "classroomId", "id", "course_id"):
        if d.get(k):
            return str(d[k])
    return ""


def _cname(d: dict):
    for k in ("name", "course_name", "courseName", "title"):
        if d.get(k):
            return str(d[k]).strip()
    return ""


class YuketangAdapter(Adapter):
    key = "yuketang"
    name = "雨课堂"
    login_url = "https://www.yuketang.cn/web"
    home_url = "https://www.yuketang.cn/web"
    login_cookies = ["sessionid"]
    throttle = 1.2

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.host = HOSTS[0]
        # 见到过的活动类型及条数，最后一并打印 —— 这是判断「公告到底是哪个 Type」的依据
        self.type_dist: dict[str, int] = {}
        self.sample_keys: list[str] = []

    async def fetch(self) -> dict:
        out = self.empty()
        page = await self.ctx.new_page()
        self.attach_xhr_recorder(page)
        try:
            await page.goto(self.home_url, wait_until="domcontentloaded", timeout=60000)
        except Exception as e:
            self.log("[%s] 打开首页失败：%s" % (self.name, e), level="warn")

        courses = await self._fetch_courses()
        if courses is None:
            self.log("[%s] 未取到课程列表；若登录正常，可加 --debug 重新运行以记录真实接口" % self.name,
                     level="warn")
            if not page.is_closed():
                await page.close()
            return out

        for c in courses:
            name, cid = _cname(c), _cid(c)
            if not name:
                continue
            out["courses"].append({"syncKey": "yuketang:" + (cid or name), "name": name,
                                   "platform": "yuketang", "url": self.home_url})
        self.log("[%s] 课程 %d 门" % (self.name, len(out["courses"])))

        for c in courses[:12]:                     # 最多遍历 12 门课
            cid = _cid(c)
            if not cid:
                continue
            await self._fetch_logs(cid, _cname(c), out)

        if self.type_dist:
            self.log("[%s] 活动 Type 分布：%s" % (
                self.name, ", ".join("%s×%d" % (k, v) for k, v in
                                     sorted(self.type_dist.items(), key=lambda x: -x[1])[:10])),
                level="dim")
        if self.sample_keys:
            self.log("[%s] 活动字段：%s" % (self.name, ", ".join(self.sample_keys[:18])), level="dim")

        if not page.is_closed():
            await page.close()
        return out

    async def _fetch_courses(self):
        for host in HOSTS:
            status, data = await self.req(host + "/v2/api/web/courses/list?identity=2")
            if isinstance(data, (dict, list)):
                items = []
                if isinstance(data, dict):
                    d = data.get("data")
                    if isinstance(d, dict):
                        for k in ("course_list", "courses", "list"):
                            if isinstance(d.get(k), list):
                                items = d[k]
                                break
                    elif isinstance(d, list):
                        items = d
                if not items:
                    items = find_dict_list(data, "name")
                items = [x for x in items if isinstance(x, dict) and _cname(x)]
                if items:
                    self.host = host
                    self.log("[%s] 学校域名：%s" % (self.name, host))
                    return items
        return None

    async def _fetch_logs(self, cid: str, cname: str, out: dict):
        url = ("%s/v2/api/web/logs/learn/%s?actype=-1&page=0&offset=500&sort=-1"
               % (self.host, cid))
        status, data = await self.req(url)
        if not isinstance(data, (dict, list)):
            return
        items = data.get("data") if isinstance(data, dict) else data
        if isinstance(items, dict):
            for k in ("activities", "list", "logs"):
                if isinstance(items.get(k), list):
                    items = items[k]
                    break
        if not isinstance(items, list):
            return
        if items and isinstance(items[0], dict) and not self.sample_keys:
            self.sample_keys = sorted(items[0].keys())

        cnt = 0
        for it in items:
            if not isinstance(it, dict):
                continue
            typ = it.get("Type")
            if typ is None:
                typ = it.get("type")
            self.type_dist[str(typ)] = self.type_dist.get(str(typ), 0) + 1

            title = str(it.get("Title") or it.get("title") or "").strip()
            if not title:
                continue
            body = re.sub(r"<[^>]+>", "", str(it.get("Content") or it.get("content") or "")).strip()
            blob = title + " " + body

            # 公告是 type 9（实测确认）。旧代码只认 type 6，等于一条公告都进不来。
            # 另外标题/正文里写着作业、测验、考试、截止的，也一并收进来。
            is_notice = str(typ) in NOTICE_TYPES
            is_work = bool(WORK_HINT_RE.search(blob))
            if not (is_notice or is_work):
                continue

            kind = "notice"
            if re.search(r"(考试|测验|测试)", title):
                kind = "exam"
            elif re.search(r"作业|习题|实验|报告", title):
                kind = "homework"

            # 实测字段是 snake_case 的 create_time（毫秒字符串）。
            # 旧代码只找 CreateTime/createTime/time，全部落空 → 每条消息的时间都变成
            # 「本次同步的时刻」，时间线全是错的。
            t = (it.get("CreateTime") or it.get("createTime") or it.get("create_time")
                 or it.get("publishTime") or it.get("publish_time")
                 or it.get("time") or it.get("sendTime") or it.get("send_time"))
            m = self.msg(
                "yuketang", title, content=body, url=self.home_url, time_=t,
                course=cname, kind=kind,
                mid="yuketang-%s-%s" % (cid, it.get("Id") or it.get("id")
                                        or stable_id("yuketang", cid, title, t)))
            self.enrich_message(m, out)
            out["messages"].append(m)
            cnt += 1
        if cnt:
            self.log("[%s]   %s：%d 条" % (self.name, cname, cnt), level="dim")
