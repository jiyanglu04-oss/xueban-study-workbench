from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator


SCHEMA_VERSION = 1


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Database:
    """SQLite persistence for the single-user local workbench.

    The browser still owns the shape of the application state. The database
    materialises its important collections into separate tables so the server
    can query them without treating the whole product as one opaque JSON blob.
    """

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.migrate()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        con = sqlite3.connect(self.path, timeout=10)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA foreign_keys = ON")
        con.execute("PRAGMA journal_mode = WAL")
        try:
            yield con
            con.commit()
        except Exception:
            con.rollback()
            raise
        finally:
            con.close()

    def migrate(self) -> None:
        with self.connect() as con:
            con.executescript(
                """
                CREATE TABLE IF NOT EXISTS app_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS singleton_state (
                    name TEXT PRIMARY KEY,
                    data_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS courses (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    platform TEXT NOT NULL DEFAULT '',
                    sync_key TEXT NOT NULL DEFAULT '',
                    data_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS course_sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    course_id TEXT NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
                    weekday INTEGER NOT NULL,
                    start_section INTEGER NOT NULL,
                    section_count INTEGER NOT NULL,
                    weeks TEXT NOT NULL DEFAULT '',
                    room TEXT NOT NULL DEFAULT ''
                );

                CREATE TABLE IF NOT EXISTS todos (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    due TEXT NOT NULL DEFAULT '',
                    priority INTEGER NOT NULL DEFAULT 2,
                    done INTEGER NOT NULL DEFAULT 0,
                    source TEXT NOT NULL DEFAULT 'manual',
                    data_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_todos_due ON todos(done, due);

                CREATE TABLE IF NOT EXISTS messages (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    published_at TEXT NOT NULL DEFAULT '',
                    platform TEXT NOT NULL DEFAULT 'other',
                    kind TEXT NOT NULL DEFAULT 'notice',
                    is_read INTEGER NOT NULL DEFAULT 0,
                    data_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_messages_time ON messages(published_at DESC);

                CREATE TABLE IF NOT EXISTS platform_connections (
                    platform_key TEXT PRIMARY KEY,
                    status TEXT NOT NULL DEFAULT 'never',
                    account_label TEXT NOT NULL DEFAULT '',
                    last_sync TEXT,
                    last_error TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS sync_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    started_at TEXT NOT NULL,
                    finished_at TEXT NOT NULL,
                    status TEXT NOT NULL,
                    summary_json TEXT NOT NULL,
                    error TEXT NOT NULL DEFAULT ''
                );
                """
            )
            con.execute(
                "INSERT INTO app_meta(key, value) VALUES('schema_version', ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (str(SCHEMA_VERSION),),
            )

    @staticmethod
    def _json(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))

    @staticmethod
    def _load(value: str, fallback: Any) -> Any:
        try:
            return json.loads(value)
        except (TypeError, json.JSONDecodeError):
            return fallback

    def has_state(self) -> bool:
        with self.connect() as con:
            return con.execute(
                "SELECT 1 FROM singleton_state WHERE name='settings'"
            ).fetchone() is not None

    def save_state(self, state: dict[str, Any]) -> str:
        if not isinstance(state, dict):
            raise ValueError("state must be an object")
        now = utc_now()
        revision = hashlib.sha256(self._json(state).encode("utf-8")).hexdigest()[:16]

        with self.connect() as con:
            for name in ("profile", "settings", "cet", "meta"):
                value = state.get(name, {})
                con.execute(
                    "INSERT INTO singleton_state(name, data_json, updated_at) VALUES(?,?,?) "
                    "ON CONFLICT(name) DO UPDATE SET data_json=excluded.data_json, updated_at=excluded.updated_at",
                    (name, self._json(value), now),
                )

            con.execute("DELETE FROM course_sessions")
            con.execute("DELETE FROM courses")
            for course in state.get("courses", []):
                if not isinstance(course, dict):
                    continue
                cid = str(course.get("id") or course.get("syncKey") or "").strip()
                if not cid:
                    continue
                compact = dict(course)
                sessions = compact.pop("sessions", [])
                con.execute(
                    "INSERT INTO courses(id,name,platform,sync_key,data_json,updated_at) VALUES(?,?,?,?,?,?)",
                    (cid, str(course.get("name") or "(未命名课程)"),
                     str(course.get("platform") or ""), str(course.get("syncKey") or ""),
                     self._json(compact), now),
                )
                for session in sessions if isinstance(sessions, list) else []:
                    if not isinstance(session, dict):
                        continue
                    con.execute(
                        "INSERT INTO course_sessions(course_id,weekday,start_section,section_count,weeks,room) "
                        "VALUES(?,?,?,?,?,?)",
                        (cid, int(session.get("day") or 1), int(session.get("start") or 1),
                         int(session.get("len") or 1), str(session.get("weeks") or ""),
                         str(session.get("room") or "")),
                    )

            con.execute("DELETE FROM todos")
            for todo in state.get("todos", []):
                if not isinstance(todo, dict) or not todo.get("id"):
                    continue
                con.execute(
                    "INSERT INTO todos(id,title,due,priority,done,source,data_json,updated_at) "
                    "VALUES(?,?,?,?,?,?,?,?)",
                    (str(todo["id"]), str(todo.get("title") or "(未命名)"),
                     str(todo.get("due") or ""), int(todo.get("priority") or 2),
                     1 if todo.get("done") else 0, str(todo.get("source") or "manual"),
                     self._json(todo), now),
                )

            con.execute("DELETE FROM messages")
            for message in state.get("messages", []):
                if not isinstance(message, dict) or not message.get("id"):
                    continue
                con.execute(
                    "INSERT INTO messages(id,title,published_at,platform,kind,is_read,data_json,updated_at) "
                    "VALUES(?,?,?,?,?,?,?,?)",
                    (str(message["id"]), str(message.get("title") or "(无标题)"),
                     str(message.get("time") or ""), str(message.get("platform") or "other"),
                     str(message.get("kind") or "notice"), 1 if message.get("read") else 0,
                     self._json(message), now),
                )

            incoming = [c for c in (state.get("meta", {}).get("connections") or [])
                        if isinstance(c, dict) and c.get("key")]
            for connection in incoming:
                self._upsert_connection(con, connection, now)
            # 清掉这次没出现的平台。否则不再参与自动同步的平台（比如默认不跑的
            # 「教务」）会一直挂着很久以前的「已连接」，平台入口页看起来像同步过。
            # 只在载荷确实带了连接列表时才清，避免部分更新把整表抹掉。
            if incoming:
                keep = [str(c["key"]) for c in incoming]
                con.execute(
                    "DELETE FROM platform_connections WHERE platform_key NOT IN (%s)"
                    % ",".join("?" * len(keep)), keep)

            con.execute(
                "INSERT INTO app_meta(key,value) VALUES('revision',?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (revision,),
            )
        return revision

    def load_state(self) -> dict[str, Any] | None:
        with self.connect() as con:
            rows = con.execute("SELECT name,data_json FROM singleton_state").fetchall()
            if not rows:
                return None
            state = {row["name"]: self._load(row["data_json"], {}) for row in rows}

            courses: list[dict[str, Any]] = []
            for row in con.execute("SELECT id,data_json FROM courses ORDER BY rowid"):
                course = self._load(row["data_json"], {})
                course["id"] = row["id"]
                course["sessions"] = [
                    {
                        "day": s["weekday"], "start": s["start_section"],
                        "len": s["section_count"], "weeks": s["weeks"], "room": s["room"],
                    }
                    for s in con.execute(
                        "SELECT weekday,start_section,section_count,weeks,room "
                        "FROM course_sessions WHERE course_id=? ORDER BY weekday,start_section", (row["id"],)
                    )
                ]
                courses.append(course)

            state["courses"] = courses
            # done / read 这两个「用户自己的状态」以**表列为准**，不能只信 data_json。
            # 否则列和 data_json 会各说各话：dashboard() 是按 is_read 列统计未读数的，
            # 而消息列表读的是 data_json —— 一旦两者不一致，顶部的未读数和列表就对不上，
            # 而且任何直接改列的修复动作都会「看起来生效、实际被下一次同步抹掉」。
            state["todos"] = []
            for row in con.execute("SELECT data_json,done FROM todos ORDER BY rowid"):
                todo = self._load(row["data_json"], {})
                todo["done"] = bool(row["done"])
                state["todos"].append(todo)
            state["messages"] = []
            for row in con.execute("SELECT data_json,is_read FROM messages ORDER BY rowid"):
                message = self._load(row["data_json"], {})
                message["read"] = bool(row["is_read"])
                state["messages"].append(message)
            state.setdefault("v", 1)
            # connections 表只存「连上没连上」，而登录态到期信息（还剩几天、
            # 什么时候失效）只存在于 meta 快照里。这里直接把表结果盖上去的话，
            # 工作台每次重启都会丢掉倒计时 —— 所以以表为准，再把快照里的
            # 到期字段补回来。
            meta = state.setdefault("meta", {})
            saved = {c.get("key"): c for c in (meta.get("connections") or [])
                     if isinstance(c, dict) and c.get("key")}
            fresh = self.list_connections(con)
            for conn in fresh:
                old = saved.get(conn.get("key")) or {}
                for field in ("expiresAt", "daysLeft", "loginStatus"):
                    if old.get(field) is not None:
                        conn[field] = old[field]
            meta["connections"] = fresh
            return state

    @staticmethod
    def _upsert_connection(con: sqlite3.Connection, item: dict[str, Any], now: str) -> None:
        con.execute(
            "INSERT INTO platform_connections(platform_key,status,account_label,last_sync,last_error,updated_at) "
            "VALUES(?,?,?,?,?,?) ON CONFLICT(platform_key) DO UPDATE SET "
            "status=excluded.status,account_label=excluded.account_label,last_sync=excluded.last_sync," 
            "last_error=excluded.last_error,updated_at=excluded.updated_at",
            (str(item["key"]), str(item.get("status") or "never"),
             str(item.get("accountLabel") or ""), item.get("lastSync"),
             str(item.get("error") or ""), now),
        )

    def list_connections(self, con: sqlite3.Connection | None = None) -> list[dict[str, Any]]:
        def rows(db: sqlite3.Connection) -> list[dict[str, Any]]:
            return [
                {"key": row["platform_key"], "status": row["status"],
                 "accountLabel": row["account_label"], "lastSync": row["last_sync"],
                 "error": row["last_error"]}
                for row in db.execute(
                    "SELECT platform_key,status,account_label,last_sync,last_error "
                    "FROM platform_connections ORDER BY platform_key"
                )
            ]
        if con is not None:
            return rows(con)
        with self.connect() as db:
            return rows(db)

    def dashboard(self) -> dict[str, Any]:
        now = datetime.now().astimezone().isoformat(timespec="minutes")
        with self.connect() as con:
            counts = {
                "courses": con.execute("SELECT COUNT(*) FROM courses").fetchone()[0],
                "openTodos": con.execute("SELECT COUNT(*) FROM todos WHERE done=0").fetchone()[0],
                "overdueTodos": con.execute(
                    "SELECT COUNT(*) FROM todos WHERE done=0 AND due<>'' AND due<?", (now,)
                ).fetchone()[0],
                "unreadMessages": con.execute("SELECT COUNT(*) FROM messages WHERE is_read=0").fetchone()[0],
            }
            urgent = [self._load(row["data_json"], {}) for row in con.execute(
                "SELECT data_json FROM todos WHERE done=0 ORDER BY CASE WHEN due='' THEN 1 ELSE 0 END,due LIMIT 8"
            )]
            return {"counts": counts, "urgentTodos": urgent, "generatedAt": utc_now()}

    def record_sync(self, payload: dict[str, Any]) -> int:
        now = utc_now()
        connections = payload.get("connections", [])
        with self.connect() as con:
            for item in connections if isinstance(connections, list) else []:
                if isinstance(item, dict) and item.get("key"):
                    self._upsert_connection(con, item, now)
            summary = {
                "courses": len(payload.get("courses", [])),
                "messages": len(payload.get("messages", [])),
                "todos": len(payload.get("todos", [])),
                "note": payload.get("note", ""),
            }
            cur = con.execute(
                "INSERT INTO sync_runs(started_at,finished_at,status,summary_json,error) VALUES(?,?,?,?,?)",
                (str(payload.get("startedAt") or payload.get("syncedAt") or now),
                 str(payload.get("syncedAt") or now), str(payload.get("status") or "success"),
                 self._json(summary), str(payload.get("error") or "")),
            )
            return int(cur.lastrowid)

    def list_sync_runs(self, limit: int = 20) -> list[dict[str, Any]]:
        limit = min(max(int(limit), 1), 100)
        with self.connect() as con:
            return [
                {"id": row["id"], "startedAt": row["started_at"], "finishedAt": row["finished_at"],
                 "status": row["status"], "summary": self._load(row["summary_json"], {}),
                 "error": row["error"]}
                for row in con.execute(
                    "SELECT * FROM sync_runs ORDER BY id DESC LIMIT ?", (limit,)
                )
            ]

    def revision(self) -> str:
        with self.connect() as con:
            row = con.execute("SELECT value FROM app_meta WHERE key='revision'").fetchone()
            return row["value"] if row else ""

