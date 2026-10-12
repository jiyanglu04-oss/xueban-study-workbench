# -*- coding: utf-8 -*-
"""同步层的回归测试。

这里守的是两个**踩过坑**的点：

1. **id 必须跨进程稳定。**
   以前用 `abs(hash((title, iso)))` 生成消息 id。Python 对字符串的 hash 每个进程
   都带随机盐，同一条通知两次运行算出不同 id，`merge_payload` 就当成新消息，
   于是每同步一次重复入库一次 —— 实测消息从 20 条涨到 87 条，去掉重复只剩 14 条。
   这个测试会真的**起两个子进程**去比，因为「同一进程内相等」根本测不出这个问题。

2. **done / read 以表列为准。**
   以前 `load_state()` 只从 `data_json` 里读 read，而 `dashboard()` 是按 `is_read`
   列统计未读数的。两处一旦不一致，顶栏未读数和消息列表就对不上，而且直接改列的
   修复动作会被下一次同步静默抹掉。
"""
from __future__ import annotations

import importlib.util
import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SYNC = ROOT / "sync"
sys.path.insert(0, str(SYNC))

from adapters.base import Adapter, is_browser_dead, stable_id   # noqa: E402
from adapters.base import extract_course_name, published_recently  # noqa: E402
from adapters.chaoxing import T_ID, find_dict_list              # noqa: E402
from adapters.deadline import extract_deadline, is_future       # noqa: E402
from adapters.icourse163 import parse_course_list               # noqa: E402
from adapters.keywords import LOOKBACK_DAYS, classify_action    # noqa: E402
from backend.database import Database                           # noqa: E402
from backend.server import create_server, merge_payload               # noqa: E402

CST = timezone(timedelta(hours=8))
NOW = datetime(2026, 10, 7, 18, 0, tzinfo=CST)

# 子进程里要打印的几个 id。故意混入「没有时间」这种最容易被 now() 污染的输入。
CHILD = """
import json, sys
sys.path.insert(0, r"{sync}")
from adapters.base import Adapter, stable_id
print(json.dumps({{
    "stable": stable_id("chaoxing", "关于期中考试的通知", "2026-10-06T16:55:43+08:00"),
    "no_time": Adapter.msg("chaoxing", "课堂互动情况")["id"],
    "str_time": Adapter.msg("chaoxing", "考试通知", time_="2026-09-16 19:09:21")["id"],
    "todo": Adapter.todo("chaoxing", "C9-测验题", due="2026-10-20T23:59")["id"],
}}, ensure_ascii=False))
""".format(sync=SYNC)


class IdStabilityTests(unittest.TestCase):
    def test_ids_are_identical_across_separate_processes(self) -> None:
        runs = []
        for _ in range(3):
            out = subprocess.run([sys.executable, "-c", CHILD],
                                 capture_output=True, text=True, timeout=90, cwd=str(ROOT))
            self.assertEqual(out.returncode, 0, out.stderr)
            runs.append(json.loads(out.stdout.strip().splitlines()[-1]))
        self.assertEqual(runs[0], runs[1])
        self.assertEqual(runs[1], runs[2])
        # 顺带确认这些路径真的产出了 id，而不是全都空字符串
        for key in ("stable", "no_time", "str_time", "todo"):
            self.assertTrue(runs[0][key], key)

    def test_no_builtin_hash_left_in_adapters(self) -> None:
        """`hash()` 带随机盐，绝不能再用它生成 id。"""
        for path in sorted((SYNC / "adapters").glob("*.py")):
            for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if line.strip().startswith("#"):
                    continue                      # 注释里提到 hash() 是允许的
                self.assertNotIn("abs(hash(", line, "%s:%d" % (path.name, i))

    def test_message_id_is_stable_within_a_process(self) -> None:
        a = Adapter.msg("yuketang", "第一章作业", time_=1789961753000)["id"]
        b = Adapter.msg("yuketang", "第一章作业", time_=1789961753000)["id"]
        self.assertEqual(a, b)

    def test_explicit_mid_wins(self) -> None:
        self.assertEqual(
            Adapter.msg("chaoxing", "x", mid="chaoxing-n-F43AFD9158")["id"],
            "chaoxing-n-F43AFD9158")

    def test_merge_is_idempotent(self) -> None:
        """同一份载荷连续合并两次，不应该多出任何一条。"""
        payload = {
            "syncedAt": "2026-10-07T14:00:00+08:00",
            "courses": [{"syncKey": "chaoxing:c1", "name": "高等数学", "platform": "chaoxing"}],
            "messages": [
                Adapter.msg("chaoxing", "考试通知", time_="2026-09-16 19:09:21"),
                Adapter.msg("yuketang", "课堂互动情况"),
            ],
            "todos": [Adapter.todo("chaoxing", "C9-测验题", due="2026-10-20T23:59")],
        }
        state: dict = {}
        merge_payload(state, payload)
        once = (len(state["courses"]), len(state["messages"]), len(state["todos"]))
        merge_payload(state, payload)
        twice = (len(state["courses"]), len(state["messages"]), len(state["todos"]))
        self.assertEqual(once, twice)
        self.assertEqual(once, (1, 2, 1))

    def test_browser_death_is_recognised(self) -> None:
        self.assertTrue(is_browser_dead(Exception(
            "Target page, context or browser has been closed")))
        self.assertTrue(is_browser_dead(Exception("Browser has been closed")))
        self.assertFalse(is_browser_dead(Exception("HTTP 404 Not Found")))


class NoticesToTodosTests(unittest.TestCase):
    """「通知 → 待办」的抽取逻辑，这是同步的主要目的。"""

    def test_course_name_extracted_and_not_swallowing_next_field(self) -> None:
        self.assertEqual(
            extract_course_name("课程名称：高等数学2（经4）\r\n作业名称：C9"), "高等数学2（经4）")
        self.assertEqual(extract_course_name("《金融学》教材"), "金融学")
        self.assertEqual(extract_course_name("没有课程信息的一段话"), "")

    def test_deadline_extracted_from_real_notice_texts(self) -> None:
        cases = [
            ("考试通知", "结束时间：2026-06-25 19:55", "2026-06-25T19:55"),
            ("报名", "截止日期9月21日", "2026-09-21T23:59"),
        ]
        for title, body, expect in cases:
            iso, _ = extract_deadline(title + " " + body)
            self.assertEqual(iso, expect, body)

    def test_chapter_range_is_not_parsed_as_a_date(self) -> None:
        """「第8—9章」不能被当成 8 月 9 日。"""
        iso, _ = extract_deadline("《高等数学2》第8—9章阶段考试")
        self.assertEqual(iso, "")

    def test_past_deadline_does_not_create_a_todo(self) -> None:
        out = {"messages": [], "todos": [], "courses": []}
        ad = Adapter.__new__(Adapter)
        ad.enrich_message(
            {"id": "m1", "platform": "chaoxing", "title": "考试通知",
             "content": "结束时间：2020-06-25 19:55"},
            out)
        self.assertEqual(out["todos"], [])
        self.assertTrue(out["messages"] == [] or out["messages"] is not None)

    def test_future_deadline_creates_exactly_one_todo(self) -> None:
        out = {"messages": [], "todos": [], "courses": []}
        ad = Adapter.__new__(Adapter)
        ad.enrich_message(
            {"id": "m1", "platform": "chaoxing", "title": "作业",
             "content": "课程名称：金融学\r\n结束时间：2099-06-25 19:55"},
            out)
        self.assertEqual(len(out["todos"]), 1)
        self.assertEqual(out["todos"][0]["course"], "金融学")
        self.assertTrue(is_future(out["todos"][0]["due"]))


class RealPayloadTests(unittest.TestCase):
    """用真实抓下来的接口数据回放，防止以后再退回「猜字段」。"""

    NOTICE = SYNC / "debug" / "chaoxing" / "008_https_notice_chaoxing_com_pc_notice_getNoticeList.json"

    def test_real_notice_payload_yields_stable_unique_ids(self) -> None:
        if not self.NOTICE.exists():
            self.skipTest("没有 sync/debug 里的真实载荷，跳过")
        body = json.loads(self.NOTICE.read_text(encoding="utf-8"))["body"]
        items = find_dict_list(json.loads(body), "title")
        self.assertTrue(items, "真实通知载荷里应该能找到条目")

        # 真实字段是 idCode，不是 id —— 这就是当初 id 一直落到 hash 兜底的原因
        self.assertIn("idCode", T_ID)
        first = items[0]
        self.assertTrue(first.get("idCode") or first.get("uuid"))

        ids = [Adapter.msg("chaoxing", str(it.get("title")),
                           time_=it.get("insertTime"),
                           mid="chaoxing-n-%s" % (it.get("idCode") or it.get("uuid")))["id"]
               for it in items]
        self.assertEqual(len(ids), len(set(ids)), "同一批通知的 id 不能撞车")
        for i in ids:
            self.assertTrue(re.match(r"^chaoxing-n-.+", i), i)

    def test_real_notice_has_a_parseable_timestamp(self) -> None:
        """insertTime 是毫秒时间戳；解析不出来就会退化成「同步时刻」。"""
        if not self.NOTICE.exists():
            self.skipTest("没有 sync/debug 里的真实载荷，跳过")
        body = json.loads(self.NOTICE.read_text(encoding="utf-8"))["body"]
        first = find_dict_list(json.loads(body), "title")[0]
        m = Adapter.msg("chaoxing", str(first.get("title")), time_=first.get("insertTime"))
        self.assertTrue(m["time"].startswith("2026-0") or m["time"].startswith("2026-1"), m["time"])


class MoocCourseListTests(unittest.TestCase):
    """MOOC 课程列表。

    真实响应形状（抓包，2026-10-07）里课程名藏在 `mocCourseBaseCardVo` 子字典中，
    外层元素**没有** name/title —— 所以 `find_dict_list` 那种「找带 name 的列表」
    的做法在这里永远返回空，必须用专门的解析函数。
    """

    RESP = {
        "code": 0,
        "result": [{
            "id": 1471660166, "type": 306,
            "mocCPkgKyCardBulkPurchInfoVo": None,
            "mocCourseBaseCardVo": {"id": 1471660166, "name": "创业基础：原理与训练"},
        }],
    }

    def test_parses_name_and_term_id(self) -> None:
        """契约（2026-10-08 起）：返回课程名 + 定位课程需要的三个 ID。

        courseId / schoolId / termId 都要留下来 —— 课程内容页是
        /spoc/learn/<schoolId>-<courseId>，漏一个就 404；
        termId 则用来读章节结构和学习进度。
        """
        got = parse_course_list(self.RESP)
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0]["name"], "创业基础：原理与训练")
        self.assertEqual(got[0]["courseId"], 1471660166)
        self.assertEqual(got[0]["schoolId"], "")      # 这条样例里没带
        self.assertEqual(got[0]["termId"], "")

    def test_find_dict_list_would_have_missed_it(self) -> None:
        """记录一下为什么不能用 find_dict_list，避免以后有人「简化」回去。"""
        self.assertEqual(find_dict_list(self.RESP, "name"), [])

    def test_empty_and_error_shapes_are_safe(self) -> None:
        self.assertEqual(parse_course_list({"code": 0, "result": []}), [])
        self.assertEqual(parse_course_list({"code": -1004, "result": None}), [])
        self.assertEqual(parse_course_list(None), [])
        self.assertEqual(parse_course_list({"code": 0, "result": [{"id": 1}]}), [])


class ReadFlagPersistenceTests(unittest.TestCase):
    """done / read 必须能从表列原样往返，否则同步会把用户标好的已读抹掉。"""

    def test_read_flag_survives_roundtrip_and_sync(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            db = Database(Path(temp) / "t.sqlite3")
            state = {
                "v": 1, "profile": {}, "settings": {}, "cet": {},
                "courses": [], "todos": [],
                "messages": [
                    {"id": "m1", "title": "已读的", "time": "2026-10-07T08:00",
                     "platform": "chaoxing", "kind": "notice", "read": True},
                    {"id": "m2", "title": "未读的", "time": "2026-10-07T09:00",
                     "platform": "chaoxing", "kind": "notice", "read": False},
                ],
                "meta": {"connections": []},
            }
            db.save_state(state)
            loaded = db.load_state()
            self.assertTrue(loaded["messages"][0]["read"])
            self.assertFalse(loaded["messages"][1]["read"])

            # 再合并一次同一批（但不带 read 字段，模拟同步载荷）——已读必须保住
            merge_payload(loaded, {
                "syncedAt": "2026-10-07T14:00:00+08:00",
                "messages": [{"id": "m1", "title": "已读的"}, {"id": "m2", "title": "未读的"}],
            })
            self.assertTrue(loaded["messages"][0]["read"])
            self.assertEqual(len(loaded["messages"]), 2)

            # 存回去再读，仍然一致
            db.save_state(loaded)
            again = db.load_state()
            self.assertTrue(again["messages"][0]["read"])

    def test_dashboard_unread_count_matches_message_list(self) -> None:
        """顶栏未读数来自 is_read 列，列表来自 data_json —— 两者必须一致。"""
        with tempfile.TemporaryDirectory() as temp:
            db = Database(Path(temp) / "t.sqlite3")
            db.save_state({
                "v": 1, "profile": {}, "settings": {}, "cet": {},
                "courses": [], "todos": [],
                "messages": [
                    {"id": "m1", "title": "a", "platform": "chaoxing", "read": True},
                    {"id": "m2", "title": "b", "platform": "chaoxing", "read": False},
                    {"id": "m3", "title": "c", "platform": "chaoxing", "read": False},
                ],
                "meta": {"connections": []},
            })
            unread = sum(1 for m in db.load_state()["messages"] if not m.get("read"))
            self.assertEqual(db.dashboard()["counts"]["unreadMessages"], unread)
            self.assertEqual(unread, 2)


class KeyMessageClassificationTests(unittest.TestCase):
    """「这条通知要不要我做点什么」的判断。

    用例直接取自**真实抓下来的 37 条通知**（2026-10-07 的学习通 + 雨课堂）。
    这一层比截止时间解析更关键 —— 它决定了待办列表是被真正要做的事占满，
    还是被「课堂互动情况」「课件已上传」这种看一眼就够的通知刷屏。
    """

    # (标题, 正文) -> 期望的分类（None = 不转待办）
    REAL_CASES = [
        (("第一次作业提交", ""), "homework"),
        (("《中国近现代史纲要》 习题1", ""), "homework"),
        (("《创业基础》课程安排及课程群（必读）重发", ""), "social"),
        (("后选的同学加入微信和微助教", ""), "social"),
        (("2026年大学生数学竞赛报名通知，截止日期9月21日", ""), "signup"),
        (("考试通知", "试卷名称：第一、第二章测试考试时间：09-23 11:22:54 至 09-29 11:24:33"), "exam"),
        # 以下都是「看一眼就够」的，绝不能变成待办
        (("课堂互动情况", "刘丹枫    1次"), None),
        (("《金融学》教材", "本学期《金融学》课程使用的教材是米什金的《货币金融学》"), None),
        (("课件已上传", ""), None),
        (("上课提醒", ""), None),
        (("周二下午7-9节 阶梯4   财务学原理", ""), None),
        (("《经济法》课程开学公告", ""), None),
        (("今天的课程通知说会有领导听课，辛苦大家尽量到课哈~", ""), None),
        (("《高等数学II》期末考试基本要求", "严格按照校区教务系统的考试座位表，在指定的考场和座位入座"), None),
    ]

    def test_real_notices_are_classified_as_expected(self) -> None:
        for (title, body), expect in self.REAL_CASES:
            got = classify_action(title + " " + body)
            self.assertEqual(got[0] if got else None, expect, title)

    def test_info_only_notice_wins_over_action_words(self) -> None:
        """「到课」「座位表」这些词表面像要做事，其实是纯提醒。"""
        self.assertIsNone(classify_action("辛苦大家务必到课啊"))
        self.assertIsNone(classify_action("考试座位表已发布"))
        self.assertIsNotNone(classify_action("第8—9章阶段考试将于今晚进行"))

    def test_empty_text_is_safe(self) -> None:
        self.assertIsNone(classify_action(""))
        self.assertIsNone(classify_action(None))

    def test_published_recently_window(self) -> None:
        self.assertTrue(published_recently("2026-09-23T19:06:00+08:00", NOW, LOOKBACK_DAYS))
        self.assertTrue(published_recently("2026-09-20T20:59:00+08:00", NOW, LOOKBACK_DAYS))
        self.assertFalse(published_recently("2026-09-01T00:00:00+08:00", NOW, LOOKBACK_DAYS))
        self.assertFalse(published_recently("", NOW, LOOKBACK_DAYS))
        self.assertFalse(published_recently("不是时间", NOW, LOOKBACK_DAYS))
        # 时钟偏差导致「未来几秒」的通知不该被判成无效
        self.assertTrue(published_recently("2026-10-07T18:02:00+08:00", NOW, LOOKBACK_DAYS))


class NoticeToTodoRuleTests(unittest.TestCase):
    """enrich_message 的三条规则，逐条锁住。"""

    @staticmethod
    def _adapter() -> Adapter:
        return Adapter.__new__(Adapter)

    def test_future_deadline_beats_keywords(self) -> None:
        out = {"messages": [], "todos": [], "courses": []}
        m = {"id": "m1", "platform": "chaoxing", "title": "作业",
             "content": "结束时间：2099-07-03 23:59", "time": "2026-10-01T10:00:00+08:00"}
        self._adapter().enrich_message(m, out, now=NOW)
        self.assertEqual(len(out["todos"]), 1)
        self.assertEqual(out["todos"][0]["due"], "2099-07-03T23:59")
        self.assertEqual(out["todos"][0]["priority"], 1)

    def test_expired_deadline_creates_nothing_at_all(self) -> None:
        """解析出截止时间但已经过去 -> 既不建带日期的，也不退化成无日期待办。"""
        out = {"messages": [], "todos": [], "courses": []}
        m = {"id": "m1", "platform": "chaoxing", "title": "作业",
             "content": "结束时间：2020-07-03 23:59", "time": "2026-10-01T10:00:00+08:00"}
        self._adapter().enrich_message(m, out, now=NOW)
        self.assertEqual(out["todos"], [])

    def test_recent_actionable_notice_without_deadline_becomes_todo(self) -> None:
        out = {"messages": [], "todos": [], "courses": []}
        m = {"id": "m1", "platform": "yuketang", "title": "第一次作业提交", "content": "",
             "time": "2026-09-23T19:06:00+08:00", "kind": "notice"}
        self._adapter().enrich_message(m, out, now=NOW)
        self.assertEqual(len(out["todos"]), 1)
        self.assertEqual(out["todos"][0]["due"], "", "没有写截止时间就不该编一个")
        self.assertEqual(out["todos"][0]["priority"], 1)
        self.assertEqual(m["kind"], "homework", "顺带把消息角标从「公告」升级成「作业」")

    def test_old_actionable_notice_is_skipped(self) -> None:
        """半年前的通知不能被翻出来变成待办 —— 否则第一次同步就会刷屏。"""
        out = {"messages": [], "todos": [], "courses": []}
        m = {"id": "m1", "platform": "yuketang", "title": "实践作业主题及相关要求",
             "content": "请大家尽快组队", "time": "2026-05-21T16:48:00+08:00"}
        self._adapter().enrich_message(m, out, now=NOW)
        self.assertEqual(out["todos"], [])

    def test_noise_notice_never_becomes_a_todo(self) -> None:
        out = {"messages": [], "todos": [], "courses": []}
        m = {"id": "m1", "platform": "chaoxing", "title": "课堂互动情况",
             "content": "刘丹枫 1次", "time": "2026-09-23T11:51:00+08:00"}
        self._adapter().enrich_message(m, out, now=NOW)
        self.assertEqual(out["todos"], [])
        self.assertIn(m.get("kind"), (None, "notice"), "纯信息通知不该被升级角标")

    def test_allow_todo_false_still_fills_deadline_and_kind(self) -> None:
        """作业列表那条路径自己建待办，这里只补字段，不能重复建。"""
        out = {"messages": [], "todos": [], "courses": []}
        m = {"id": "m1", "platform": "chaoxing", "title": "作业 · C9—测验题",
             "content": "结束时间：2099-07-03 23:59", "time": "2026-10-01T10:00:00+08:00",
             "kind": "homework"}
        self._adapter().enrich_message(m, out, allow_todo=False, now=NOW)
        self.assertEqual(out["todos"], [])
        self.assertEqual(m["deadline"], "2099-07-03T23:59")

    def test_todo_id_is_stable_for_the_same_notice(self) -> None:
        """同一条通知重复处理不能产出两个 id 不同的待办。"""
        ids = []
        for _ in range(2):
            out = {"messages": [], "todos": [], "courses": []}
            m = {"id": "m1", "platform": "yuketang", "title": "第一次作业提交",
                 "content": "", "time": "2026-09-23T19:06:00+08:00"}
            self._adapter().enrich_message(m, out, now=NOW)
            ids.append(out["todos"][0]["id"])
        self.assertEqual(ids[0], ids[1])


class DeadlineWordingTests(unittest.TestCase):
    def test_date_before_the_keyword_is_parsed(self) -> None:
        """「10月20日前完成」日期在关键词前面，只往后看是抓不到的。"""
        iso, _ = extract_deadline("请务必于10月20日前完成课程评价",
                                  now=datetime(2026, 10, 7))
        self.assertEqual(iso, "2026-10-20T23:59")
        iso2, _ = extract_deadline("本作业需在11月5日前提交", now=datetime(2026, 10, 7))
        self.assertEqual(iso2, "2026-11-05T23:59")

    def test_does_not_invent_a_date_from_a_weekday(self) -> None:
        """「本周五之前提交」没有具体数字，宁可解析不出，也不要瞎猜。"""
        iso, _ = extract_deadline("本周五之前提交实验报告", now=datetime(2026, 10, 7))
        self.assertEqual(iso, "")


class DismissedTests(unittest.TestCase):
    """删掉的东西不该被下一次同步拉回来。"""

    def test_dismissed_ids_are_skipped(self) -> None:
        payload = {
            "syncedAt": "2026-10-07T14:00:00+08:00",
            "courses": [],
            "messages": [Adapter.msg("chaoxing", "考试通知", time_="2026-09-16 19:09:21")],
            "todos": [Adapter.todo("chaoxing", "C9-测验题", due="2026-10-20T23:59")],
        }
        mid = payload["messages"][0]["id"]
        tid = payload["todos"][0]["id"]
        state = {"settings": {"dismissed": [mid, tid]}}
        merge_payload(state, payload)
        self.assertEqual(state["messages"], [])
        self.assertEqual(state["todos"], [])

    def test_non_dismissed_ids_still_come_in(self) -> None:
        payload = {"messages": [Adapter.msg("chaoxing", "新通知", time_="2026-10-07 08:00:00")]}
        state = {"settings": {"dismissed": ["别的 id"]}}
        merge_payload(state, payload)
        self.assertEqual(len(state["messages"]), 1)

    def test_broken_dismissed_value_is_ignored(self) -> None:
        payload = {"messages": [Adapter.msg("chaoxing", "新通知", time_="2026-10-07 08:00:00")]}
        state = {"settings": {"dismissed": "不是列表"}}
        merge_payload(state, payload)
        self.assertEqual(len(state["messages"]), 1)


def _load_sync_module():
    spec = importlib.util.spec_from_file_location("lwb_sync_under_test", SYNC / "sync.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class SingleInstanceLockTests(unittest.TestCase):
    """同一时刻只能有一个同步在跑。

    定时任务和网页上的「立即同步」很容易撞在一起，而两边用的是同一个
    Chromium profile 目录 —— 同时启动的结果是其中一个随机崩掉，
    表现为「有时候抓得到、有时候抓不到」这种最难查的毛病。
    """

    def setUp(self) -> None:
        self.mod = _load_sync_module()
        self.temp = tempfile.TemporaryDirectory()
        self.mod.STATE = Path(self.temp.name)
        self.mod.LOCK = Path(self.temp.name) / "sync.lock"
        self.quiet = lambda *a, **k: None

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_second_run_is_refused_then_released(self) -> None:
        with self.mod.single_instance(self.quiet) as first:
            self.assertTrue(first)
            with self.mod.single_instance(self.quiet) as second:
                self.assertFalse(second, "第二个实例必须被拒绝")
        self.assertFalse(self.mod.LOCK.exists(), "退出后要清掉锁文件")
        with self.mod.single_instance(self.quiet) as third:
            self.assertTrue(third, "锁释放后应能重新获取")

    def test_stale_lock_from_a_dead_process_is_reclaimed(self) -> None:
        self.mod.LOCK.write_text(json.dumps({"pid": 999999, "at": time.time()}),
                                 encoding="utf-8")
        with self.mod.single_instance(self.quiet) as ok:
            self.assertTrue(ok, "进程已经不在的残留锁应该被清理掉")

    def test_pid_alive_detects_self(self) -> None:
        import os
        self.assertTrue(self.mod._pid_alive(os.getpid()))
        self.assertFalse(self.mod._pid_alive(999999))


def _free_port() -> int:
    """拿一个确定没人监听的端口，用来模拟「工作台没开着」。"""
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class WriteBackTests(unittest.TestCase):
    """同步结果写回数据库的两条路都必须通。

    定时同步最常见的场景是**工作台没开着**（早上 8 点），这时必须走
    `save_to_database` 直接落库 —— 否则结果只留在 sync-data.json 里，
    用户晚上打开工作台看到的还是旧数据，会以为「自动同步根本没生效」。
    工作台开着时则应优先走接口。

    以前 `post_to_server` 失败一律返回 False，日志里就一句「工作台没开着」，
    分不清是服务没起还是接口 500。现在要求它给出可读的原因。
    """

    def setUp(self) -> None:
        self.mod = _load_sync_module()
        self.temp = tempfile.TemporaryDirectory()
        self.server = create_server("127.0.0.1", 0, Path(self.temp.name) / "srv.sqlite3")
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.port = self.server.server_address[1]
        self._orig_url = self.mod.SERVER_URL
        self._orig_root = self.mod.ROOT

    def tearDown(self) -> None:
        self.mod.SERVER_URL = self._orig_url
        self.mod.ROOT = self._orig_root
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.temp.cleanup()

    def test_posting_to_a_live_server_succeeds(self) -> None:
        self.server.db.save_state({})      # 工作台至少要打开过一次，接口才收
        self.mod.SERVER_URL = "http://127.0.0.1:%d" % self.port
        ok, why = self.mod.post_to_server(
            {"courses": [], "messages": [], "todos": [], "connections": []})
        self.assertTrue(ok, why)
        self.assertEqual(why, "", "成功时不该带错误原因")

    def test_unopened_workbench_is_reported_as_such(self) -> None:
        """数据库还没初始化时接口返回 409，原因要能原样带回来，不能只说「失败」。"""
        self.mod.SERVER_URL = "http://127.0.0.1:%d" % self.port
        ok, why = self.mod.post_to_server({"courses": [], "messages": []})
        self.assertFalse(ok)
        self.assertIn("409", why)

    def test_dead_server_says_so_in_plain_words(self) -> None:
        self.mod.SERVER_URL = "http://127.0.0.1:%d" % _free_port()
        ok, why = self.mod.post_to_server({"courses": [], "messages": []})
        self.assertFalse(ok)
        self.assertTrue(why, "失败时必须给出原因，不能是空串")
        self.assertIn("没在运行", why)

    def test_loopback_never_goes_through_a_system_proxy(self) -> None:
        """开着 Clash / 公司代理时系统会有 HTTP_PROXY，连 127.0.0.1 也会被劫持。

        一旦走代理，本地接口就永远失败，每次同步都静默退化成离线写库 ——
        功能「看起来正常」，其实一直没走接口。这里钉住这个坑。
        """
        self.server.db.save_state({})
        self.mod.SERVER_URL = "http://127.0.0.1:%d" % self.port
        keys = ("HTTP_PROXY", "http_proxy", "NO_PROXY", "no_proxy")
        saved = {k: os.environ.get(k) for k in keys}
        dead_proxy = "http://127.0.0.1:%d" % _free_port()
        os.environ["HTTP_PROXY"] = dead_proxy
        os.environ["http_proxy"] = dead_proxy
        os.environ.pop("NO_PROXY", None)
        os.environ.pop("no_proxy", None)
        try:
            ok, why = self.mod.post_to_server(
                {"courses": [], "messages": [], "todos": [], "connections": []})
        finally:
            for k, v in saved.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
        self.assertTrue(ok, "本机请求被 HTTP_PROXY 劫持了：%s" % why)

    def test_offline_path_lands_in_the_database(self) -> None:
        """工作台没开着：直接写库，用户打开工作台必须能看到这次抓到的消息。"""
        root = Path(self.temp.name) / "proj"
        (root / "data").mkdir(parents=True)
        db_path = root / "data" / "workbench.sqlite3"
        Database(db_path).save_state({})          # 模拟「工作台至少打开过一次」
        self.mod.ROOT = root

        ok, err = self.mod.save_to_database({
            "courses": [], "todos": [], "connections": [],
            "messages": [{"id": "m-offline", "title": "离线写入的通知",
                          "platform": "chaoxing", "time": "2026-10-07T08:00:00+08:00"}],
        })
        self.assertTrue(ok, err)
        state = Database(db_path).load_state()
        self.assertIsNotNone(state)
        self.assertIn("m-offline", [m["id"] for m in state["messages"]])

    def test_offline_path_reports_a_brand_new_database_clearly(self) -> None:
        """一次都没打开过工作台时，要给一句能照做的提示，而不是抛异常。"""
        root = Path(self.temp.name) / "fresh"
        (root / "data").mkdir(parents=True)
        self.mod.ROOT = root
        ok, err = self.mod.save_to_database({"courses": [], "messages": []})
        self.assertFalse(ok)
        self.assertIn("打开一次工作台", err)


class DedupeTests(unittest.TestCase):
    """汇总各平台抓取结果时的去重。

    id 是「平台 + 标题 + 截止时间」的哈希，所以同一条通知被老师重发、
    或者翻页时跨页重复带进来，id 会一模一样。汇总时不去重的话，
    列表里就会出现两条完全一样的条目。
    """

    def setUp(self) -> None:
        self.mod = _load_sync_module()

    def test_same_id_kept_once(self) -> None:
        items = [
            {"id": "a", "title": "第一条"},
            {"id": "b", "title": "第二条"},
            {"id": "a", "title": "第一条（重复抓到）"},
        ]
        out = self.mod._dedupe(items)
        self.assertEqual([x["id"] for x in out], ["a", "b"])
        self.assertEqual(out[0]["title"], "第一条", "保留先出现的，避免顺序抖动")

    def test_同名不同课不算重复(self) -> None:
        """「第一次作业提交」在很多门课下都叫这个，id 不同就不能合。"""
        items = [
            {"id": "c1", "title": "第一次作业提交", "course": "概率论"},
            {"id": "c2", "title": "第一次作业提交", "course": "宏观经济学"},
        ]
        self.assertEqual(len(self.mod._dedupe(items)), 2)

    def test_items_without_id_are_kept(self) -> None:
        """没有 id 的条目不能被当成「同一个」全删掉。"""
        items = [{"title": "甲"}, {"title": "乙"}, {"title": "丙"}]
        self.assertEqual(len(self.mod._dedupe(items)), 3)

    def test_empty_input(self) -> None:
        self.assertEqual(self.mod._dedupe([]), [])


if __name__ == "__main__":
    unittest.main()
