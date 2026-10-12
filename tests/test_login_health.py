# -*- coding: utf-8 -*-
"""登录态体检 + 提醒策略的测试。

这两个模块的存在理由都来自同一个实测结论：超星 / 雨课堂的登录 cookie
带服务端写死的到期时间，反复访问并不会续期。既然到期是必然的，就必须
提前算得准（login_health），并且把「该提醒了」判断对（alerting）——
否则要么用户被天天弹窗烦到无视，要么到期了没人知道，数据静默停更。
"""
from __future__ import annotations

import importlib.util
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SYNC = ROOT / "sync"
sys.path.insert(0, str(SYNC))

import login_health  # noqa: E402
import alerting  # noqa: E402


def chrome_ts(dt: datetime) -> int:
    """把 datetime 转成 Chromium 的 expires_utc（1601 年起的微秒数）。"""
    return int((dt.timestamp() + login_health.EPOCH_DIFF) * 1000000)


def make_db(path: Path, rows: list[tuple[str, str, int]]) -> Path:
    con = sqlite3.connect(str(path))
    con.execute("CREATE TABLE cookies (host_key TEXT, name TEXT, expires_utc INTEGER)")
    con.executemany("INSERT INTO cookies VALUES (?,?,?)", rows)
    con.commit()
    con.close()
    return path


class LoginHealthTest(unittest.TestCase):
    def setUp(self) -> None:
        # ignore_cleanup_errors：Windows 上刚读过的 sqlite 文件偶尔还被系统
        # 攥着句柄，清理时报 WinError 32，跟测试本身无关。
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.now = datetime(2026, 10, 7, 12, 0, 0)
        self._n = 0

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def check(self, rows, warn_days=3):
        # 每次换一个新文件：Windows 会短暂占住刚写过的 sqlite，
        # 同一个路径连着写两次会撞上 WinError 32。
        self._n += 1
        path = Path(self.tmp.name) / ("Cookies-%d" % self._n)
        make_db(path, rows)
        return login_health.check_all(db_path=path, now=self.now, warn_days=warn_days)

    # ---------- 时间换算 ----------

    def test_chrome_timestamp_roundtrip(self):
        dt = datetime(2026, 10, 15, 3, 54, 12)
        self.assertEqual(login_health._chrome_ts_to_dt(chrome_ts(dt)), dt)

    def test_session_cookie_is_not_dated(self):
        # 0 / 负数都表示「会话级 cookie」，不能当成 1970 年
        self.assertIsNone(login_health._chrome_ts_to_dt(0))
        self.assertIsNone(login_health._chrome_ts_to_dt(-1))
        self.assertIsNone(login_health._chrome_ts_to_dt(None))

    # ---------- 状态分级 ----------

    def test_healthy_when_far_from_expiry(self):
        h = self.check([(".chaoxing.com", "_uid", chrome_ts(self.now + timedelta(days=8)))])
        self.assertEqual(h["platforms"]["chaoxing"]["status"], login_health.STATUS_OK)
        self.assertEqual(h["platforms"]["chaoxing"]["daysLeft"], 8)
        self.assertNotIn("chaoxing", h["needAttention"])

    def test_expiring_within_warn_window(self):
        h = self.check([(".chaoxing.com", "_uid", chrome_ts(self.now + timedelta(days=2)))])
        self.assertEqual(h["platforms"]["chaoxing"]["status"], login_health.STATUS_EXPIRING)
        self.assertIn("chaoxing", h["needAttention"])

    def test_exactly_on_warn_boundary_counts_as_expiring(self):
        # 边界要算进来：剩 3 天、预警线也是 3 天，必须提醒而不是放过
        h = self.check([(".chaoxing.com", "_uid", chrome_ts(self.now + timedelta(days=3)))])
        self.assertEqual(h["platforms"]["chaoxing"]["status"], login_health.STATUS_EXPIRING)

    def test_expired_when_past(self):
        h = self.check([(".chaoxing.com", "_uid", chrome_ts(self.now - timedelta(days=1)))])
        self.assertEqual(h["platforms"]["chaoxing"]["status"], login_health.STATUS_EXPIRED)
        self.assertIn("chaoxing", h["needAttention"])

    def test_earliest_cookie_wins(self):
        """一个 7 天、一个 29 天 —— 要以最早的那个为准。

        实测超星就是这样：_uid 剩 7 天，fid 还剩 29 天。若按最晚算，
        会在 _uid 早就失效之后还告诉用户「还有 29 天」。
        """
        h = self.check([
            (".chaoxing.com", "_uid", chrome_ts(self.now + timedelta(days=7))),
            (".chaoxing.com", "fid", chrome_ts(self.now + timedelta(days=29))),
        ])
        self.assertEqual(h["platforms"]["chaoxing"]["daysLeft"], 7)
        self.assertEqual(h["platforms"]["chaoxing"]["earliestKey"], "_uid")

    def test_unknown_when_no_credential_at_all(self):
        h = self.check([("www.yuketang.cn", "sessionid", chrome_ts(self.now + timedelta(days=13)))])
        self.assertEqual(h["platforms"]["chaoxing"]["status"], login_health.STATUS_UNKNOWN)
        self.assertIn("chaoxing", h["needAttention"])

    def test_mooc_is_session_only_and_never_nags(self):
        """MOOC 的凭证是会话级的，浏览器一关就没了 —— 这是正常状态。

        如果把它记成「需要登录」，用户每轮同步都会收到一条毫无意义的提醒。
        """
        empty = self.check([(".chaoxing.com", "_uid", chrome_ts(self.now + timedelta(days=9)))])
        self.assertEqual(empty["platforms"]["icourse163"]["status"], login_health.STATUS_SESSION)
        self.assertNotIn("icourse163", empty["needAttention"])

        with_session = self.check([
            (".chaoxing.com", "_uid", chrome_ts(self.now + timedelta(days=9))),
            ("www.icourse163.org", "STUDY_SESS", 0),
        ])
        self.assertEqual(with_session["platforms"]["icourse163"]["status"],
                         login_health.STATUS_SESSION)

    def test_guest_only_cookie_is_ignored(self):
        """只有游客也有的 cookie（比如 ttwid）不能当登录判据。"""
        h = self.check([("www.yuketang.cn", "ttwid", chrome_ts(self.now + timedelta(days=99)))])
        self.assertEqual(h["platforms"]["yuketang"]["status"], login_health.STATUS_UNKNOWN)

    def test_summary_mentions_platform_and_followup(self):
        h = self.check([(".chaoxing.com", "_uid", chrome_ts(self.now + timedelta(days=2)))])
        self.assertIn("超星学习通", h["summary"])
        self.assertIn("2", h["summary"])
        self.assertIn("重新登录.bat", h["summary"])

    def test_missing_db_file_does_not_crash(self):
        h = login_health.check_all(db_path=Path(self.tmp.name) / "nope.sqlite3",
                                   now=self.now)
        self.assertEqual(h["platforms"]["chaoxing"]["status"], login_health.STATUS_UNKNOWN)

    def test_future_expiry_beyond_30_days_still_reported(self):
        h = self.check([(".chaoxing.com", "_uid", chrome_ts(self.now + timedelta(days=45)))])
        self.assertEqual(h["platforms"]["chaoxing"]["daysLeft"], 45)
        self.assertEqual(h["platforms"]["chaoxing"]["status"], login_health.STATUS_OK)


class AlertingTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        # 把历史记录指到临时目录 —— 测试绝不能污染真实的 state/notify-history.json，
        # 否则跑完测试会连带把「今天已经提醒过了」写进去，真同步就不提醒了。
        self._real_history = alerting.HISTORY
        alerting.HISTORY = Path(self.tmp.name) / "notify-history.json"

    def tearDown(self) -> None:
        alerting.HISTORY = self._real_history
        self.tmp.cleanup()

    def health(self, pairs, need=None):
        platforms = {pid: {"status": st, "label": pid} for pid, st in pairs.items()}
        return {
            "platforms": platforms,
            "needAttention": need if need is not None else list(pairs.keys()),
            "summary": "测试用摘要",
        }

    def test_all_healthy_never_notifies(self):
        h = self.health({"chaoxing": "ok"}, need=[])
        should, reason = alerting.decide(h, {}, datetime(2026, 10, 7, 9, 0))
        self.assertFalse(should)
        self.assertIn("正常", reason)

    def test_state_change_triggers_once(self):
        h = self.health({"chaoxing": "expiring"})
        now = datetime(2026, 10, 7, 9, 0)
        should, _ = alerting.decide(h, {"signature": "chaoxing:ok", "date": "2026-10-07"}, now)
        self.assertTrue(should)

    def test_same_state_same_day_is_silent(self):
        """一天同步两次，不能变成一天弹两次。"""
        h = self.health({"chaoxing": "expiring"})
        history = {"signature": "chaoxing:expiring", "date": "2026-10-07"}
        should, reason = alerting.decide(h, history, datetime(2026, 10, 7, 20, 0))
        self.assertFalse(should)
        self.assertIn("不重复", reason)

    def test_hard_problem_nags_again_next_day(self):
        """已经失效的平台第二天要再提一次 —— 它一直在静默地抓不到数据。"""
        h = self.health({"chaoxing": "expired"})
        history = {"signature": "chaoxing:expired", "date": "2026-10-07"}
        should, _ = alerting.decide(h, history, datetime(2026, 10, 8, 8, 0))
        self.assertTrue(should)

    def test_soft_warning_does_not_repeat_next_day(self):
        """只是「快到期」的话，第二天不重复催 —— 别把人烦到无视提醒。"""
        h = self.health({"chaoxing": "expiring"})
        history = {"signature": "chaoxing:expiring", "date": "2026-10-07"}
        should, _ = alerting.decide(h, history, datetime(2026, 10, 8, 8, 0))
        self.assertFalse(should)

    def test_signature_is_order_independent(self):
        a = self.health({"yuketang": "expiring", "chaoxing": "expired"},
                        need=["yuketang", "chaoxing"])
        b = self.health({"chaoxing": "expired", "yuketang": "expiring"},
                        need=["chaoxing", "yuketang"])
        self.assertEqual(alerting.signature(a), alerting.signature(b))

    def test_signature_captures_status_change(self):
        a = alerting.signature(self.health({"chaoxing": "expiring"}))
        b = alerting.signature(self.health({"chaoxing": "expired"}))
        self.assertNotEqual(a, b)

    def test_notify_disabled_by_env(self):
        """排查同步问题时能一键关掉弹窗，否则调试会一直被通知打断。"""
        import os
        old = os.environ.get("WB_NO_NOTIFY")
        os.environ["WB_NO_NOTIFY"] = "1"
        try:
            self.assertFalse(alerting.notifier.enabled())
            # 策略认为该发，但发送被环境变量挡下，结果仍然是不打扰
            h = self.health({"chaoxing": "expired"})
            out = alerting.maybe_notify(h, datetime(2026, 10, 7, 9, 0))
            self.assertFalse(out["sent"])
        finally:
            if old is None:
                os.environ.pop("WB_NO_NOTIFY", None)
            else:
                os.environ["WB_NO_NOTIFY"] = old

    def test_maybe_notify_never_raises(self):
        """提醒模块再怎么写错，也不能把整轮同步带崩。"""
        import os
        old = os.environ.get("WB_NO_NOTIFY")
        os.environ["WB_NO_NOTIFY"] = "1"    # 跑测试时别真弹通知
        try:
            out = alerting.maybe_notify({"platforms": None, "needAttention": ["x"]})
            self.assertIn("sent", out)
        finally:
            if old is None:
                os.environ.pop("WB_NO_NOTIFY", None)
            else:
                os.environ["WB_NO_NOTIFY"] = old


class BackendKeepsExpiryTest(unittest.TestCase):
    """连接表里没有「还剩几天」这几列，重启后端不能把倒计时弄丢。"""

    def setUp(self) -> None:
        from backend.database import Database
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.db = Database(Path(self.tmp.name) / "state.sqlite3")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_expiry_fields_survive_roundtrip(self):
        state = {
            "v": 1,
            "meta": {
                "lastSync": "2026-10-07T20:00:00",
                "connections": [{
                    "key": "chaoxing", "status": "connected", "lastSync": "2026-10-07T20:00:00",
                    "expiresAt": "2026-10-15T03:54:12", "daysLeft": 7, "loginStatus": "ok",
                }],
                "loginHealth": {"needAttention": [], "summary": "全部正常。"},
            },
            "courses": [], "todos": [], "messages": [],
        }
        self.db.save_state(state)
        loaded = self.db.load_state()
        conn = loaded["meta"]["connections"][0]
        self.assertEqual(conn["daysLeft"], 7)
        self.assertEqual(conn["expiresAt"], "2026-10-15T03:54:12")
        self.assertEqual(conn["loginStatus"], "ok")
        self.assertTrue(loaded["meta"]["loginHealth"])

    def test_newer_expiry_not_downgraded_by_stale_client(self):
        """页面开着没刷新时手里的是旧倒计时，保存不能把新值盖回去。"""
        from backend.server import absorb_synced_items
        fresh = {
            "meta": {"lastSync": "2026-10-07T20:00:00", "connections": [{
                "key": "chaoxing", "status": "connected",
                "lastSync": "2026-10-07T20:00:00", "daysLeft": 7, "loginStatus": "ok"}]},
            "messages": [], "todos": [],
        }
        stale = {
            "meta": {"lastSync": "2026-10-07T08:00:00", "connections": [{
                "key": "chaoxing", "status": "connected",
                "lastSync": "2026-10-07T08:00:00", "daysLeft": 19, "loginStatus": "ok"}]},
            "messages": [], "todos": [], "settings": {},
        }
        merged = absorb_synced_items(stale, fresh)
        self.assertEqual(merged["meta"]["connections"][0]["daysLeft"], 7)


if __name__ == "__main__":
    unittest.main()
