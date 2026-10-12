from __future__ import annotations

import argparse
import collections
import json
import mimetypes
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import webbrowser
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from .database import Database


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = ROOT / "data" / "workbench.sqlite3"
MAX_BODY = 8 * 1024 * 1024


def merge_payload(state: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    """Merge a scraper payload while preserving user-owned fields."""
    courses = state.setdefault("courses", [])
    messages = state.setdefault("messages", [])
    todos = state.setdefault("todos", [])

    # 用户手动删掉的东西不该被下一次同步又拉回来。
    # 消息/待办的 id 现在是跨进程稳定的（见 adapters/base.stable_id），
    # 同步每次都会带着同一个 id 过来；不记「删除名单」的话，删了等于白删。
    dismissed = state.get("settings", {}).get("dismissed")
    dismissed = set(dismissed) if isinstance(dismissed, list) else set()

    for incoming in payload.get("courses", []):
        if not isinstance(incoming, dict):
            continue
        key = incoming.get("syncKey") or incoming.get("id") or incoming.get("name")
        current = next((x for x in courses if
                        (x.get("syncKey") or x.get("id")) == key or x.get("name") == incoming.get("name")), None)
        if current:
            for field in ("teacher", "school", "url", "platform", "sessions", "room", "detail"):
                if incoming.get(field) not in (None, ""):
                    current[field] = incoming[field]
        else:
            item = dict(incoming)
            item.setdefault("id", "c-sync-" + stable_id(str(key)))
            item.setdefault("color", "#2F6BED")
            courses.append(item)

    for incoming in payload.get("messages", []):
        if not isinstance(incoming, dict):
            continue
        mid = incoming.get("id") or "s-" + stable_id(
            str(incoming.get("platform", "")) + str(incoming.get("title", "")) + str(incoming.get("time", ""))
        )
        if mid in dismissed:
            continue
        current = next((x for x in messages if x.get("id") == mid), None)
        if current:
            read = current.get("read", False)
            current.update(incoming)
            current["id"] = mid
            current["read"] = read
        else:
            item = dict(incoming)
            item["id"] = mid
            # 新消息的已读状态以载荷为准：同步脚本会把「很旧的历史通知」直接标成
            # 已读，否则翻历史页一次带回来的上百条旧通知会把未读角标淹没。
            item["read"] = bool(incoming.get("read", False))
            messages.append(item)

    for incoming in payload.get("todos", []):
        if not isinstance(incoming, dict):
            continue
        tid = incoming.get("id") or "t-" + stable_id(
            str(incoming.get("title", "")) + str(incoming.get("due", ""))
        )
        if tid in dismissed:
            continue
        current = next((x for x in todos if x.get("id") == tid), None)
        if current:
            current["title"] = incoming.get("title") or current.get("title")
            current["due"] = incoming.get("due") or current.get("due")
            # 同步型待办（例如 MOOC 在线学习）会持续更新进度说明；完成状态仍然
            # 以用户在工作台里的勾选为准，不能被下一轮同步重置。
            for field in ("url", "note", "course", "source", "priority"):
                if incoming.get(field) not in (None, ""):
                    current[field] = incoming[field]
        else:
            item = dict(incoming)
            item.setdefault("id", tid)
            item.setdefault("done", False)
            item.setdefault("priority", 2)
            todos.append(item)

    meta = state.setdefault("meta", {})
    meta["lastSync"] = payload.get("syncedAt")
    meta["syncNote"] = payload.get("note", "")
    if isinstance(payload.get("connections"), list):
        meta["connections"] = payload["connections"]
    return state


def stable_id(value: str) -> str:
    import hashlib
    return hashlib.sha1(value.encode("utf-8")).hexdigest()[:16]


def absorb_synced_items(client: dict, previous: dict) -> dict:
    """把数据库里有、客户端却没有的同步条目补回客户端状态。

    客户端 PUT 上来的是它内存里的**整份**状态，而服务端是整体替换。于是：
    页面停在上一次自动同步之前打开的人，一保存（勾个待办、标条已读）就会把
    新抓来的通知和待办**整个抹掉**，而且悄无声息 —— 同步日志里那次明明成功了，
    数据却没变多。这是「定时同步到底有没有用」最容易被误解的一种失败。

    只做增量补齐，不碰客户端已有的条目：
      * 只有「客户端没有、且不在删除名单里」的条目会被补回来；
      * 客户端自己的改动（已读、已完成、手改的标题）一律以客户端为准。
    删除名单（settings.dismissed）是用户手动删过的记录，界面上每个删除入口
    都会写它，所以补回来不会把用户删掉的东西复活。
    """
    if not isinstance(client, dict) or not isinstance(previous, dict):
        return client
    raw = client.get("settings", {}).get("dismissed")
    dismissed = set(raw) if isinstance(raw, list) else set()

    for key in ("messages", "todos"):
        rows = client.get(key)
        rows = rows if isinstance(rows, list) else []
        have = {x.get("id") for x in rows if isinstance(x, dict)}
        extra = [
            x for x in (previous.get(key) or [])
            if isinstance(x, dict) and x.get("id")
            and x["id"] not in have and x["id"] not in dismissed
        ]
        if extra:
            client[key] = rows + extra

    # 「上次同步时间」这类信息只有同步会写。旧页面拿着旧值，别让它把新值改回去。
    meta = client.setdefault("meta", {})
    prev_meta = previous.get("meta") or {}
    if str(prev_meta.get("lastSync") or "") > str(meta.get("lastSync") or ""):
        meta["lastSync"] = prev_meta.get("lastSync")
        meta["syncNote"] = prev_meta.get("syncNote", "")

    # connections 里带着「登录态还剩几天」。页面开着几个小时没刷新时，它手里的
    # 是过期信息，一保存就会把新的倒计时盖回旧的。和 lastSync 同理，按时间取新的。
    prev_conns = {c.get("key"): c for c in (prev_meta.get("connections") or [])
                  if isinstance(c, dict) and c.get("key")}
    if isinstance(meta.get("connections"), list):
        for conn in meta["connections"]:
            if not isinstance(conn, dict):
                continue
            old = prev_conns.get(conn.get("key")) or {}
            if str(old.get("lastSync") or "") > str(conn.get("lastSync") or ""):
                for field in ("expiresAt", "daysLeft", "loginStatus",
                              "lastSync", "status"):
                    if old.get(field) is not None:
                        conn[field] = old[field]
    elif prev_meta.get("connections"):
        meta["connections"] = prev_meta["connections"]

    # 登录态体检结果是同步脚本算出来的，跟连接状态一样不该被旧页面抹掉。
    if not meta.get("loginHealth") and prev_meta.get("loginHealth"):
        meta["loginHealth"] = prev_meta["loginHealth"]
    return client


class WorkbenchServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address: tuple[str, int], db: Database, root: Path = ROOT):
        self.db = db
        self.root = root.resolve()
        self.sync_manager: SyncManager | None = None
        self.onboarding: OnboardingManager | None = None
        super().__init__(address, WorkbenchHandler)

    def server_close(self) -> None:
        if self.sync_manager:
            self.sync_manager.stop()
        if self.onboarding:
            self.onboarding.stop()
        super().server_close()


def _decode_console(raw: bytes | None) -> str:
    """Windows PowerShell 默认按控制台代码页（简中是 GBK）输出，不是 UTF-8。"""
    if not raw:
        return ""
    for enc in ("utf-8", "gbk", "mbcs"):
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", "replace")


def find_sync_python(root: Path) -> Path | None:
    """找一个真的装了 Playwright 的解释器。

    顺序：项目内的便携环境 → 项目 venv → 当前解释器。
    发布包里第一个就命中 —— 那是「启动学伴.bat」第一次运行时自动装好的，
    所以对方不需要自己装 Python，也不用懂什么是 PATH。
    """
    candidates = [
        root / "runtime" / "python" / "python.exe",       # 发布包自动装的便携版
        root / "runtime" / "python" / "bin" / "python",
        root / ".venv" / "Scripts" / "python.exe",        # 本机开发环境
        root / ".venv" / "bin" / "python",
        Path(sys.executable),
    ]
    for candidate in candidates:
        if not candidate.is_file():
            continue
        try:
            check = subprocess.run(
                [str(candidate), "-c", "import playwright"],
                cwd=str(root),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=8,
                check=False,
            )
            if check.returncode == 0:
                return candidate
        except (OSError, subprocess.TimeoutExpired):
            continue
    return None


def send_system_notice(root: Path, title: str, body: str) -> None:
    """弹一条 Windows 通知。失败一律吞掉 —— 通知不该影响服务启动。

    复用 sync/notifier.py（中文走 UTF-8 JSON 文件，命令行只传路径），
    这里用按路径加载，因为 sync 目录不是 Python 包。
    """
    try:
        import importlib.util
        path = root / "sync" / "notifier.py"
        if not path.is_file():
            return
        spec = importlib.util.spec_from_file_location("wb_notifier", path)
        if spec is None or spec.loader is None:
            return
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        mod.send(title, body)
    except Exception:
        pass


class SyncManager:
    """负责「立即同步」，以及把「每天自动同步」同步到 Windows 计划任务。

    ⚠️ 定时**不再**由本进程的线程负责，这是有意的。以前这里有个「每 20 秒看一次
    是不是到了设定时间」的循环，三个问题：
      1. 只在工作台服务开着的时候有效 —— 学生不会整天开着它，等于没做；
      2. 它配的时间和系统计划任务里的时间是两份真相，很容易对不上；
      3. 两边同时到点会各起一个 Chromium，抢同一个 profile，表现为随机抓取失败。
    现在只有一个入口：sync/register_task.ps1。本类只做两件事 ——
    手动触发同步、读写那个计划任务的状态。
    """

    SCHEDULE_STATE = Path("sync") / "state" / "schedule.json"

    def __init__(self, server: WorkbenchServer):
        self.server = server
        self.process: subprocess.Popen | None = None
        self.lock = threading.Lock()

    def start(self) -> None:
        """定时由 Windows 计划任务负责，这里刻意什么都不做。"""

    def stop(self) -> None:
        """同上。"""

    # ---------- 自动同步（Windows 计划任务）----------

    def schedule_status(self) -> dict[str, Any]:
        raw: dict[str, Any] = {}
        try:
            # utf-8-sig：PowerShell 写出来的 JSON 可能带 BOM，
            # 用普通 utf-8 读会让 json.loads 在第一个字符就报错。
            raw = json.loads((self.server.root / self.SCHEDULE_STATE)
                             .read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            raw = {}
        if not isinstance(raw, dict):
            raw = {}
        mode = str(raw.get("mode") or "none")
        times = raw.get("times")
        runs = self.server.db.list_sync_runs(1)
        return {
            "mode": mode,                                  # task / startup / none
            "enabled": mode in ("task", "startup"),
            "times": [str(t) for t in times] if isinstance(times, list) else [],
            "updatedAt": raw.get("updatedAt") or "",
            "available": (self.server.root / "sync" / "register_task.ps1").is_file(),
            "lastRun": runs[0] if runs else None,
        }

    def apply_schedule(self, enabled: bool, times: list[str]) -> dict[str, Any]:
        """把界面上的开关/时间应用到系统计划任务，再回读真实状态。

        回读这一步是关键：界面显示的必须是系统里的真实情况，
        而不是「界面以为的」情况 —— 否则失败时会显示得好像成功了。
        """
        script = self.server.root / "sync" / "register_task.ps1"
        if not script.is_file():
            return {"ok": False, "error": "找不到 sync/register_task.ps1"}
        shell = shutil.which("powershell") or "powershell"
        cmd = [shell, "-NoProfile", "-ExecutionPolicy", "Bypass",
               "-File", str(script), "-Mode", "register" if enabled else "unregister"]
        if enabled and times:
            cmd += ["-Times", ",".join(times)]
        try:
            proc = subprocess.run(cmd, cwd=str(self.server.root), timeout=120,
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        except (OSError, subprocess.TimeoutExpired) as exc:
            return {"ok": False, "error": "调用 PowerShell 失败：%s" % exc}
        output = _decode_console(proc.stdout) + _decode_console(proc.stderr)
        if proc.returncode != 0:
            return {"ok": False, "error": (output.strip() or "注册失败")[-400:],
                    "status": self.schedule_status()}
        return {"ok": True, "status": self.schedule_status(), "output": output.strip()[-600:]}

    # ---------- 手动触发 ----------

    def trigger(self, reason: str = "manual") -> tuple[bool, str]:
        with self.lock:
            if self.process and self.process.poll() is None:
                return False, "同步任务正在运行"
            script = self.server.root / "sync" / "sync.py"
            if not script.exists():
                return False, "未找到同步脚本"
            sync_python = self._sync_python()
            if sync_python is None:
                return False, "同步环境未安装 Playwright，请先双击「安装环境.bat」"
            env = os.environ.copy()
            env["LWB_SERVER_URL"] = "http://127.0.0.1:%d" % self.server.server_address[1]
            try:
                self.process = subprocess.Popen(
                    [str(sync_python), str(script), "--no-pause"],
                    cwd=str(self.server.root), env=env,
                )
                print("同步任务已启动（%s，PID %s）" % (reason, self.process.pid))
                return True, "同步已启动，首次或登录过期时会弹出扫码窗口"
            except OSError as exc:
                return False, "无法启动同步脚本：%s" % exc

    def _sync_python(self) -> Path | None:
        """Prefer the project venv so web-triggered sync uses Playwright reliably."""
        return find_sync_python(self.server.root)


class OnboardingManager:
    """首次使用的引导：判断要不要引导、拉起扫码登录、抓第一次数据。

    为什么单独走一条链路
    ------------------
    发布包发出去之后，对方电脑上什么都没有 —— 没有课表、没有登录态，
    连 Python 都得现装。以前只能靠他自己在文件夹里翻出一串 .bat 双击，
    很容易卡在第一步就放弃了。现在改成：页面一打开就是向导，点一下按钮，
    扫码窗口自己弹出来；扫完自动抓一次，课程和通知直接出现在界面上 ——
    全程不用离开浏览器。

    为什么不复用 SyncManager：那条路跑的是**无窗口**模式，而实测发现无窗口
    模式下遇到没登录的平台会静默跳过（不会弹扫码窗）。首次引导必须有窗口，
    这是两件事，不能合并。
    """

    STATE_DIR = Path("sync") / "state"
    DONE_FILE = STATE_DIR / "onboarded.json"

    #: 引导里露出的平台，(key, 显示名, 一句话说明)，顺序即页面上的顺序
    PLATFORMS = (
        ("chaoxing", "超星学习通", "通知 · 作业 · 课程"),
        ("yuketang", "雨课堂", "公告 · 课件 · 上课提醒"),
        ("icourse163", "中国大学 MOOC", "公告 · 测验 · 学习进度"),
    )
    HEALTH_TTL = 2.5      # 登录态体检结果的缓存时长，避免每次轮询都开一个进程

    def __init__(self, server: "WorkbenchServer"):
        self.server = server
        self.process: subprocess.Popen | None = None
        self.lock = threading.Lock()
        self.stage = ""                       # "" / login / sync
        self.platform = ""
        self.logs: collections.deque = collections.deque(maxlen=200)
        self._py: Path | None = None
        self._health: dict = {}
        self._health_at = 0.0

    # ---------------- 状态 ----------------

    @property
    def done_file(self) -> Path:
        return self.server.root / self.DONE_FILE

    def is_done(self) -> bool:
        return self.done_file.is_file()

    def mark_done(self) -> None:
        """记下「这个人已经走完引导」。

        发布包里特意不带这个文件，所以别人拿到一定会被引导一次；
        你自己本机早就有，不会再被弹。
        """
        try:
            self.done_file.parent.mkdir(parents=True, exist_ok=True)
            self.done_file.write_text(
                json.dumps({"completedAt": datetime.now().isoformat(timespec="seconds")},
                           ensure_ascii=False, indent=2),
                encoding="utf-8")
        except OSError:
            pass

    def is_running(self) -> bool:
        return self.process is not None and self.process.poll() is None

    def python(self) -> Path | None:
        if self._py is None:
            self._py = find_sync_python(self.server.root)
        return self._py

    def platform_health(self) -> list[dict[str, Any]]:
        """各平台的登录态。读的是浏览器 profile 里的 cookie，不联网。"""
        now = time.monotonic()
        if now - self._health_at > self.HEALTH_TTL:
            self._health = self._read_health()
            self._health_at = now
        health = self._health
        rows = []
        for key, label, use in self.PLATFORMS:
            info = (health.get("platforms") or {}).get(key) or {}
            status = str(info.get("status") or "unknown")
            # 会话级平台不参与到期提醒，不等于新用户已经登录过。
            if status == "session" and info.get("credentialFound") is False:
                status = "unknown"
            rows.append({
                "key": key,
                "label": label,
                "use": use,
                "status": status,
                "daysLeft": info.get("daysLeft"),
                "loggedIn": status in ("ok", "expiring", "session"),
            })
        return rows

    def _read_health(self) -> dict:
        py = self.python()
        script = self.server.root / "sync" / "login_health.py"
        if py is None or not script.is_file():
            return {}
        try:
            proc = subprocess.run([str(py), str(script), "--json"],
                                  cwd=str(self.server.root), timeout=30,
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                  check=False)
        except (OSError, subprocess.TimeoutExpired):
            return {}
        try:
            data = json.loads(_decode_console(proc.stdout) or "{}")
        except ValueError:
            return {}
        return data if isinstance(data, dict) else {}

    def status(self) -> dict[str, Any]:
        return {
            "needsOnboarding": not self.is_done(),
            "ready": self.python() is not None,
            "running": ({"stage": self.stage, "platform": self.platform}
                        if self.is_running() else None),
            "platforms": self.platform_health(),
            "logs": list(self.logs)[-14:],
        }

    # ---------------- 动作 ----------------

    def start_login(self, platform: str) -> tuple[bool, str]:
        """给某个平台弹一次扫码窗口（有头，否则扫不了码）。"""
        if platform not in [k for k, _l, _u in self.PLATFORMS]:
            return False, "未知平台：%s" % platform
        return self._spawn(["sync/relogin.py", "--only", platform], "login", platform)

    def start_sync(self) -> tuple[bool, str]:
        """登录完之后抓第一次数据。无窗口，不打扰人。"""
        return self._spawn(["sync/sync.py", "--headless", "--no-pause",
                            "--reason", "onboard"], "sync", "")

    def _spawn(self, args: list[str], stage: str, platform: str) -> tuple[bool, str]:
        with self.lock:
            if self.is_running():
                return False, "上一步还没跑完，等它结束再点"
            py = self.python()
            if py is None:
                return False, "运行环境还没装好，请先双击文件夹里的「启动学伴.bat」"
            env = os.environ.copy()
            # 强制 UTF-8 + 不缓冲：否则日志要么乱码，要么全攒到最后才吐出来
            env["PYTHONIOENCODING"] = "utf-8"
            env["PYTHONUNBUFFERED"] = "1"
            # 结果回写本机服务（而不是只更新单文件 HTML），否则页面上看不到新数据
            env["LWB_SERVER_URL"] = "http://127.0.0.1:%d" % self.server.server_address[1]
            try:
                self.process = subprocess.Popen(
                    [str(py)] + args, cwd=str(self.server.root), env=env,
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            except OSError as exc:
                return False, "无法启动：%s" % exc
            self.stage = stage
            self.platform = platform
            self.logs.clear()
            proc = self.process
            threading.Thread(target=self._pump, args=(proc,), daemon=True).start()
            return True, "已启动"

    def _pump(self, proc: subprocess.Popen) -> None:
        """把子进程的输出一行一行搬进内存，供前端轮询时显示。"""
        try:
            stream = proc.stdout
            if stream is None:
                return
            for raw in iter(stream.readline, b""):
                line = _decode_console(raw).rstrip()
                if line:
                    self.logs.append(line)
        except (OSError, ValueError):
            pass
        finally:
            try:
                if proc.stdout:
                    proc.stdout.close()
            except OSError:
                pass
            self.stage = ""
            self.platform = ""

    def stop(self) -> None:
        if self.is_running() and self.process:
            try:
                self.process.terminate()
            except OSError:
                pass


class WorkbenchHandler(BaseHTTPRequestHandler):
    server: WorkbenchServer
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt: str, *args: Any) -> None:
        sys.stdout.write("[%s] %s\n" % (self.log_date_time_string(), fmt % args))

    def _json(self, data: Any, status: int = 200) -> None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _body(self) -> dict[str, Any]:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise ValueError("invalid content length") from exc
        if length <= 0 or length > MAX_BODY:
            raise ValueError("request body is empty or too large")
        try:
            data = json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("invalid JSON") from exc
        if not isinstance(data, dict):
            raise ValueError("JSON body must be an object")
        return data

    def _serve_file(self, path: Path) -> None:
        try:
            resolved = path.resolve()
            resolved.relative_to(self.server.root)
        except (OSError, ValueError):
            self._json({"error": "not found"}, HTTPStatus.NOT_FOUND)
            return
        if not resolved.is_file():
            self._json({"error": "not found"}, HTTPStatus.NOT_FOUND)
            return
        data = resolved.read_bytes()
        mime = mimetypes.guess_type(resolved.name)[0] or "application/octet-stream"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", mime + ("; charset=utf-8" if mime.startswith("text/") else ""))
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self' 'unsafe-inline' data: https:; connect-src 'self'")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        if path == "/api/health":
            self._json({"ok": True, "service": "学伴", "schemaVersion": 1,
                        "database": str(self.server.db.path.name),
                        "scheduler": bool(self.server.sync_manager),
                        "schedule": (self.server.sync_manager.schedule_status()["mode"]
                                     if self.server.sync_manager else "none")})
        elif path == "/api/schedule":
            self._json(self.server.sync_manager.schedule_status() if self.server.sync_manager
                       else {"mode": "none", "enabled": False, "times": []})
        elif path == "/api/state":
            self._json({"state": self.server.db.load_state(), "revision": self.server.db.revision()})
        elif path == "/api/dashboard":
            self._json(self.server.db.dashboard())
        elif path == "/api/platforms":
            self._json({"connections": self.server.db.list_connections()})
        elif path == "/api/sync-runs":
            query = parse_qs(parsed.query)
            try:
                limit = int(query.get("limit", ["20"])[0])
            except ValueError:
                limit = 20
            self._json({"runs": self.server.db.list_sync_runs(limit)})
        elif path == "/api/onboarding":
            # 首次打开页面会来问一句「要不要引导」。这个接口要能扛住高频轮询，
            # 所以登录态体检带缓存（见 HEALTH_TTL）。
            self._json(self.server.onboarding.status() if self.server.onboarding
                       else {"needsOnboarding": False, "ready": True,
                             "running": None, "platforms": [], "logs": []})
        elif path in ("/", "/学伴.html"):
            self._serve_file(self.server.root / "学伴.html")
        elif path == "/favicon.ico":
            # 浏览器打开页面时会自动来要图标。不处理的话控制台会挂一条 404，
            # 排查真正的问题时很碍眼，所以直接回 204。
            self.send_response(HTTPStatus.NO_CONTENT)
            self.send_header("Content-Length", "0")
            self.send_header("Cache-Control", "max-age=86400")
            self.end_headers()
        elif path.startswith("/src/"):
            self._serve_file(self.server.root / path.lstrip("/"))
        else:
            self._json({"error": "not found"}, HTTPStatus.NOT_FOUND)

    def do_PUT(self) -> None:  # noqa: N802
        if urlparse(self.path).path != "/api/state":
            self._json({"error": "not found"}, HTTPStatus.NOT_FOUND)
            return
        try:
            payload = self._body()
            state = payload.get("state", payload)
            if not isinstance(state, dict):
                raise ValueError("state must be an object")
            # 页面可能停在上一次自动同步之前。先把数据库里它不知道的同步条目
            # 补回去，否则这次保存会把刚抓到的通知和待办一起抹掉。
            state = absorb_synced_items(state, self.server.db.load_state())
            revision = self.server.db.save_state(state)
            self._json({"ok": True, "revision": revision})
        except ValueError as exc:
            self._json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
        except Exception as exc:
            self._json({"error": "database write failed", "detail": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path == "/api/timetable/recognize":
            from .timetable_image import recognize_image, TimetableImageError
            try:
                body = self._body()
                python = find_sync_python(self.server.root)
                if python is None:
                    raise TimetableImageError("运行环境未就绪，请先运行安装环境。")
                weeks = int(body.get("totalWeeks", 20))
                sections = int(body.get("maxSections", 13))
                draft = recognize_image(body.get("image", ""), python, self.server.root, weeks, sections)
                self._json({"ok": True, **draft})
            except (ValueError, TypeError) as exc:
                self._json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            except Exception:
                self._json({"error": "课表识别失败，请重新选择图片或手动录入。"}, HTTPStatus.INTERNAL_SERVER_ERROR)
            return
        if path == "/api/schedule":
            # 把界面上的「自动同步」开关/时间落到系统计划任务里。
            # 返回的是**回读后的真实状态**，不是「我们已经下发了」这种乐观回答。
            if not self.server.sync_manager:
                self._json({"ok": False, "error": "调度不可用"}, HTTPStatus.SERVICE_UNAVAILABLE)
                return
            try:
                body = self._body()
            except ValueError as exc:
                self._json({"ok": False, "error": str(exc)}, HTTPStatus.BAD_REQUEST)
                return
            raw_times = body.get("times")
            if not isinstance(raw_times, list):
                raw_times = re.split(r"[,，;；\s]+", str(raw_times or ""))
            times = [str(t).strip() for t in raw_times
                     if re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", str(t).strip())]
            result = self.server.sync_manager.apply_schedule(bool(body.get("enabled")), times)
            self._json(result, HTTPStatus.OK if result.get("ok") else HTTPStatus.INTERNAL_SERVER_ERROR)
            return
        if path == "/api/sync/run":
            if not self.server.sync_manager:
                self._json({"error": "scheduler is unavailable"}, HTTPStatus.SERVICE_UNAVAILABLE)
                return
            ok, message = self.server.sync_manager.trigger("manual")
            self._json({"ok": ok, "message": message} if ok else {"ok": False, "error": message},
                       HTTPStatus.ACCEPTED if ok else HTTPStatus.CONFLICT)
            return
        if path.startswith("/api/onboarding/"):
            manager = self.server.onboarding
            if manager is None:
                self._json({"ok": False, "error": "引导不可用"}, HTTPStatus.SERVICE_UNAVAILABLE)
                return
            action = path.rsplit("/", 1)[-1]
            if action == "done":
                # Consume the JSON body before the browser reuses this HTTP/1.1
                # connection for reload; otherwise '{}' becomes part of GET.
                try:
                    self._body()
                except ValueError as exc:
                    self._json({"ok": False, "error": str(exc)}, HTTPStatus.BAD_REQUEST)
                    return
                manager.mark_done()
                self._json({"ok": True, "status": manager.status()})
                return
            if action not in ("login", "sync"):
                self._json({"ok": False, "error": "未知操作"}, HTTPStatus.NOT_FOUND)
                return
            try:
                body = self._body()
            except ValueError:
                body = {}
            if action == "login":
                ok, message = manager.start_login(str(body.get("platform") or ""))
            else:
                ok, message = manager.start_sync()
            self._json({"ok": ok, "message": message, "status": manager.status()},
                       HTTPStatus.ACCEPTED if ok else HTTPStatus.CONFLICT)
            return
        if path != "/api/sync/import":
            self._json({"error": "not found"}, HTTPStatus.NOT_FOUND)
            return
        try:
            payload = self._body()
            state = self.server.db.load_state()
            if state is None:
                self._json({"error": "请先打开一次工作台，初始化数据库"}, HTTPStatus.CONFLICT)
                return
            state = merge_payload(state, payload)
            revision = self.server.db.save_state(state)
            run_id = self.server.db.record_sync(payload)
            self._json({"ok": True, "revision": revision, "syncRunId": run_id})
        except ValueError as exc:
            self._json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
        except Exception as exc:
            self._json({"error": "sync import failed", "detail": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)


def create_server(host: str = "127.0.0.1", port: int = 8765,
                  db_path: str | Path = DEFAULT_DB, root: str | Path = ROOT) -> WorkbenchServer:
    server = WorkbenchServer((host, port), Database(db_path), Path(root))
    # 引导管理器跟着服务一起建：它的「要不要引导」判断是页面打开时第一个要问的。
    # SyncManager 仍然由 main() 挂 —— 有些测试刻意在「没有调度器」的前提下跑。
    server.onboarding = OnboardingManager(server)
    return server


def main() -> int:
    parser = argparse.ArgumentParser(description="学伴本地 API 与页面服务")
    parser.add_argument("--host", default="127.0.0.1", help="默认只监听本机")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--db", default=os.environ.get("LWB_DATABASE", str(DEFAULT_DB)))
    parser.add_argument("--no-open", action="store_true", help="不要自动打开浏览器")
    args = parser.parse_args()

    if not re.fullmatch(r"127\.0\.0\.1|localhost|::1", args.host):
        print("安全保护：本地 Demo 只允许绑定到回环地址。", file=sys.stderr)
        return 2
    server = create_server(args.host, args.port, args.db)
    server.sync_manager = SyncManager(server)
    server.sync_manager.start()
    url = "http://127.0.0.1:%d" % args.port
    print("\n学伴已启动：%s" % url)
    print("数据库：%s" % Path(args.db).resolve())
    print("按 Ctrl+C 停止。\n")
    # 第一次启动时除了自动开页面，再弹一条系统通知。浏览器有可能被最小化、
    # 或者开在别的窗口后面 —— 而「登录」这一步不做，后面就什么数据都没有，
    # 所以值得单独提醒一次。老用户（走过引导的）不会被打扰。
    if server.onboarding and not server.onboarding.is_done():
        threading.Thread(
            target=send_system_notice,
            args=(server.root, "学伴 · 还差一步",
                  "请在打开的页面里登录学习平台，登录后会自动抓取你的课程和通知"),
            daemon=True).start()
    if not args.no_open:
        threading.Timer(0.7, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n正在停止学伴……")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
