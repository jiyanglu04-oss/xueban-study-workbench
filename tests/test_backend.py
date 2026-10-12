from __future__ import annotations

import json
import http.client
import tempfile
import threading
import unittest
from unittest.mock import patch
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from backend.database import Database
from backend.server import SyncManager, create_server, merge_payload


def sample_state() -> dict:
    return {
        "v": 1,
        "profile": {"name": "小陆", "sid": "20260001", "college": "经济学院"},
        "settings": {"termStart": "2026-09-07", "totalWeeks": 20},
        "courses": [{
            "id": "c1", "name": "高等数学", "platform": "chaoxing", "color": "#2F6BED",
            "sessions": [{"day": 1, "start": 1, "len": 2, "weeks": "1-18", "room": "A101"}],
        }],
        "todos": [{"id": "t1", "title": "习题 5.1", "due": "2026-10-08T23:59",
                    "priority": 1, "done": False, "source": "chaoxing"}],
        "messages": [{"id": "m1", "title": "作业发布", "time": "2026-10-07T08:00",
                      "platform": "chaoxing", "kind": "homework", "read": False}],
        "cet": {"type": "CET-6", "daily": {}},
        "meta": {"lastSync": None, "connections": []},
    }


class _FakeServer:
    """schedule_status 只用到 root 和 db，测试里不必真的起服务。"""

    def __init__(self, root: Path, db: Database):
        self.root = root
        self.db = db


class ScheduleStatusTests(unittest.TestCase):
    """自动同步的状态判定。

    状态文件是 sync/register_task.ps1（PowerShell）写的。这里守的是
    「工作台必须显示系统里的真实情况」—— 读不到就老实说未开启，
    而不是乐观地显示已开启。
    """

    def _manager(self, root: Path) -> SyncManager:
        return SyncManager(_FakeServer(root, Database(root / "t.sqlite3")))

    def test_no_state_file_means_disabled(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            status = self._manager(Path(temp)).schedule_status()
            self.assertEqual(status["mode"], "none")
            self.assertFalse(status["enabled"])
            self.assertEqual(status["times"], [])
            self.assertIn("lastRun", status)

    def test_reads_the_state_file_written_by_powershell(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            d = root / "sync" / "state"
            d.mkdir(parents=True)
            (d / "schedule.json").write_text(
                json.dumps({"mode": "task", "times": ["08:00", "20:00"]}), encoding="utf-8")
            status = self._manager(root).schedule_status()
            self.assertEqual(status["mode"], "task")
            self.assertTrue(status["enabled"])
            self.assertEqual(status["times"], ["08:00", "20:00"])

    def test_tolerates_the_bom_powershell_likes_to_write(self) -> None:
        """`Set-Content -Encoding UTF8` 在 Windows PowerShell 5.1 会写 BOM。

        实测踩过：不处理的话 json.loads 在第一个字符就抛异常，
        于是状态永远被读成「未开启」—— 明明计划任务已经注册好了。
        """
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            d = root / "sync" / "state"
            d.mkdir(parents=True)
            (d / "schedule.json").write_bytes(
                b"\xef\xbb\xbf" + json.dumps({"mode": "task", "times": ["08:00"]}).encode("utf-8"))
            status = self._manager(root).schedule_status()
            self.assertEqual(status["mode"], "task")
            self.assertTrue(status["enabled"])

    def test_corrupt_state_file_does_not_crash(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            d = root / "sync" / "state"
            d.mkdir(parents=True)
            (d / "schedule.json").write_text("这不是 json", encoding="utf-8")
            self.assertEqual(self._manager(root).schedule_status()["mode"], "none")

    def test_missing_register_script_reports_an_error(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            result = self._manager(Path(temp)).apply_schedule(True, ["08:00"])
            self.assertFalse(result["ok"])
            self.assertIn("register_task.ps1", result["error"])


class DatabaseTests(unittest.TestCase):
    def test_roundtrip_and_dashboard(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            db = Database(Path(temp) / "test.sqlite3")
            revision = db.save_state(sample_state())
            self.assertEqual(len(revision), 16)
            loaded = db.load_state()
            self.assertEqual(loaded["profile"]["name"], "小陆")
            self.assertEqual(loaded["courses"][0]["sessions"][0]["room"], "A101")
            self.assertEqual(db.dashboard()["counts"]["openTodos"], 1)

    def test_payload_merge_preserves_completion_and_read_state(self) -> None:
        state = sample_state()
        state["todos"][0]["done"] = True
        state["messages"][0]["read"] = True
        merged = merge_payload(state, {
            "syncedAt": "2026-10-07T14:00:00+08:00",
            "messages": [{"id": "m1", "title": "作业发布（更新）", "time": "2026-10-07T08:00"}],
            "todos": [{"id": "t1", "title": "习题 5.1（更新）", "due": "2026-10-09T23:59"}],
        })
        self.assertTrue(merged["messages"][0]["read"])
        self.assertTrue(merged["todos"][0]["done"])
        self.assertEqual(merged["todos"][0]["due"], "2026-10-09T23:59")

    def test_payload_merge_updates_synced_todo_progress_but_preserves_done(self) -> None:
        state = sample_state()
        state["todos"][0]["done"] = True
        state["todos"][0]["note"] = "进度 0/59"
        merged = merge_payload(state, {
            "todos": [{"id": "t1", "title": "在线学习", "due": "",
                       "note": "进度 12/59", "source": "icourse163", "priority": 1}],
        })
        self.assertTrue(merged["todos"][0]["done"])
        self.assertEqual(merged["todos"][0]["note"], "进度 12/59")
        self.assertEqual(merged["todos"][0]["source"], "icourse163")


class ApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.server = create_server("127.0.0.1", 0, Path(self.temp.name) / "api.sqlite3")
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = "http://127.0.0.1:%d" % self.server.server_address[1]

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.temp.cleanup()

    def request(self, path: str, method: str = "GET", payload: dict | None = None) -> dict:
        data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = Request(self.base + path, data=data, method=method,
                      headers={"Content-Type": "application/json"} if data else {})
        with urlopen(req, timeout=3) as res:
            return json.loads(res.read().decode("utf-8"))

    def test_schedule_endpoint_is_answerable_without_a_scheduler(self) -> None:
        """单文件模式 / 没有调度器时也要能回答，不能 500。"""
        data = self.request("/api/schedule")
        self.assertIn("mode", data)
        self.assertIn("enabled", data)
        self.assertFalse(data["enabled"])

    def test_timetable_recognition_returns_draft_without_saving(self):
        with patch('backend.timetable_image.recognize_image', return_value={'courses': [{'name': '示例课程'}], 'warnings': [], 'rawText': '示例'}), patch('backend.server.find_sync_python', return_value=Path('python.exe')):
            data = self.request('/api/timetable/recognize', 'POST', {'image': 'test', 'totalWeeks': 20})
        self.assertTrue(data['ok'])
        self.assertEqual(data['courses'][0]['name'], '示例课程')
        self.assertIsNone(self.server.db.load_state())

    def test_timetable_bad_input_returns_readable_error(self):
        with patch('backend.server.find_sync_python', return_value=Path('python.exe')):
            with self.assertRaises(HTTPError) as error:
                self.request('/api/timetable/recognize', 'POST', {'image': 'not-an-image'})
        self.assertEqual(error.exception.code, 400)

    def test_final_exams_survive_database_roundtrip(self):
        state = sample_state()
        state['cet']['finalExams'] = [{'id': 'exam-1', 'title': '高数期末', 'date': '2027-01-12'}]
        self.request('/api/state', 'PUT', {'state': state})
        loaded = self.request('/api/state')['state']
        self.assertEqual(loaded['cet']['finalExams'], state['cet']['finalExams'])

    def test_finish_onboarding_consumes_body_before_reload(self):
        connection = http.client.HTTPConnection('127.0.0.1', self.server.server_address[1], timeout=3)
        # Never write an onboarding marker to the real workspace during a test.
        with patch.object(self.server.onboarding, 'mark_done'), patch.object(self.server.onboarding, 'status', return_value={}):
            connection.request('POST', '/api/onboarding/done', body='{}', headers={'Content-Type':'application/json'})
            response = connection.getresponse()
            self.assertEqual(response.status, 200); response.read()
            connection.request('GET', '/api/health')
            response = connection.getresponse()
            self.assertEqual(response.status, 200); response.read()
        connection.close()

    def test_favicon_probe_is_not_an_error(self) -> None:
        """浏览器打开页面会自动来要 /favicon.ico。
        回 404 的话开发者控制台会挂一条红字，干扰真正的报错排查，所以回 204。"""
        with urlopen(Request(self.base + "/favicon.ico"), timeout=3) as res:
            self.assertEqual(res.status, 204)
            self.assertEqual(res.read(), b"")

    def test_unknown_path_is_still_a_404(self) -> None:
        """放行 favicon 不能把兜底 404 一起放掉。"""
        with self.assertRaises(HTTPError) as ctx:
            urlopen(Request(self.base + "/definitely-not-here.txt"), timeout=3)
        self.assertEqual(ctx.exception.code, 404)

    def test_static_file_traversal_is_refused(self) -> None:
        """静态路由不允许跳出项目根目录。"""
        for probe in ("/src/../../../../Windows/win.ini", "/src/%2e%2e/%2e%2e/secret.txt"):
            with self.assertRaises(HTTPError) as ctx:
                urlopen(Request(self.base + probe), timeout=3)
            self.assertEqual(ctx.exception.code, 404, probe)

    def test_state_and_sync_api(self) -> None:
        self.assertTrue(self.request("/api/health")["ok"])
        put = self.request("/api/state", "PUT", {"state": sample_state()})
        self.assertTrue(put["ok"])
        self.assertEqual(self.request("/api/state")["state"]["courses"][0]["name"], "高等数学")
        sync = self.request("/api/sync/import", "POST", {
            "syncedAt": "2026-10-07T14:00:00+08:00", "note": "1 条消息",
            "courses": [], "todos": [],
            "messages": [{"id": "m2", "title": "临时调课", "platform": "yuketang"}],
            "connections": [{"key": "yuketang", "status": "connected",
                             "lastSync": "2026-10-07T14:00:00+08:00"}],
        })
        self.assertTrue(sync["ok"])
        self.assertEqual(len(self.request("/api/state")["state"]["messages"]), 2)
        self.assertEqual(len(self.request("/api/sync-runs")["runs"]), 1)


if __name__ == "__main__":
    unittest.main()
