# -*- coding: utf-8 -*-
"""登录态提醒策略：决定「什么时候该打扰用户一次」。

体检本身（login_health）只是算出还剩几天；这里管的是**要不要弹通知**。
没有策略的话，一天两次同步会变成一天两次弹窗，用户很快就学会无视它，
提醒就失效了。所以规则刻意保守：

    1. 状态发生变化时立刻提醒（正常 -> 临期、临期 -> 失效）；
    2. 状态没变就不重复——但「已经失效」是实质问题（这个平台一直抓不到数据），
       所以跨天之后再提醒一次，每天最多一次；
    3. 一切正常时清空记录，下次出问题能立刻提醒。

记录放在 state/notify-history.json，只存 signature 和日期，不存隐私内容。
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import notifier  # noqa: E402

STATE = HERE / "state"
HISTORY = STATE / "notify-history.json"

STATUS_EXPIRED = "expired"
STATUS_UNKNOWN = "unknown"
STATUS_EXPIRING = "expiring"


def signature(health: dict) -> str:
    """把「哪些平台需要关注、分别什么状态」压成一个字符串，用来判断有没有变化。"""
    ids = health.get("needAttention") or []
    platforms = health.get("platforms") or {}
    return ",".join(
        "%s:%s" % (pid, (platforms.get(pid) or {}).get("status", "?"))
        for pid in sorted(ids)
    )


def read_history() -> dict:
    try:
        return json.loads(HISTORY.read_text(encoding="utf-8"))
    except Exception:
        return {}


def write_history(data: dict) -> None:
    try:
        STATE.mkdir(parents=True, exist_ok=True)
        HISTORY.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                           encoding="utf-8")
    except Exception:
        pass


def decide(health: dict, history: dict, now: datetime | None = None) -> tuple[bool, str]:
    """返回 (要不要发通知, 原因)。原因用于写日志，方便排查「为什么没提醒我」。"""
    now = now or datetime.now()
    today = now.strftime("%Y-%m-%d")
    sig = signature(health)

    if not sig:
        return False, "全部正常，不用提醒"

    last_sig = history.get("signature") or ""
    last_day = history.get("date") or ""

    if sig != last_sig:
        return True, "登录态状态有变化"

    if last_day != today:
        # 状态没变但跨天了。只有「已经失效」才值得再催一次 —— 它意味着这个
        # 平台一直在静默地抓不到数据，用户多半是没看到上一条通知。
        # 「找不到凭证」不重复催：那也可能只是用户根本不用这个平台，
        # 天天提醒只会训练出「看到通知就划掉」的习惯，反而让提醒失效。
        ids = health.get("needAttention") or []
        platforms = health.get("platforms") or {}
        hard = [p for p in ids
                if (platforms.get(p) or {}).get("status") == STATUS_EXPIRED]
        if hard:
            return True, "问题仍未处理（%s）" % "、".join(hard)

    return False, "今天已经提醒过同样的内容，不重复打扰"


def maybe_notify(health: dict, now: datetime | None = None) -> dict:
    """按策略决定是否弹系统通知。任何时候都不该抛异常影响同步主流程。"""
    now = now or datetime.now()
    out = {"sent": False, "reason": "", "signature": signature(health)}
    try:
        history = read_history()
        should, reason = decide(health, history, now)
        out["reason"] = reason
        if not should:
            if not signature(health):
                write_history({})   # 恢复正常，清掉记录
            return out

        title = "学伴 · 需要你扫码登录"
        body = health.get("summary") or "有平台登录态需要处理。"
        ok = notifier.send(title, body)
        out["sent"] = bool(ok)
        if ok:
            write_history({
                "signature": signature(health),
                "date": now.strftime("%Y-%m-%d"),
                "at": now.isoformat(timespec="seconds"),
                "body": body,
            })
        else:
            out["reason"] = reason + "（通知发送失败，可能是系统屏蔽）"
    except Exception as e:  # 宁可静默失败，也不能连累同步
        out["reason"] = "提醒模块异常：%r" % e
    return out


if __name__ == "__main__":
    import login_health  # noqa: E402
    h = login_health.check_all()
    print(json.dumps(maybe_notify(h), ensure_ascii=False, indent=2))
