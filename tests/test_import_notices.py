# -*- coding: utf-8 -*-
"""班群通知手工导入（`sync/import_notices.py`）的测试。

这条链路的失败模式都是**静默**的：
  * 重跑一次把你删掉的待办又拉回来（和同步层的删除名单规矩不一致）；
  * 重跑一次把你已读 / 已勾完成的状态重置成未读 / 未完成；
  * id 没加命名空间，某天平台同步碰巧撞 id，两边互相覆盖；
  * 顺手把平台同步来的 117 条消息当成「不在名单里」清掉。
所以这里逐条钉住这些边界。
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SYNC = ROOT / "sync"
sys.path.insert(0, str(SYNC))
sys.path.insert(0, str(ROOT))

import import_notices as N  # noqa: E402
from backend.database import Database  # noqa: E402


def blank_state() -> dict:
    return {
        "v": 1,
        "profile": {}, "settings": {}, "cet": {}, "meta": {},
        "courses": [], "todos": [], "messages": [],
    }


class ImportNoticesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "t.sqlite3"
        db = Database(self.db_path)
        db.save_state(blank_state())
        self.db = Database(self.db_path)

    def tearDown(self):
        self.tmp.cleanup()

    # ---------- 数据本身 ----------

    def test_ids_are_namespaced_and_unique(self):
        ids = [m["id"] for m in N.MESSAGES] + [t["id"] for t in N.TODOS]
        for i in ids:
            self.assertTrue(i.startswith(N.WECHAT_PREFIX),
                            "id 必须以 %s 开头，否则重跑会误伤平台同步来的数据：%s"
                            % (N.WECHAT_PREFIX, i))
        self.assertEqual(len(ids), len(set(ids)), "id 有重复：%s" % ids)

    def test_message_shape_matches_frontend_norm(self):
        """字段必须够 normMsg 用，且只带它认识的键（多余的会被前端 normalize 丢掉）。"""
        allowed = {"id", "platform", "course", "courseId", "title",
                   "content", "url", "time", "read", "kind", "deadline"}
        for item in N.MESSAGES:
            rec = N._message_record(item)
            self.assertEqual(set(rec), allowed)
            self.assertEqual(rec["platform"], "wechat")
            self.assertIn(rec["kind"], {"notice", "homework", "exam", "signin"})
            self.assertTrue(rec["title"], "标题不能为空")
            self.assertTrue(rec["time"], "时间不能为空（排序靠它）")

    def test_todo_shape_matches_frontend_norm(self):
        allowed = {"id", "title", "course", "courseId", "due", "priority",
                   "done", "doneAt", "note", "source", "url", "createdAt"}
        for item in N.TODOS:
            rec = N._todo_record(item)
            self.assertEqual(set(rec), allowed)
            self.assertEqual(rec["source"], "wechat",
                             "source 必须是 wechat，前端靠它在 PLATFORMS 里找来源徽章")
            self.assertIn(rec["priority"], (1, 2, 3))
            self.assertTrue(rec["title"])

    def test_due_format_is_parseable_by_frontend(self):
        """前端 parseD 直接吃字符串，格式必须是 YYYY-MM-DDTHH:MM。"""
        import re
        pat = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$")
        for item in N.TODOS:
            due = item.get("due", "")
            if due:
                self.assertRegex(due, pat, "待办截止格式不对：%s" % due)
        for item in N.MESSAGES:
            due = item.get("deadline", "")
            if due:
                self.assertRegex(due, pat, "消息截止格式不对：%s" % due)

    # ---------- 写库行为 ----------

    def test_import_into_fresh_db(self):
        s = N.run(self.db_path)
        self.assertEqual(s["messages_imported"], len(N.MESSAGES))
        self.assertEqual(s["todos_imported"], len(N.TODOS))
        state = self.db.load_state()
        self.assertEqual(len(state["messages"]), len(N.MESSAGES))
        self.assertEqual(len(state["todos"]), len(N.TODOS))

    def test_import_is_idempotent(self):
        first = N.run(self.db_path)
        second = N.run(self.db_path)
        self.assertEqual(first["messages_after"], second["messages_after"])
        self.assertEqual(first["todos_after"], second["todos_after"])
        state = self.db.load_state()
        self.assertEqual(len(state["messages"]), len(N.MESSAGES))
        self.assertEqual(len(state["todos"]), len(N.TODOS))

    def test_leaves_synced_items_alone(self):
        """平台同步来的消息 / 待办一根汗毛都不能动。"""
        state = blank_state()
        state["messages"] = [{
            "id": "chaoxing-n-ABC", "platform": "chaoxing", "course": "", "courseId": "",
            "title": "考试通知", "content": "……", "url": "", "time": "2026-09-23T11:24:00+08:00",
            "read": False, "kind": "exam", "deadline": "",
        }]
        state["todos"] = [{
            "id": "yuketang-t-1", "title": "第一次作业提交", "course": "", "courseId": "",
            "due": "", "priority": 1, "done": False, "doneAt": None, "note": "",
            "source": "yuketang", "url": "", "createdAt": "2026-09-23T19:06:43+08:00",
        }]
        Database(self.db_path).save_state(state)

        N.run(self.db_path)
        state = self.db.load_state()
        self.assertEqual(len(state["messages"]), len(N.MESSAGES) + 1)
        self.assertEqual(len(state["todos"]), len(N.TODOS) + 1)

        N.run(self.db_path)  # 再跑一次也不该把同步来的删掉
        state = self.db.load_state()
        ids = {m["id"] for m in state["messages"]}
        self.assertIn("chaoxing-n-ABC", ids)
        ids = {t["id"] for t in state["todos"]}
        self.assertIn("yuketang-t-1", ids)

    def test_preserves_user_read_and_done(self):
        """重复导入不能把「我已读 / 我已完成」重置掉。"""
        N.run(self.db_path)
        state = self.db.load_state()
        target_msg = N.MESSAGES[0]["id"]
        target_todo = N.TODOS[0]["id"]
        for m in state["messages"]:
            if m["id"] == target_msg:
                m["read"] = True
        for t in state["todos"]:
            if t["id"] == target_todo:
                t["done"] = True
                t["doneAt"] = "2026-10-08T16:30:00+08:00"
        Database(self.db_path).save_state(state)

        N.run(self.db_path)
        state = self.db.load_state()
        msg = next(m for m in state["messages"] if m["id"] == target_msg)
        todo = next(t for t in state["todos"] if t["id"] == target_todo)
        self.assertTrue(msg["read"], "已读被重跑重置了")
        self.assertTrue(todo["done"], "已完成被重跑重置了")
        self.assertEqual(todo["doneAt"], "2026-10-08T16:30:00+08:00")

    def test_respects_dismissed_list(self):
        """用户删过的条目记在 settings.dismissed，重跑不该复活它。"""
        N.run(self.db_path)
        state = self.db.load_state()
        killed = N.TODOS[0]["id"]
        state["todos"] = [t for t in state["todos"] if t["id"] != killed]
        state.setdefault("settings", {})["dismissed"] = [killed]
        Database(self.db_path).save_state(state)

        s = N.run(self.db_path)
        self.assertEqual(s["todos_imported"], len(N.TODOS) - 1)
        state = self.db.load_state()
        self.assertNotIn(killed, {t["id"] for t in state["todos"]})

    def test_dry_run_writes_nothing(self):
        before = len(self.db.load_state()["messages"])
        N.run(self.db_path, dry=True)
        self.assertEqual(len(self.db.load_state()["messages"]), before)

    def test_run_without_state_raises(self):
        empty = Path(self.tmp.name) / "empty.sqlite3"
        Database(empty)  # 建表但没有任何 singleton_state 行
        with self.assertRaises(SystemExit):
            N.run(empty)


class ContentQualityTest(unittest.TestCase):
    """内容层面的最低要求 —— 这条链路的价值全在「筛得对」，所以也测。"""

    def test_every_todo_has_a_reason(self):
        for item in N.TODOS:
            self.assertTrue(item.get("note", "").strip(),
                            "每条待办都要有 note 说明为什么 / 怎么做：%s" % item["title"])

    def test_expired_notices_are_marked_read(self):
        """已过期的通知标成已读，别让它们占未读角标。

        例外：**还有待办要补救**的（条目上带 todo 关联）必须保持未读 ——
        比如助学金那条已经过了 15:00，但你还是得去补申请；
        标成已读等于把提醒从视野里抹掉，正好丢掉最要紧的一条。
        """
        for item in N.MESSAGES:
            due = item.get("deadline", "")
            if not due or due >= "2026-10-08T16:00":
                continue
            if item.get("todo"):
                continue
            self.assertTrue(item.get("read", False),
                            "这条已经过期了，应该标已读：%s" % item["title"])

    def test_expired_but_recoverable_stays_unread(self):
        """过期却有 todo 兜着的通知，必须保持未读，且那个 todo 要真实存在。

        这条是上一条的配对约束：例外通道不能只是「没标已读」，
        它得真的指向一条待办，否则就是漏标，提醒会凭空消失。
        """
        todo_ids = {t["id"] for t in N.TODOS}
        linked = [i for i in N.MESSAGES if i.get("todo")]
        self.assertTrue(linked, "至少助学金那条应该有 todo 关联")
        for item in linked:
            self.assertIn(item["todo"], todo_ids,
                          "通知关联了一个不存在的待办：%s" % item["title"])
            self.assertFalse(item.get("read", False),
                             "还有待办没做完，这条不该标成已读：%s" % item["title"])

    def test_no_pure_forward_articles(self):
        """「请点赞转发」的推文不录 —— 群里这类占了八成。"""
        for item in N.MESSAGES:
            blob = item["title"] + item.get("content", "")
            self.assertNotIn("请同学们积极浏览、点赞、转发", blob)
            self.assertNotIn("请积极浏览、点赞、转发", blob)


if __name__ == "__main__":
    unittest.main()
