# -*- coding: utf-8 -*-
"""电脑端「推送到手机」的测试。

这一环最容易出的问题不是崩溃，而是**静默的错**：
时间换算错 8 小时 → 提醒准点变半夜；把已完成的待办又推回去 → 手机上删不掉；
推送失败却让同步报错 → 用户以为整个工作台坏了。所以这里主要校准这些边界。
"""
from __future__ import annotations

import json
import sys
import tempfile
import threading
import unittest
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SYNC = ROOT / "sync"
sys.path.insert(0, str(SYNC))

import push_to_cloud as P  # noqa: E402


class FakeCloud(BaseHTTPRequestHandler):
    """假装成云函数的 HTTP 入口，把收到的请求记下来给测试断言。"""

    received: list = []
    reply = {"ok": True, "added": 1, "updated": 0, "message": "新增 1 条，更新 0 条"}

    def do_POST(self):  # noqa: N802 - http.server 的命名约定
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length).decode("utf-8")
        FakeCloud.received.append({"headers": dict(self.headers), "body": json.loads(raw)})
        payload = json.dumps(FakeCloud.reply).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *a):  # 静音
        pass


class PushTestCase(unittest.TestCase):
    def setUp(self) -> None:
        FakeCloud.received = []
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.dir = Path(self.tmp.name)
        self.config = self.dir / "push_config.json"
        self.snapshot = self.dir / "sync-data.json"
        self.state = self.dir / "push-state.json"

        # 模块级路径常量指向临时目录，避免碰到真实配置
        self._saved = (P.CONFIG, P.SNAPSHOT, P.STATE)
        P.CONFIG, P.SNAPSHOT, P.STATE = self.config, self.snapshot, self.state

        self.server = HTTPServer(("127.0.0.1", 0), FakeCloud)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        P.CONFIG, P.SNAPSHOT, P.STATE = self._saved
        self.tmp.cleanup()

    def write_config(self, enabled=True, base=None):
        self.config.write_text(
            json.dumps(
                {
                    "enabled": enabled,
                    "baseUrl": base if base is not None else "http://127.0.0.1:%d/ingest" % self.port,
                    "ingestKey": "k-secret",
                    "bindCode": "abcd2345",
                }
            ),
            encoding="utf-8",
        )

    def write_snapshot(self, todos, messages=None):
        self.snapshot.write_text(
            json.dumps({"todos": todos, "messages": messages or []}, ensure_ascii=False),
            encoding="utf-8",
        )


class TimeConversionTest(PushTestCase):
    def test_iso_local_time_is_read_as_beijing(self):
        """due 是本机墙上时间，必须按东八区解释 —— 差 8 小时会让提醒跑到半夜。"""
        ms = P.to_epoch("2026-10-20T18:00", datetime(2026, 10, 7))
        self.assertEqual(datetime.fromtimestamp(ms / 1000).hour, 18)
        self.assertEqual(datetime.fromtimestamp(ms / 1000).day, 20)

    def test_accepts_several_formats(self):
        want = P.to_epoch("2026-10-20T18:00", datetime.now())
        for s in ("2026-10-20 18:00", "2026-10-20 18:00:00", "2026-10-20T18:00:00"):
            self.assertEqual(P.to_epoch(s, datetime.now()), want, s)

    def test_empty_returns_none(self):
        for v in ("", None, "   ", "下周三"):
            self.assertIsNone(P.to_epoch(v, datetime.now()), repr(v))


class PayloadTest(PushTestCase):
    def test_done_and_empty_title_are_dropped(self):
        items = P.build_payload(
            [
                {"id": "a", "title": "高数作业", "due": "2026-10-08T23:59"},
                {"id": "b", "title": "已完成的", "done": True, "due": "2026-10-09T10:00"},
                {"id": "c", "title": "   "},
                {"id": "", "title": "没有 id"},
            ]
        )
        self.assertEqual([x["id"] for x in items], ["a"])

    def test_sorted_by_due_then_priority(self):
        items = P.build_payload(
            [
                {"id": "no-due", "title": "没截止", "priority": 1},
                {"id": "later", "title": "晚的", "due": "2026-12-01T09:00"},
                {"id": "soon", "title": "早的", "due": "2026-10-08T09:00"},
            ]
        )
        self.assertEqual([x["id"] for x in items], ["soon", "later", "no-due"])

    def test_server_side_wins_over_snapshot(self):
        """服务端才是用户改过状态的真相源：快照里未完成、服务端已完成，不能推回去。"""
        snapshot = [{"id": "a", "title": "待办", "done": False}]
        server = [{"id": "a", "title": "待办", "done": True}]
        merged = P.merge(snapshot, server)
        self.assertTrue(merged[0]["done"])
        self.assertEqual(len(P.build_payload(merged)), 0)

    def test_snapshot_survives_when_server_unreachable(self):
        """后端没开着时它返回空列表，快照必须原样保留，不能因此把待办全丢了。"""
        snapshot = [{"id": "a", "title": "待办"}]
        self.assertEqual(len(P.merge(snapshot, [])), 1)


class PushRunTest(PushTestCase):
    def test_disabled_config_does_nothing(self):
        self.write_config(enabled=False)
        r = P.run()
        self.assertFalse(r["ok"])
        self.assertEqual(r["code"], 0)  # 不算错误，不该让同步报红
        self.assertEqual(FakeCloud.received, [])

    def test_missing_fields_reported(self):
        self.config.write_text(json.dumps({"enabled": True, "baseUrl": ""}), encoding="utf-8")
        r = P.run()
        self.assertEqual(r["code"], 1)
        self.assertIn("baseUrl", r["message"])

    def test_successful_push_carries_key_and_bindcode(self):
        self.write_config()
        self.write_snapshot([{"id": "a", "title": "高数作业", "due": "2026-10-08T23:59", "source": "yuketang"}])
        r = P.run()
        self.assertTrue(r["ok"], r["message"])
        self.assertEqual(r["count"], 1)
        body = FakeCloud.received[0]["body"]
        self.assertEqual(body["key"], "k-secret")
        self.assertEqual(body["bindCode"], "ABCD2345")  # 手抄的码统一转大写
        self.assertEqual(body["todos"][0]["platform"], "yuketang")
        self.assertIsInstance(body["todos"][0]["dueAt"], int)

    def test_unchanged_content_is_not_pushed_twice(self):
        self.write_config()
        self.write_snapshot([{"id": "a", "title": "高数作业"}])
        P.run()
        P.run()
        self.assertEqual(len(FakeCloud.received), 1)

    def test_force_repushes(self):
        self.write_config()
        self.write_snapshot([{"id": "a", "title": "高数作业"}])
        P.run()
        P.run(force=True)
        self.assertEqual(len(FakeCloud.received), 2)

    def test_network_error_returns_code_but_never_raises(self):
        """云端连不上是很正常的事，必须安静返回错误码，不能把同步主流程带崩。"""
        self.write_config(base="http://127.0.0.1:1/ingest")
        self.write_snapshot([{"id": "a", "title": "高数作业"}])
        r = P.run()
        self.assertFalse(r["ok"])
        self.assertEqual(r["code"], 2)

    def test_state_file_records_last_result(self):
        self.write_config()
        self.write_snapshot([{"id": "a", "title": "任务"}])
        P.run()
        saved = json.loads(self.state.read_text(encoding="utf-8"))
        self.assertTrue(saved["ok"])
        self.assertEqual(saved["count"], 1)


class MessagePushTest(PushTestCase):
    """通知（不只是待办）的推送。

    用户的原话是「看看有没有新的通知和待办」—— 那些被判定成「纯信息」的
    通知（课件已上传、课堂互动）不会变成待办，但恰恰是「有没有新消息」的答案，
    所以必须单独有一条通道送上去。
    """

    @staticmethod
    def iso(days_ago=0, hours=0):
        return (datetime.now() - timedelta(days=days_ago, hours=hours)).isoformat()

    def test_old_notices_are_dropped(self):
        """45 天前的通知不推 —— 那些是上学期的事，翻出来只会让列表变长。"""
        msgs = P.build_messages(
            [
                {"id": "new", "title": "新通知", "time": self.iso(1)},
                {"id": "old", "title": "很旧的通知", "time": self.iso(90)},
            ]
        )
        self.assertEqual([m["id"] for m in msgs], ["new"])

    def test_broken_time_is_dropped_not_crashed(self):
        msgs = P.build_messages(
            [{"id": "x", "title": "时间字段坏了", "time": "昨天"}, {"id": "y", "title": "正常", "time": self.iso(1)}]
        )
        self.assertEqual([m["id"] for m in msgs], ["y"])

    def test_sorted_newest_first(self):
        msgs = P.build_messages(
            [
                {"id": "mid", "title": "中间", "time": self.iso(3)},
                {"id": "new", "title": "最新", "time": self.iso(0, 1)},
                {"id": "old", "title": "较早", "time": self.iso(10)},
            ]
        )
        self.assertEqual([m["id"] for m in msgs], ["new", "mid", "old"])

    def test_body_is_truncated(self):
        msgs = P.build_messages([{"id": "a", "title": "长文", "time": self.iso(1), "content": "甲" * 500}])
        self.assertLessEqual(len(msgs[0]["content"]), 120)

    def test_first_push_sends_everything_then_only_new(self):
        """第二次只推新增的通知 —— 全量重推会让云函数每条都做一次写库，容易超时。"""
        self.write_config()
        self.write_snapshot([{"id": "t1", "title": "待办"}], [{"id": "m1", "title": "通知一", "time": self.iso(1)}])
        P.run()
        self.assertEqual(len(FakeCloud.received[0]["body"]["messages"]), 1)

        # 又来了两条新通知
        self.write_snapshot(
            [{"id": "t1", "title": "待办"}],
            [
                {"id": "m1", "title": "通知一", "time": self.iso(1)},
                {"id": "m2", "title": "通知二", "time": self.iso(0, 1)},
                {"id": "m3", "title": "通知三", "time": self.iso(0, 2)},
            ],
        )
        P.run()
        sent = FakeCloud.received[1]["body"]["messages"]
        self.assertEqual(sorted(m["id"] for m in sent), ["m2", "m3"])

    def test_unchanged_todos_are_sent_as_empty_list(self):
        """待办没变、只有新通知时，待办要传空数组。

        传空数组表示「这次不动待办」（云函数那边空数组不进循环），
        而不是「把云端待办清空」。
        """
        self.write_config()
        self.write_snapshot([{"id": "t1", "title": "待办"}], [{"id": "m1", "title": "通知一", "time": self.iso(1)}])
        P.run()
        self.write_snapshot(
            [{"id": "t1", "title": "待办"}],
            [{"id": "m1", "title": "通知一", "time": self.iso(1)}, {"id": "m2", "title": "通知二", "time": self.iso(0, 1)}],
        )
        P.run()
        body = FakeCloud.received[1]["body"]
        self.assertEqual(body["todos"], [], "待办没变就该传空数组，让云端别动它")
        self.assertEqual(len(body["messages"]), 1)

    def test_nothing_changed_means_no_request(self):
        self.write_config()
        self.write_snapshot([{"id": "t1", "title": "待办"}], [{"id": "m1", "title": "通知一", "time": self.iso(1)}])
        P.run()
        P.run()
        self.assertEqual(len(FakeCloud.received), 1)

    def test_force_resends_notices(self):
        self.write_config()
        self.write_snapshot([{"id": "t1", "title": "待办"}], [{"id": "m1", "title": "通知一", "time": self.iso(1)}])
        P.run()
        P.run(force=True)
        self.assertEqual(len(FakeCloud.received[1]["body"]["messages"]), 1)

    def test_failed_push_does_not_mark_notices_as_sent(self):
        """推失败不能把「已推过」记上，否则这些通知永远送不上去。"""
        self.write_config(base="http://127.0.0.1:1/ingest")
        self.write_snapshot([], [{"id": "m1", "title": "通知一", "time": self.iso(1)}])
        P.run()
        saved = json.loads(self.state.read_text(encoding="utf-8"))
        self.assertFalse(saved["ok"])
        self.assertEqual(saved["msgIds"], [])

        # 网络恢复后应该把这条通知补上
        self.write_config()
        P.run()
        self.assertEqual(len(FakeCloud.received[0]["body"]["messages"]), 1)


if __name__ == "__main__":
    unittest.main()
