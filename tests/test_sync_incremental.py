# -*- coding: utf-8 -*-
"""「自动抓新数据」这条链路上的回归测试。

守的是三件**会让定时同步悄悄失效**的事：

1. **超星通知的翻页游标。**
   实测（2026-10-07 抓包）游标在 `notices.lastGetId`，不在顶层。
   老代码只读顶层 → 永远取不到 → `for page_no in range(1, 6)` 那圈翻页是死代码，
   只能拿第 1 页 20 条。当时 `lastPage=0`（总共就一页）所以完全看不出问题；
   等通知攒到 20 条以上，第 21 条起就永久抓不到，而且**没有任何报错**。

2. **登录过期必须能从状态里看出来。**
   无人值守的定时同步不会弹扫码窗，只会跳过那个平台正常退出。
   如果状态还是 `connected`（或者前端把它画成「待连接」），
   用户唯一的感受就是「数据怎么不更新了」。

3. **平台连接表要跟着同步结果收敛。**
   它原来只 upsert 不删，于是不再参与自动同步的平台会一直挂着
   「已连接 + 很久以前的同步时间」。
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SYNC = ROOT / "sync"
sys.path.insert(0, str(SYNC))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from adapters.base import Adapter, HISTORY_READ_DAYS   # noqa: E402
from adapters.chaoxing import _next_cursor          # noqa: E402
from backend.database import Database                # noqa: E402
from backend.server import absorb_synced_items, merge_payload   # noqa: E402


class ChaoxingNoticeCursorTests(unittest.TestCase):
    """翻页游标要能在真实返回结构里取到。"""

    def test_cursor_is_read_from_the_nested_notices_object(self) -> None:
        """真实结构：{"notices": {"list": [...], "lastGetId": "...", "lastPage": 0}}"""
        data = {"notices": {"list": [{"title": "x"}], "lastGetId": "ABC123", "lastPage": 3},
                "folders": [], "status": True}
        self.assertEqual(_next_cursor(data), "ABC123")

    def test_toplevel_cursor_still_works(self) -> None:
        """兼容老结构，别为了修一层把另一层弄坏。"""
        self.assertEqual(_next_cursor({"lastGetId": "TOP"}), "TOP")

    def test_alias_keys_are_accepted(self) -> None:
        for key in ("lastValue", "lastId"):
            self.assertEqual(_next_cursor({key: "V1"}), "V1", key)
            self.assertEqual(_next_cursor({"notices": {key: "V2"}}), "V2", key)

    def test_last_page_zero_means_no_more_pages(self) -> None:
        """只有一页时不该编出一个游标，否则会空转一圈。"""
        data = {"notices": {"list": [{"title": "x"}], "lastPage": 0}, "status": True}
        self.assertEqual(_next_cursor(data), "")

    def test_empty_or_falsy_cursor_means_stop(self) -> None:
        for bad in ("", None, 0, False):
            self.assertEqual(_next_cursor({"notices": {"lastGetId": bad}}), "", repr(bad))

    def test_junk_input_does_not_raise(self) -> None:
        for junk in (None, [], "文字", 42, {}):
            self.assertEqual(_next_cursor(junk), "", repr(junk))

    def test_non_string_cursor_is_coerced(self) -> None:
        self.assertEqual(_next_cursor({"notices": {"lastGetId": 1790135493000}}),
                         "1790135493000")


class PlatformConnectionStatusTests(unittest.TestCase):
    """平台连接状态要能被前端读到，并且跟着同步结果收敛。"""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.db = Database(str(Path(self.temp.name) / "t.sqlite3"))

    def tearDown(self) -> None:
        self.temp.cleanup()

    @staticmethod
    def _state(connections):
        return {"courses": [], "todos": [], "messages": [],
                "settings": {}, "meta": {"connections": connections}}

    def test_needs_login_survives_a_round_trip(self) -> None:
        """同步说「未登录」，前端就得能从状态里读出 needs_login。"""
        self.db.save_state(self._state([
            {"key": "chaoxing", "status": "needs_login", "lastSync": None},
        ]))
        got = {c["key"]: c["status"] for c in self.db.list_connections()}
        self.assertEqual(got, {"chaoxing": "needs_login"})

        state = self.db.load_state()
        meta = {c["key"]: c for c in state["meta"]["connections"]}
        self.assertEqual(meta["chaoxing"]["status"], "needs_login")

    def test_status_recovers_after_a_successful_sync(self) -> None:
        self.db.save_state(self._state([{"key": "chaoxing", "status": "needs_login"}]))
        self.db.save_state(self._state([{"key": "chaoxing", "status": "connected",
                                         "lastSync": "2026-10-08T08:00:00+08:00"}]))
        meta = {c["key"]: c for c in self.db.load_state()["meta"]["connections"]}
        self.assertEqual(meta["chaoxing"]["status"], "connected")

    def test_platform_missing_from_a_sync_is_dropped(self) -> None:
        """不再参与自动同步的平台不该一直挂着「已连接」。

        真实案例：「教务」默认不跑，却因为早期实验留下一条 connected，
        平台入口页于是一直显示它是连接的。
        """
        self.db.save_state(self._state([
            {"key": "chaoxing", "status": "connected"},
            {"key": "jw", "status": "connected"},
        ]))
        self.assertEqual(len(self.db.list_connections()), 2)

        self.db.save_state(self._state([{"key": "chaoxing", "status": "connected"}]))
        self.assertEqual([c["key"] for c in self.db.list_connections()],
                         ["chaoxing"])

    def test_an_empty_connections_list_does_not_wipe_the_table(self) -> None:
        """部分更新（载荷没带连接列表）不能把整张表清掉。"""
        self.db.save_state(self._state([{"key": "chaoxing", "status": "connected"}]))
        self.db.save_state(self._state([]))
        self.assertEqual(len(self.db.list_connections()), 1)

    def test_broken_entries_are_skipped(self) -> None:
        self.db.save_state(self._state([
            {"key": "chaoxing", "status": "connected"},
            {"status": "connected"},          # 没有 key
            "不是字典",                        # 类型都不对
            None,
        ]))
        self.assertEqual([c["key"] for c in self.db.list_connections()],
                         ["chaoxing"])


class StalePageSaveTests(unittest.TestCase):
    """停在同步之前的页面来保存时，不能把新抓的数据抹掉。

    服务端 PUT /api/state 是整体替换，而客户端发的是它内存里的整份状态。
    所以「早上打开页面 → 晚上 8 点自动同步 → 用户勾一个待办」这条最常见的路径，
    如果没有任何保护，就会把当晚抓到的通知和待办**全部静默删除**。
    """

    @staticmethod
    def _msg(mid, title="通知", read=False):
        return {"id": mid, "title": title, "platform": "chaoxing", "read": read}

    @staticmethod
    def _todo(tid, title="待办", done=False):
        return {"id": tid, "title": title, "source": "sync", "done": done}

    def test_synced_items_the_page_never_saw_are_kept(self) -> None:
        previous = {"messages": [self._msg("m1"), self._msg("m2")],
                    "todos": [self._todo("t1"), self._todo("t2")],
                    "meta": {"lastSync": "2026-10-07T20:00:00+08:00", "syncNote": "100 条"}}
        client = {"messages": [self._msg("m1")], "todos": [self._todo("t1")],
                  "settings": {}, "meta": {"lastSync": "2026-10-07T08:00:00+08:00"}}

        merged = absorb_synced_items(client, previous)

        self.assertEqual([m["id"] for m in merged["messages"]], ["m1", "m2"])
        self.assertEqual([t["id"] for t in merged["todos"]], ["t1", "t2"])

    def test_the_old_page_does_not_roll_back_the_sync_timestamp(self) -> None:
        previous = {"meta": {"lastSync": "2026-10-07T20:00:00+08:00", "syncNote": "100 条通知"}}
        client = {"meta": {"lastSync": "2026-10-07T08:00:00+08:00", "syncNote": "37 条通知"}}
        merged = absorb_synced_items(client, previous)
        self.assertEqual(merged["meta"]["lastSync"], "2026-10-07T20:00:00+08:00")
        self.assertEqual(merged["meta"]["syncNote"], "100 条通知")

    def test_user_edits_still_win(self) -> None:
        """已读、已完成是用户在页面上做的改动，不能被数据库里的旧值覆盖。"""
        previous = {"messages": [self._msg("m1", read=False)],
                    "todos": [self._todo("t1", done=False)]}
        client = {"messages": [self._msg("m1", read=True)],
                  "todos": [self._todo("t1", done=True)], "settings": {}}

        merged = absorb_synced_items(client, previous)

        self.assertTrue(merged["messages"][0]["read"])
        self.assertTrue(merged["todos"][0]["done"])
        self.assertEqual(len(merged["messages"]), 1, "不该补出重复条目")

    def test_dismissed_items_are_not_resurrected(self) -> None:
        """用户手动删掉的条目，即使数据库里还在，也不能补回来。"""
        previous = {"messages": [self._msg("m1"), self._msg("m2")],
                    "todos": [self._todo("t1")]}
        client = {"messages": [self._msg("m1")], "todos": [],
                  "settings": {"dismissed": ["m2", "t1"]}}

        merged = absorb_synced_items(client, previous)

        self.assertEqual([m["id"] for m in merged["messages"]], ["m1"])
        self.assertEqual(merged["todos"], [])

    def test_broken_dismissed_value_does_not_blow_up(self) -> None:
        previous = {"messages": [self._msg("m1")], "todos": []}
        for bad in ("不是列表", 123, None, {"a": 1}):
            client = {"messages": [], "todos": [], "settings": {"dismissed": bad}}
            merged = absorb_synced_items(client, previous)
            self.assertEqual(len(merged["messages"]), 1, repr(bad))

    def test_an_up_to_date_page_is_left_alone(self) -> None:
        """页面是新的时候不该产生任何变化（也不能复制出重复条目）。"""
        previous = {"messages": [self._msg("m1"), self._msg("m2")],
                    "todos": [self._todo("t1")], "meta": {"lastSync": "x"}}
        client = {"messages": [self._msg("m1"), self._msg("m2")],
                  "todos": [self._todo("t1")], "settings": {}, "meta": {"lastSync": "x"}}
        merged = absorb_synced_items(client, previous)
        self.assertEqual(len(merged["messages"]), 2)
        self.assertEqual(len(merged["todos"]), 1)

    def test_missing_previous_state_is_tolerated(self) -> None:
        client = {"messages": [self._msg("m1")], "todos": [], "settings": {}}
        self.assertIs(absorb_synced_items(client, None), client)
        self.assertEqual(len(client["messages"]), 1)

    def test_broken_entries_in_previous_are_skipped(self) -> None:
        previous = {"messages": [self._msg("m1"), {"title": "没有 id"}, "不是字典", None],
                    "todos": []}
        client = {"messages": [], "todos": [], "settings": {}}
        merged = absorb_synced_items(client, previous)
        self.assertEqual([m["id"] for m in merged["messages"]], ["m1"])


class HistoryNoticeReadStateTests(unittest.TestCase):
    """翻历史页带回来的旧通知，不该把未读角标淹没。

    修好超星翻页之后，一次同步会从 20 条通知变成 100 条。如果这 100 条全算未读，
    未读角标会从 23 跳到 103，几乎全是上学期的东西，「未读」这个词就失去意义了。
    """

    @staticmethod
    def _ago(days):
        return (datetime.now() - timedelta(days=days)).isoformat()

    def test_old_notice_is_imported_as_already_read(self) -> None:
        m = Adapter.msg("chaoxing", "上学期的高数通知",
                        time_=self._ago(HISTORY_READ_DAYS + 5))
        self.assertTrue(m.get("read"), "旧通知应该直接算已读")

    def test_recent_notice_stays_unread(self) -> None:
        m = Adapter.msg("chaoxing", "今天的通知", time_=self._ago(2))
        self.assertFalse(m.get("read"), "近期通知必须留成未读，否则会漏掉新消息")

    def test_caller_can_force_the_flag_either_way(self) -> None:
        old = self._ago(HISTORY_READ_DAYS + 100)
        self.assertFalse(Adapter.msg("chaoxing", "x", time_=old, read=False).get("read"))
        self.assertTrue(Adapter.msg("chaoxing", "y", time_=self._ago(1),
                                    read=True).get("read"))

    def test_message_without_a_time_is_treated_as_recent(self) -> None:
        """拿不到发布时间时按「刚刚」算，宁可显示未读也别漏掉。"""
        self.assertFalse(Adapter.msg("chaoxing", "无时间通知").get("read"))

    def test_merge_payload_keeps_the_read_flag_from_the_payload(self) -> None:
        state = {"messages": [], "todos": [], "settings": {}}
        merge_payload(state, {"messages": [
            {"id": "m-old", "title": "旧通知", "platform": "chaoxing", "read": True},
            {"id": "m-new", "title": "新通知", "platform": "chaoxing"},
        ]})
        by_id = {m["id"]: m for m in state["messages"]}
        self.assertTrue(by_id["m-old"]["read"])
        self.assertFalse(by_id["m-new"]["read"])

    def test_merge_payload_never_resets_read_on_a_known_message(self) -> None:
        """第二次同步时，用户已经读过的消息不能被重新标成未读。"""
        state = {"messages": [{"id": "m1", "title": "t", "read": True}],
                 "todos": [], "settings": {}}
        merge_payload(state, {"messages": [{"id": "m1", "title": "t", "read": False}]})
        self.assertTrue(state["messages"][0]["read"])


if __name__ == "__main__":
    unittest.main()
