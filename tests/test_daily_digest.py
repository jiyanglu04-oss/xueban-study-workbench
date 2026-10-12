# -*- coding: utf-8 -*-
"""daily_digest 的单元测试。

重点盯住「哪天该提醒什么」这类日期判断。它们的共同特点是：
**错了不会报错，只会安静地不提醒你**，等你发现的时候事情已经过了。
所以边界单独测：今天/明天/后天/逾期怎么分、周次怎么算、
`24:00` 这种脏数据怎么处理、正文会不会长到被系统裁掉。
"""
import sys
import unittest
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "sync"))

import daily_digest as dd  # noqa: E402

SECTIONS = [["08:00", "08:45"], ["08:55", "09:40"], ["10:00", "10:45"],
            ["10:55", "11:40"], ["12:40", "13:25"]]


def mk_state(todos=(), courses=(), termStart="2026-09-07"):
    return {
        "settings": {"termStart": termStart, "totalWeeks": 20, "sections": SECTIONS},
        "todos": list(todos),
        "courses": list(courses),
    }


def todo(title="某事", due="", done=False):
    return {"id": "t-" + title, "title": title, "due": due, "done": done}


def course(name="金融学", day=3, start=2, weeks="1-18", room="教420"):
    return {"id": "c-tt-x", "name": name,
            "sessions": [{"day": day, "start": start, "len": 2,
                          "weeks": weeks, "room": room}]}


class TestParseDt(unittest.TestCase):
    def test_normal(self):
        self.assertEqual(dd.parse_dt("2026-10-10T08:50"),
                         datetime(2026, 10, 10, 8, 50))

    def test_empty(self):
        for v in ("", None, "   "):
            self.assertIsNone(dd.parse_dt(v), v)

    def test_24_00_is_end_of_day(self):
        """通知里常见的『10 月 30 日 24:00』—— datetime 不认，得自己兜。"""
        self.assertEqual(dd.parse_dt("2026-10-30T24:00"),
                         datetime(2026, 10, 30, 23, 59))

    def test_date_only(self):
        self.assertEqual(dd.parse_dt("2026-10-30"),
                         datetime(2026, 10, 30, 23, 59))

    def test_garbage(self):
        self.assertIsNone(dd.parse_dt("待定"))


class TestWeek(unittest.TestCase):
    def test_first_week(self):
        self.assertEqual(dd.week_of(datetime(2026, 9, 7, 8), "2026-09-07"), 1)

    def test_second_week(self):
        self.assertEqual(dd.week_of(datetime(2026, 9, 14, 8), "2026-09-07"), 2)

    def test_sunday_still_same_week(self):
        """周日属于本周，不该因为『一周从周一算』的直觉就跳过。"""
        self.assertEqual(dd.week_of(datetime(2026, 9, 13, 8), "2026-09-07"), 1)


class TestParseWeeks(unittest.TestCase):
    def test_range(self):
        s = dd.parse_weeks("1-18")
        self.assertIn(5, s)
        self.assertNotIn(19, s)

    def test_even_only(self):
        s = dd.parse_weeks("2-13双")
        self.assertIn(6, s)
        self.assertNotIn(5, s)

    def test_odd_only(self):
        s = dd.parse_weeks("1-16单")
        self.assertIn(5, s)
        self.assertNotIn(6, s)

    def test_list(self):
        """『1-3,5-18』这种间断写法：中间的 4 不在任何一段里。"""
        s = dd.parse_weeks("1-3,5-18")
        self.assertIn(5, s)
        self.assertIn(18, s)
        self.assertNotIn(4, s)
        self.assertNotIn(19, s)

    def test_single(self):
        self.assertEqual(dd.parse_weeks("4"), {4})

    def test_blank_means_all(self):
        for v in ("", None, "all"):
            self.assertIsNone(dd.parse_weeks(v), v)
            self.assertTrue(dd.in_week(v, 99))


class TestSessionsOn(unittest.TestCase):
    def test_hits_right_day_and_week(self):
        st = mk_state(courses=[course(day=3, weeks="1-18")])
        # 2026-10-07 是周三，第 5 周
        got = dd.sessions_on(st, datetime(2026, 10, 7, 8))
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0]["name"], "金融学")
        self.assertEqual(got[0]["start"], "08:55")   # 第 2 节的开始时间
        self.assertEqual(got[0]["room"], "教420")

    def test_wrong_day(self):
        st = mk_state(courses=[course(day=3)])
        self.assertEqual(dd.sessions_on(st, datetime(2026, 10, 8, 8)), [])

    def test_week_not_in_range(self):
        st = mk_state(courses=[course(day=3, weeks="1-2")])
        self.assertEqual(dd.sessions_on(st, datetime(2026, 10, 7, 8)), [])

    def test_even_week_filter(self):
        """创业基础那种『2-13 周但只有双周』的课，单周不该出现。"""
        st = mk_state(courses=[course(day=3, weeks="2-13双")])
        self.assertEqual(dd.sessions_on(st, datetime(2026, 10, 7, 8)), [])   # 第 5 周=单周
        self.assertEqual(len(dd.sessions_on(st, datetime(2026, 10, 14, 8))), 1)  # 第 6 周=双周

    def test_sorted_by_start(self):
        """同一天多门课要按节次排，否则通知里『几点开始』会是错的。"""
        st = mk_state(courses=[course(name="晚课", day=3, start=5),
                               course(name="早课", day=3, start=1)])
        got = dd.sessions_on(st, datetime(2026, 10, 7, 8))
        self.assertEqual([g["name"] for g in got], ["早课", "晚课"])


class TestClassify(unittest.TestCase):
    NOW = datetime(2026, 10, 9, 18, 0)      # 周五

    def test_buckets(self):
        st = mk_state(todos=[
            todo("过期", "2026-10-08T12:00"),
            todo("今天", "2026-10-09T23:59"),
            todo("明天", "2026-10-10T08:50"),
            todo("后天", "2026-10-11T09:00"),
            todo("很久以后", "2026-11-30T23:59"),
            todo("没时间", ""),
            todo("已完成", "2026-10-09T10:00", done=True),
        ])
        open_todos = [t for t in st["todos"] if not t["done"]]
        b = dd.classify(open_todos, self.NOW)
        self.assertEqual([t["title"] for _, t in b["overdue"]], ["过期"])
        self.assertEqual([t["title"] for _, t in b["today"]], ["今天"])
        self.assertEqual([t["title"] for _, t in b["tomorrow"]], ["明天"])
        self.assertEqual([t["title"] for _, t in b["dayafter"]], ["后天"])
        self.assertEqual([t["title"] for _, t in b["later"]], ["很久以后"])
        self.assertEqual([t["title"] for _, t in b["nodue"]], ["没时间"])

    def test_today_but_time_passed_is_overdue(self):
        """今天 12:00 截止、现在 18:00 —— 属于逾期，不是『今天到点』。"""
        b = dd.classify([todo("中午的事", "2026-10-09T12:00")], self.NOW)
        self.assertEqual(len(b["overdue"]), 1)
        self.assertEqual(len(b["today"]), 0)


class TestBuild(unittest.TestCase):
    NOW = datetime(2026, 10, 9, 7, 30)

    def test_morning_has_todo_and_course(self):
        st = mk_state(todos=[todo("交作业", "2026-10-09T23:59")],
                      courses=[course(day=5, start=1)])
        title, body = dd.build("morning", st, self.NOW)   # 10/9 是周五
        self.assertIn("今天要做什么", title)
        self.assertIn("交作业", body)
        self.assertIn("今天 1 节课", body)

    def test_morning_empty_is_reassuring(self):
        st = mk_state()
        _, body = dd.build("morning", st, self.NOW)
        self.assertIn("放心", body)

    def test_evening_points_at_tomorrow(self):
        st = mk_state(todos=[todo("补课", "2026-10-10T08:50")])
        title, body = dd.build("evening", st, datetime(2026, 10, 9, 20, 30))
        self.assertIn("明天要做什么", title)
        self.assertIn("补课", body)
        self.assertIn("08:50", body)

    def test_evening_nothing_left(self):
        st = mk_state()
        _, body = dd.build("evening", st, datetime(2026, 10, 9, 20, 30))
        self.assertIn("清完", body)

    def test_body_never_exceeds_line_budget(self):
        """正文超行会被 Windows 直接裁掉 —— 与其被裁，不如我们自己控制。"""
        st = mk_state(
            todos=[todo("逾期一", "2026-10-01T10:00"), todo("逾期二", "2026-10-02T10:00"),
                   todo("今天", "2026-10-09T23:00"), todo("明天", "2026-10-10T08:00"),
                   todo("后天", "2026-10-11T08:00"), todo("大后天", "2026-10-12T08:00")],
            courses=[course(day=5, start=1, weeks="1-18"), course(name="二", day=5, start=3),
                     course(name="三", day=5, start=4)])
        for mode in ("morning", "evening"):
            _, body = dd.build(mode, st, self.NOW)
            self.assertLessEqual(len(body.split("\n")), dd.MAX_LINES, mode)

    def test_long_title_is_cut(self):
        st = mk_state(todos=[todo("这是一个特别特别特别长的待办标题啊啊啊", "2026-10-09T23:59")])
        _, body = dd.build("morning", st, self.NOW)
        self.assertNotIn("啊啊啊", body)


class TestHistory(unittest.TestCase):
    def setUp(self):
        self._orig = dd.HISTORY
        self._orig_state = dd.STATE
        import tempfile
        self.tmp = Path(tempfile.mkdtemp())
        dd.STATE = self.tmp
        dd.HISTORY = self.tmp / "digest-history.json"

    def tearDown(self):
        dd.HISTORY = self._orig
        dd.STATE = self._orig_state

    def test_mark_and_read(self):
        now = datetime(2026, 10, 9, 8, 0)
        self.assertFalse(dd.already_sent(now, "morning"))
        dd.mark_sent(now, "morning", "内容")
        self.assertTrue(dd.already_sent(now, "morning"))
        # 别的时段不受影响
        self.assertFalse(dd.already_sent(now, "evening"))
        # 隔天重新可发
        self.assertFalse(dd.already_sent(datetime(2026, 10, 10, 8, 0), "morning"))

    def test_history_is_utf8_readable(self):
        """写进去的中文必须能原样读回来——编码错了通知就变乱码。"""
        now = datetime(2026, 10, 9, 8, 0)
        dd.mark_sent(now, "morning", "今天到点：交作业")
        import json
        data = json.loads(dd.HISTORY.read_text(encoding="utf-8"))
        self.assertEqual(data["lastBody"], "今天到点：交作业")


if __name__ == "__main__":
    unittest.main()
