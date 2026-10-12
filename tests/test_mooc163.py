# -*- coding: utf-8 -*-
"""中国大学 MOOC 适配器的解析测试。

这些样例全部来自 **2026-10-08 的真实抓包**，
不是照文档编的。之所以要写这么细，是因为这个适配器之前踩过两个坑：

  1. .rpc 接口的参数必须**平铺**在表单里，包成 `json={...}` 会拿到
     `-1007 不含有该参数 :bizType`。
  2. 课程内容页是 `/spoc/learn/<schoolId>-<courseId>`，**漏掉 schoolId 就 404**。
     老注释因此断言「本账号没有可访问的课程内容页」，于是这门课在工作台里
     永远只有一个名字、点进去什么都没有。

所以下面既测解析，也把这两个 URL / 结构约定钉死。
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SYNC = ROOT / "sync"
sys.path.insert(0, str(SYNC))

import adapters.icourse163 as m  # noqa: E402


COURSE_LIST = {
    "code": 0,
    "result": [{
        "id": 1471660166,
        "type": 306,
        "mocCourseBaseCardVo": {
            "id": 1471660166,
            "name": "创业基础：原理与训练",
            "teacherName": "王勇",
            "schoolId": 1001195001,
            "schoolName": "示例大学",
            "schoolSN": "JNU",
            "currentTermId": 1476735617,
            "startTime": 1773014400000,
            "endTime": 1778254200000,
        },
    }],
}

TERM_DTO = {
    "code": 0,
    "result": {
        "lastLearnUnitId": None,
        "mocTermDto": {
            "id": 1476735617,
            "courseId": 1471660166,
            "courseName": "创业基础：原理与训练",
            "startTime": 1773014400000,
            "endTime": 1778254200000,
            "chapters": [
                {
                    "id": 1241021962,
                    "name": "第一章 创业环境",
                    "lessons": [
                        {"id": 1, "name": "第01讲", "viewStatus": 1},
                        {"id": 2, "name": "第02讲", "viewStatus": 0},
                        {"id": 3, "name": "第03讲", "viewStatus": 0},
                    ],
                    "quizs": [{"id": 10, "name": "第一章 创业环境测试题",
                               "deadline": None}],
                    "homeworks": [],
                },
                {
                    "id": 1241021963,
                    "name": "第二章 创业者",
                    "lessons": [{"id": 4, "name": "第05讲", "viewStatus": 0}],
                    "quizs": [{"id": 11, "name": "第二章 创业者测试题",
                               "deadline": 1778254200000}],
                    "homeworks": [{"id": 12, "name": "创业计划书草稿",
                                   "deadline": None}],
                },
                {
                    # 真实数据里 MOOC 会把期末考试也塞成一条 chapter，
                    # 它没有任何课时/测验/作业 —— 这种空章不该出现在章节列表。
                    "id": 1241021974,
                    "name": "《创业基础》考试",
                    "contentType": 4,
                    "lessons": [],
                    "quizs": [],
                    "homeworks": [],
                    "exam": {"id": 1223002084, "name": "《创业基础》考试"},
                },
            ],
            "exams": [{
                "id": 1223002084,
                "name": "《创业基础》考试",
                "deadline": 1778254200000,
                "totalScore": 100.0,
                "userScore": None,
                "description": "<p>本次考核总分<b>100分</b></p>",
            }],
        },
    },
}


class LearnUrlTest(unittest.TestCase):
    def test_带学校id的spoc地址(self):
        self.assertEqual(
            m.learn_url(1001195001, 1471660166),
            "https://www.icourse163.org/spoc/learn/1001195001-1471660166")

    def test_没有学校id时退回普通课程页(self):
        """漏 schoolId 会 404 —— 至少别拼出一个带 '-?' 的怪地址。"""
        self.assertEqual(m.learn_url("", "1471660166"),
                         "https://www.icourse163.org/course/1471660166")

    def test_没有课程id时返回空(self):
        self.assertEqual(m.learn_url("1001195001", ""), "")


class ParseCourseListTest(unittest.TestCase):
    def test_识别真实响应(self):
        got = m.parse_course_list(COURSE_LIST)
        self.assertEqual(len(got), 1)
        c = got[0]
        self.assertEqual(c["name"], "创业基础：原理与训练")
        self.assertEqual(c["courseId"], 1471660166)
        self.assertEqual(c["schoolId"], 1001195001)
        self.assertEqual(c["termId"], 1476735617)   # 必须取 currentTermId
        self.assertEqual(c["teacher"], "王勇")
        self.assertEqual(c["schoolName"], "示例大学")

    def test_课程名藏在子字典里_所以不能用通用列表扫描(self):
        """顶层元素没有 name 字段，只有 mocCourseBaseCardVo 里有。"""
        self.assertNotIn("name", COURSE_LIST["result"][0])
        self.assertEqual(len(m.parse_course_list(COURSE_LIST)), 1)

    def test_没有课程名的条目要丢掉(self):
        data = {"result": [{"id": 1, "mocCourseBaseCardVo": {"id": 1}}]}
        self.assertEqual(m.parse_course_list(data), [])

    def test_畸形输入不崩(self):
        for bad in (None, [], "x", {}, {"result": "x"}, {"result": [None, 1]}):
            with self.subTest(bad=bad):
                self.assertEqual(m.parse_course_list(bad), [])


class ParseTermDetailTest(unittest.TestCase):
    def setUp(self) -> None:
        self.d = m.parse_term_detail(TERM_DTO)

    def test_学期与课程id(self):
        self.assertEqual(self.d["termId"], 1476735617)
        self.assertEqual(self.d["courseId"], 1471660166)
        self.assertEqual(self.d["startAt"], "2026-03-09T08:00")
        self.assertEqual(self.d["endAt"], "2026-05-08T23:30")

    def test_空的考试章不进章节列表(self):
        """考试章没有任何课时，列成「《创业基础》考试 · 0 讲」很怪；
        考试本身在 exams 里有，所以章节里跳过它。"""
        names = [ch["name"] for ch in self.d["chapters"]]
        self.assertNotIn("《创业基础》考试", names)
        self.assertEqual(len(self.d["chapters"]), 2)
        self.assertEqual(len(self.d["exams"]), 1)      # 但考试还得在

    def test_章节与每章的已看讲数(self):
        self.assertEqual(len(self.d["chapters"]), 2)
        ch1 = self.d["chapters"][0]
        self.assertEqual(ch1["name"], "第一章 创业环境")
        self.assertEqual(ch1["lessons"], 3)
        self.assertEqual(ch1["done"], 1)      # 只看了第01讲

    def test_章节测验按章归属(self):
        q = self.d["quizzes"]
        self.assertEqual(len(q), 2)
        self.assertEqual(q[0]["name"], "第一章 创业环境测试题")
        self.assertEqual(q[0]["chapter"], "第一章 创业环境")
        self.assertEqual(q[0]["due"], "")                  # deadline 为 null
        self.assertTrue(q[1]["due"].startswith("2026-05-08"))

    def test_作业也收进来(self):
        self.assertEqual(len(self.d["homeworks"]), 1)
        self.assertEqual(self.d["homeworks"][0]["name"], "创业计划书草稿")

    def test_考试带截止时间与满分_描述去html(self):
        self.assertEqual(len(self.d["exams"]), 1)
        e = self.d["exams"][0]
        self.assertEqual(e["name"], "《创业基础》考试")
        self.assertTrue(e["due"].startswith("2026-05-08"))
        self.assertEqual(e["totalScore"], 100.0)
        self.assertNotIn("<b>", e["description"])
        self.assertIn("100分", e["description"])

    def test_畸形输入不崩(self):
        for bad in (None, [], {}, {"result": None}, {"result": {"mocTermDto": "x"}}):
            with self.subTest(bad=bad):
                self.assertEqual(m.parse_term_detail(bad), {})


class ParseLearningRateTest(unittest.TestCase):
    def test_真实响应(self):
        got = m.parse_learning_rate(
            {"code": 0, "result": {"lessonLearned": 0, "lessonsCount": 59}})
        self.assertEqual(got, {"done": 0, "total": 59})

    def test_异常输入归零而不是崩(self):
        for bad in (None, {}, {"result": None}, {"result": {"lessonsCount": "x"}}):
            with self.subTest(bad=bad):
                got = m.parse_learning_rate(bad)
                self.assertEqual(got["done"], 0)
                self.assertIsInstance(got["total"], int)


class OnlineCourseTodoTest(unittest.TestCase):
    def test_在线课程生成待办而不是依赖课程卡(self):
        course = m.parse_course_list(COURSE_LIST)[0]
        detail = m.parse_term_detail(TERM_DTO)
        detail["progress"] = {"done": 7, "total": 59}
        item = m.online_course_todo(
            course, detail,
            "https://www.icourse163.org/spoc/learn/1001195001-1471660166",
            now=m.datetime(2026, 4, 1))
        self.assertEqual(item["title"], "在线学习《创业基础：原理与训练》")
        self.assertEqual(item["source"], "icourse163")
        self.assertEqual(item["course"], "")
        self.assertEqual(item["due"], "2026-05-08T23:30")
        self.assertIn("当前进度 7/59 讲", item["note"])

    def test_过期的课程结束时间不制造逾期待办(self):
        course = m.parse_course_list(COURSE_LIST)[0]
        detail = m.parse_term_detail(TERM_DTO)
        item = m.online_course_todo(course, detail, "https://example.test/course",
                                    now=m.datetime(2026, 10, 10))
        self.assertEqual(item["due"], "")

    def test_进度变化不会改变待办id(self):
        course = m.parse_course_list(COURSE_LIST)[0]
        detail = m.parse_term_detail(TERM_DTO)
        detail["progress"] = {"done": 0, "total": 59}
        first = m.online_course_todo(course, detail, "https://example.test/course")
        detail["progress"] = {"done": 12, "total": 59}
        second = m.online_course_todo(course, detail, "https://example.test/course")
        self.assertEqual(first["id"], second["id"])
        self.assertNotEqual(first["note"], second["note"])


class OnlineCourseMessageTest(unittest.TestCase):
    def test_在线课程同时生成进度通知(self):
        course = m.parse_course_list(COURSE_LIST)[0]
        detail = m.parse_term_detail(TERM_DTO)
        detail["progress"] = {"done": 7, "total": 59}
        detail["fetchedAt"] = "2026-10-10T21:30"
        item = m.online_course_message(
            course, detail,
            "https://www.icourse163.org/spoc/learn/1001195001-1471660166")
        self.assertEqual(item["platform"], "icourse163")
        self.assertEqual(item["title"], "在线课程进度：《创业基础：原理与训练》")
        self.assertIn("7/59 讲", item["content"])
        self.assertIn("共 2 章", item["content"])
        self.assertEqual(item["course"], "")

    def test_进度变化更新同一条消息而不是重复新增(self):
        course = m.parse_course_list(COURSE_LIST)[0]
        detail = m.parse_term_detail(TERM_DTO)
        detail["progress"] = {"done": 0, "total": 59}
        first = m.online_course_message(course, detail, "https://example.test/course")
        detail["progress"] = {"done": 12, "total": 59}
        second = m.online_course_message(course, detail, "https://example.test/course")
        self.assertEqual(first["id"], second["id"])
        self.assertNotEqual(first["content"], second["content"])


class DwrTest(unittest.TestCase):
    """DWR 返回的是 JS 片段而不是 JSON，需要单独解析。"""

    def test_空数组(self):
        text = ("//#DWR-INSERT\n//#DWR-REPLY\n"
                "dwr.engine._remoteHandleCallback('1791445681593','0',[]);")
        self.assertEqual(m.parse_dwr_result(text), [])

    def test_键没有引号也要能读(self):
        text = ("dwr.engine._remoteHandleCallback('1','0',"
                "[{id:1,title:\"期中通知\",releaseTime:new Date(1776643251522)}]);")
        got = m.parse_dwr_result(text)
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0]["title"], "期中通知")
        self.assertEqual(got[0]["releaseTime"], 1776643251522)   # new Date 已解开

    def test_布尔值与嵌套(self):
        text = "dwr.engine._remoteHandleCallback('1','0',{ok:true,n:3});"
        self.assertEqual(m.parse_dwr_result(text), {"ok": True, "n": 3})

    def test_不是dwr的文本返回None(self):
        for bad in ("", "hello", "{\"a\":1}", None, 123):
            with self.subTest(bad=bad):
                self.assertIsNone(m.parse_dwr_result(bad))

    def test_读不懂的js返回None而不是抛(self):
        text = "dwr.engine._remoteHandleCallback('1','0',[{{{]);"
        self.assertIsNone(m.parse_dwr_result(text))


class HelperTest(unittest.TestCase):
    def test_毫秒转本地iso(self):
        self.assertEqual(m._iso(1778254200000), "2026-05-08T23:30")

    def test_零与非法值转空串(self):
        for bad in (0, None, "", "abc"):
            with self.subTest(bad=bad):
                self.assertEqual(m._iso(bad), "")

    def test_去html标签(self):
        self.assertEqual(m._plain("<p>总分<b>100</b>分</p>"), "总分100分")
        self.assertEqual(m._plain(None), "")


if __name__ == "__main__":
    unittest.main()
