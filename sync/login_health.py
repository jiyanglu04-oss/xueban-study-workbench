# -*- coding: utf-8 -*-
"""登录态体检：算出各平台登录态还剩几天。

为什么需要它
------------
超星 / 雨课堂的登录 cookie 带**服务端写死的**过期时间，反复访问并不会续期
（已实测：访问前后 `_uid` 都停在 2026-10-15 03:54，一动不动）。
所以「登录态失效」不是故障，而是必然会到的日程。既然躲不掉，就提前知道——
工作台因此能显示倒计时，定时同步也能在临期/失效时主动提醒。

只读，不碰任何业务数据：把 Cookies 库拷一份到临时目录再读，
避免和正在运行的浏览器抢文件锁。
"""
from __future__ import annotations

import json
import shutil
import sqlite3
import sys
import tempfile
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROFILE = HERE / "state" / "profile"
COOKIES_DB = PROFILE / "Default" / "Network" / "Cookies"

# Chromium 的 expires_utc 是「1601-01-01 起的微秒数」
EPOCH_DIFF = 11644473600

# 默认提前几天开始提醒。超星的 cookie 只给 7~30 天，3 天足够从容安排。
DEFAULT_WARN_DAYS = 3

# 判据 cookie 与 adapters 里的 login_cookies 保持一致：
# 只认「登录之后才会下发」的凭证，游客也有的（ttwid 之类）不能当判据。
PLATFORMS: dict[str, dict] = {
    "chaoxing": {
        "label": "超星学习通",
        "hosts": ("chaoxing.com",),
        "keys": ("_uid", "_d", "vc3", "uf"),
        "note": "登录时下发，固定到期，访问不续期",
    },
    "yuketang": {
        "label": "雨课堂",
        "hosts": ("yuketang.cn",),
        "keys": ("sessionid",),
        "note": "登录时下发，固定到期",
    },
    "icourse163": {
        "label": "中国大学 MOOC",
        "hosts": ("icourse163.org",),
        "keys": ("STUDY_SESS", "STUDY_INFO", "NTESSTUDYSI"),
        # 这家的凭证是会话级 cookie，关浏览器即失效，但每次同步会自动重建，
        # 所以不参与「还剩几天」的倒计时，也不该提醒用户去扫码。
        "session_only": True,
        "note": "会话级凭证，每次同步自动重建，无需关注",
    },
}

STATUS_OK = "ok"
STATUS_EXPIRING = "expiring"
STATUS_EXPIRED = "expired"
STATUS_SESSION = "session"      # 只用会话级 cookie，不参与倒计时
STATUS_UNKNOWN = "unknown"      # 一条判据 cookie 都没有（从没登录过）


# ---------------------------------------------------------------- cookie 读取

def _chrome_ts_to_dt(ts: int | None) -> datetime | None:
    if not ts or ts <= 0:
        return None
    sec = ts / 1000000.0 - EPOCH_DIFF
    if sec <= 0:
        return None
    try:
        return datetime.fromtimestamp(sec)
    except (OSError, OverflowError, ValueError):
        return None


def read_cookies(db_path: Path | None = None) -> list[tuple[str, str, int]]:
    """返回 [(host_key, name, expires_utc), ...]。读不到就返回空列表。"""
    db = Path(db_path) if db_path else COOKIES_DB
    if not db.exists():
        return []
    tmpdir = tempfile.mkdtemp(prefix="wb_cookies_")
    dst = Path(tmpdir) / "Cookies"
    try:
        shutil.copy2(db, dst)
        for ext in ("-wal", "-shm"):
            src = Path(str(db) + ext)
            if src.exists():
                try:
                    shutil.copy2(src, Path(str(dst) + ext))
                except Exception:
                    pass
        con = sqlite3.connect(str(dst))
        try:
            rows = con.execute(
                "SELECT host_key, name, expires_utc FROM cookies").fetchall()
        finally:
            con.close()
        return [(h or "", n or "", int(e or 0)) for h, n, e in rows]
    except Exception:
        return []
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


# ---------------------------------------------------------------- 体检

def check_all(profile: Path | None = None, now: datetime | None = None,
              warn_days: int = DEFAULT_WARN_DAYS,
              db_path: Path | None = None) -> dict:
    """给每个平台判一个状态，返回可直接塞进 sync-data.json 的 dict。"""
    now = now or datetime.now()
    db = db_path if db_path is not None else (
        (Path(profile) / "Default" / "Network" / "Cookies") if profile else COOKIES_DB)
    rows = read_cookies(db)

    platforms: dict[str, dict] = {}
    need_attention: list[str] = []

    for pid, rule in PLATFORMS.items():
        hits = [(n, e) for h, n, e in rows
                if any(k in h for k in rule["hosts"]) and n in rule["keys"]]
        info: dict = {"label": rule["label"], "note": rule.get("note", ""), "credentialFound": bool(hits)}

        if not hits:
            # MOOC 这类平台本来就只有会话级凭证，浏览器一关就没了，
            # 下次同步会重新拿到 —— 这是正常状态，不该报成「需要登录」。
            if rule.get("session_only"):
                info["status"] = STATUS_SESSION
            else:
                info["status"] = STATUS_UNKNOWN
                # 一家平时在用的平台突然一条凭证都没有，等于抓不到数据，
                # 值得提醒一次（例如 cookie 被浏览器清理掉了）。
                need_attention.append(pid)
            info["daysLeft"] = None
            info["expiresAt"] = None
        else:
            dts = [(n, _chrome_ts_to_dt(e)) for n, e in hits]
            dated = [(n, d) for n, d in dts if d]
            if not dated:
                # 全是会话级 cookie
                info["status"] = (STATUS_SESSION if rule.get("session_only")
                                  else STATUS_EXPIRED)
                info["daysLeft"] = None
                info["expiresAt"] = None
            else:
                # 以最早到期的那个为准：只要有一个挂了，这个平台就读不到数据
                name, earliest = min(dated, key=lambda x: x[1])
                left = earliest - now
                days = int(left.total_seconds() // 86400)
                info["expiresAt"] = earliest.isoformat(timespec="seconds")
                info["earliestKey"] = name

                if rule.get("session_only"):
                    info["status"] = STATUS_SESSION
                    info["daysLeft"] = days
                elif days < 0:
                    info["status"] = STATUS_EXPIRED
                    info["daysLeft"] = days
                    need_attention.append(pid)
                elif days <= warn_days:
                    info["status"] = STATUS_EXPIRING
                    info["daysLeft"] = days
                    need_attention.append(pid)
                else:
                    info["status"] = STATUS_OK
                    info["daysLeft"] = days

        platforms[pid] = info

    return {
        "checkedAt": now.isoformat(timespec="seconds"),
        "warnDays": warn_days,
        "platforms": platforms,
        "needAttention": need_attention,
        "summary": summarize(platforms, need_attention),
    }


def summarize(platforms: dict, need_attention: list[str]) -> str:
    """一句话人话描述，直接用于系统通知正文。"""
    if not platforms:
        return "没有读到任何登录态记录。"
    parts = []
    for pid in need_attention:
        p = platforms[pid]
        if p["status"] == STATUS_EXPIRED:
            parts.append("%s 登录已过期" % p["label"])
        elif p["status"] == STATUS_UNKNOWN:
            parts.append("%s 找不到登录凭证" % p["label"])
        else:
            parts.append("%s 登录态还剩 %s 天" % (p["label"], p["daysLeft"]))
    if not parts:
        lefts = ["%s %s 天" % (p["label"], p["daysLeft"])
                 for p in platforms.values()
                 if p["status"] == STATUS_OK and p.get("daysLeft") is not None]
        return "全部正常。" + ("（" + "、".join(lefts) + "）" if lefts else "")
    return "；".join(parts) + "，双击「重新登录.bat」扫码续期即可。"


def label_of(pid: str) -> str:
    return PLATFORMS.get(pid, {}).get("label", pid)


# ---------------------------------------------------------------- 命令行

def _print_report(health: dict) -> None:
    print("登录态体检  %s" % health["checkedAt"])
    print("=" * 62)
    icon = {STATUS_OK: "✓", STATUS_EXPIRING: "!", STATUS_EXPIRED: "✗",
            STATUS_SESSION: "·", STATUS_UNKNOWN: "?"}
    for pid, p in health["platforms"].items():
        if p["status"] == STATUS_SESSION:
            detail = "本次同步自动重建，无需处理"
        elif p["status"] == STATUS_UNKNOWN:
            detail = "找不到登录凭证，需要扫码登录一次"
        elif p["status"] == STATUS_OK:
            detail = "还剩 %s 天   %s" % (p["daysLeft"], (p["expiresAt"] or "")[:10])
        elif p["status"] == STATUS_EXPIRING:
            detail = "还剩 %s 天   %s   ← 建议近日续期" % (
                p["daysLeft"], (p["expiresAt"] or "")[:10])
        else:
            detail = "已过期      请重新登录"
        print("  %s %-14s %s" % (icon.get(p["status"], " "), p["label"], detail))
    print("=" * 62)
    print("  " + health["summary"])


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    as_json = "--json" in argv
    warn = DEFAULT_WARN_DAYS
    if "--warn-days" in argv:
        try:
            warn = int(argv[argv.index("--warn-days") + 1])
        except (IndexError, ValueError):
            pass
    health = check_all(warn_days=warn)
    if as_json:
        print(json.dumps(health, ensure_ascii=False, indent=2))
    else:
        _print_report(health)
    return 0


if __name__ == "__main__":
    sys.exit(main())
