# -*- coding: utf-8 -*-
"""课表导入（sync/import_timetable.py）的回归测试。

重点盯那些「错了不会报错、只会静静显示错课表」的地方：
周次解析、导入幂等、不误删平台同步来的课程。
"""

from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.database import Database                                    # noqa: E402


def _load_import_timetable():
    """按文件路径加载，不要写 `from sync.import_timetable import ...`。

    `sync/` 没有 `__init__.py`，而 `sync/sync.py` 运行时会把自己的目录插进
    `sys.path`；于是 `import sync` 会被解析成 `sync/sync.py`（一个普通模块），
    再去 `sync.import_timetable` 就报 "'sync' is not a package"。
    """
    spec = importlib.util.spec_from_file_location(
        "lwb_import_timetable", ROOT / "sync" / "import_timetable.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_TT = _load_import_timetable()
TIMETABLE = _TT.TIMETABLE
import_into = _TT.import_into
parse_weeks = _TT.parse_weeks

TOTAL_SECTIONS = 13


class WeekParsingTests(unittest.TestCase):
    """周次写法必须和前端 src/js/01-core.js 的 parseWeeks 保持同一语义。"""

    def test_plain_range(self) -> None:
        self.assertEqual(parse_weeks("1-18"), set(range(1, 19)))

    def test_even_only(self) -> None:
        self.assertEqual(parse_weeks("2-13双"), {2, 4, 6, 8, 10, 12})

    def test_odd_only(self) -> None:
        self.assertEqual(parse_weeks("1-16单"), {1, 3, 5, 7, 9, 11, 13, 15})

    def test_week_four_can_be_carved_out(self) -> None:
        weeks = parse_weeks("1-3,5-18")
        self.assertNotIn(4, weeks)
        self.assertIn(3, weeks)
        self.assertIn(5, weeks)
        self.assertIn(18, weeks)

    def test_single_week(self) -> None:
        self.assertEqual(parse_weeks("4"), {4})


class TimetableShapeTests(unittest.TestCase):
    """对当前 TIMETABLE 常量做通用校验 —— 换成你自己的课表后也应该能过。"""

    def test_every_session_fits_the_section_grid(self) -> None:
        for c in TIMETABLE:
            for s in c["sessions"]:
                self.assertGreaterEqual(s["start"], 1, c["name"])
                self.assertLessEqual(s["start"] + s["len"] - 1, TOTAL_SECTIONS, c["name"])
                self.assertIn(s["day"], range(1, 8), c["name"])
                self.assertTrue(s["room"], c["name"])
                self.assertTrue(s["weeks"], c["name"])

    def test_ids_are_unique_and_namespaced(self) -> None:
        ids = [c["id"] for c in TIMETABLE]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertTrue(all(i.startswith("c-tt-") for i in ids))

    def test_weeks_are_parsable(self) -> None:
        for c in TIMETABLE:
            for s in c["sessions"]:
                self.assertTrue(parse_weeks(s["weeks"]), "%s 的周次解析为空" % c["name"])


class ImportIntoDatabaseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "t.sqlite3"
        Database(str(self.db_path)).save_state({
            "courses": [{"id": "c-sync-abc",
                         "name": "2026秋-示例课程-001",
                         "platform": "yuketang"}],
            "messages": [{"id": "m1", "title": "一条通知"}],
            "todos": [],
            "settings": {},
        })

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _courses(self) -> list[dict]:
        return Database(str(self.db_path)).load_state()["courses"]

    def test_import_adds_timetable_and_keeps_synced_courses(self) -> None:
        n, removed = import_into(self.db_path)
        self.assertEqual(n, len(TIMETABLE))
        self.assertEqual(removed, 0, "第一次导入没有旧课表课可替换")
        names = [c["name"] for c in self._courses()]
        self.assertIn("2026秋-示例课程-001", names, "平台同步来的课程不能被删")
        for c in TIMETABLE:
            self.assertIn(c["name"], names)

    def test_import_is_idempotent(self) -> None:
        import_into(self.db_path)
        import_into(self.db_path)
        import_into(self.db_path)
        courses = self._courses()
        tt = [c for c in courses if c["id"].startswith("c-tt-")]
        self.assertEqual(len(tt), len(TIMETABLE))
        self.assertEqual(sum(len(c.get("sessions", [])) for c in tt),
                         sum(len(c["sessions"]) for c in TIMETABLE))
        self.assertEqual(len(courses), len(TIMETABLE) + 1)

    def test_import_leaves_messages_alone(self) -> None:
        import_into(self.db_path)
        st = Database(str(self.db_path)).load_state()
        self.assertEqual(len(st["messages"]), 1)
        self.assertEqual(st["messages"][0]["title"], "一条通知")


if __name__ == "__main__":
    unittest.main()
