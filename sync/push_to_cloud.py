"""把本机识别出的待办推送到云端，供微信小程序读取和提醒。

设计上的两条硬边界：
  1. 本机**不持有**小程序 AppSecret。那条路要拿最高权限凭证放在电脑上，
     泄露等于别人能冒充你的小程序调任何接口。改成「云函数 HTTP 入口 + 共享密钥」，
     最坏情况只是有人往待办里塞几条垃圾数据。
  2. 推送失败**绝不影响**本机同步。抓不到、推不上去，都只是这一轮少了手机提醒，
     本机工作台该有的数据一条都不会少。

用法：
    python sync/push_to_cloud.py              # 正常推送
    python sync/push_to_cloud.py --dry-run    # 只打印要推什么，不真发
    python sync/push_to_cloud.py --force      # 内容没变也重推一次
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "sync" / "push_config.json"
SNAPSHOT = ROOT / "sync" / "sync-data.json"
STATE = ROOT / "sync" / "state" / "push-state.json"

TIMEOUT = 20
MAX_ITEMS = 200
MAX_MSGS = 100
# 通知只推最近这么多天的。更早的都是上学期的事了，翻出来只会让列表变长。
MSG_WINDOW_DAYS = 45
TEMPLATE = {
    "baseUrl": "",
    "ingestKey": "",
    "bindCode": "",
    "enabled": False,
    "note": "填完三个值并把 enabled 改成 true 就会自动推送。baseUrl 见《weapp/配置指引.md》",
}


def log(msg: str) -> None:
    """pythonw 下没有 stdout，所有打印都要能安全失败。"""
    try:
        print(msg, flush=True)
    except Exception:
        pass


def load_config() -> dict:
    if not CONFIG.exists():
        CONFIG.write_text(
            json.dumps(TEMPLATE, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        log("已创建 sync/push_config.json，请填好里面的三个值后再运行。")
        return {}
    try:
        cfg = json.loads(CONFIG.read_text(encoding="utf-8-sig"))
    except Exception as e:
        log("push_config.json 读不动（%s），本轮跳过推送。" % e)
        return {}
    return cfg if isinstance(cfg, dict) else {}


def read_todos_from_snapshot() -> list:
    if not SNAPSHOT.exists():
        return []
    try:
        data = json.loads(SNAPSHOT.read_text(encoding="utf-8-sig"))
    except Exception as e:
        log("sync-data.json 读不动（%s）。" % e)
        return []
    rows = data.get("todos")
    return [r for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []


def read_todos_from_server() -> list:
    """后端在跑的话顺手把页面里手加的待办也带上。拿不到就安静跳过。"""
    try:
        req = urllib.request.Request("http://127.0.0.1:8765/api/state")
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception:
        return []
    rows = (data or {}).get("todos")
    return [r for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []


def to_epoch(due, now: datetime):
    """把待办里的 due 换成毫秒时间戳。

    本机存的 due 是「本地墙上时间」的 ISO 串（如 2026-10-20T18:00），
    云端需要的是绝对时刻。这里按东八区解释 —— 用户就在东八区，
    而且这个串本来就是按本机时区生成出来的。
    """
    if due is None or due == "":
        return None
    if isinstance(due, (int, float)):
        v = float(due)
        return int(v * 1000) if v < 1e11 else int(v)
    s = str(due).strip()
    if not s:
        return None
    s = s.replace("/", "-").replace("年", "-").replace("月", "-").replace("日", " ")
    s = s.strip()
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(s, fmt)
            return int(dt.timestamp() * 1000)
        except ValueError:
            continue
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    return int(dt.timestamp() * 1000)


def merge(snapshot: list, server: list) -> list:
    """两份来源按 id 合并，服务端版本覆盖快照。

    服务端（本机工作台的库）才是「用户改过的状态」的唯一真源：你在页面里勾掉的待办
    在快照里 still 是未完成，用快照推上去等于把它重新推回手机。
    服务端没在跑时它返回空列表，这时快照原样保留 —— 不会因为读不到就把待办丢掉。
    """
    out: dict[str, dict] = {}
    for rows in (snapshot, server):
        for r in rows:
            rid = str(r.get("id") or "").strip()
            if rid:
                out[rid] = r
    return list(out.values())


def build_payload(todos: list) -> list:
    now = datetime.now()
    items = []
    for t in todos:
        rid = str(t.get("id") or "").strip()
        if not rid:
            continue
        if t.get("done"):
            continue  # 已完成的不需要再提醒
        title = str(t.get("title") or "").strip()
        if not title:
            continue
        items.append(
            {
                "id": rid,
                "title": title[:60],
                "course": str(t.get("course") or "")[:40],
                "platform": str(t.get("source") or t.get("platform") or "")[:20],
                "priority": int(t.get("priority") or 2),
                "url": str(t.get("url") or ""),
                "dueAt": to_epoch(t.get("due") or t.get("dueAt"), now),
            }
        )
    # 有截止时间的排前面，其余按优先级。这样小程序首页天然是「最急的在上面」
    items.sort(key=lambda x: (x["dueAt"] is None, x["dueAt"] or 0, x["priority"]))
    return items[:MAX_ITEMS]


def signature(items: list) -> str:
    raw = json.dumps(items, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


# ---- 通知（不只是待办）----

_WS = re.compile(r"\s+")


def read_messages_from_snapshot() -> list:
    if not SNAPSHOT.exists():
        return []
    try:
        data = json.loads(SNAPSHOT.read_text(encoding="utf-8-sig"))
    except Exception:
        return []
    rows = data.get("messages")
    return [r for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []


def _parse_time(v):
    """snapshot 里的 time 是带时区的 ISO 串（如 2026-09-20T20:59:36+08:00）。"""
    try:
        dt = datetime.fromisoformat(str(v))
    except (TypeError, ValueError):
        return None
    # 本机就在东八区，去掉时区后仍然是本地墙上时间，可以直接比较
    return dt.replace(tzinfo=None) if dt.tzinfo else dt


def build_messages(msgs: list, now: datetime | None = None) -> list:
    """把通知整理成可以推给小程序的形式，按时间倒序。

    正文要截断：订阅消息和小程序列表都只用得上前一两行，
    整段推上去除了让请求变大没有任何好处。
    """
    now = now or datetime.now()
    floor = now - timedelta(days=MSG_WINDOW_DAYS)
    items = []
    for m in msgs:
        mid = str(m.get("id") or "").strip()
        if not mid:
            continue
        pub = _parse_time(m.get("time"))
        if pub is None or pub < floor:
            continue
        items.append(
            {
                "id": mid,
                "title": str(m.get("title") or "")[:60],
                "course": str(m.get("course") or "")[:40],
                "platform": str(m.get("platform") or "")[:20],
                "kind": str(m.get("kind") or "notice")[:20],
                "content": _WS.sub(" ", str(m.get("content") or "")).strip()[:120],
                "url": str(m.get("url") or ""),
                "time": str(m.get("time") or ""),
            }
        )
    items.sort(key=lambda x: x["time"], reverse=True)
    return items[:MAX_MSGS]


def post(url: str, body: dict, key: str):
    """回环/直连都不能走系统代理 —— 本机装了代理软件时会把请求劫持成 502。"""
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "X-Ingest-Key": key,
            "User-Agent": "study-workbench-push/1.0",
        },
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(req, timeout=TIMEOUT) as resp:
            text = resp.read().decode("utf-8", "replace")
            try:
                return True, json.loads(text)
            except ValueError:
                return True, {"raw": text[:300]}
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:300]
        return False, {"error": "HTTP %s" % e.code, "detail": detail}
    except Exception as e:
        return False, {"error": str(e)}


def run(dry_run: bool = False, force: bool = False) -> dict:
    """执行一次推送。

    返回 {ok, code, message, count}，**任何情况下都不抛异常** ——
    调用方是同步主流程，推送只是额外通道，不能因为它把整轮同步带崩。
    """
    try:
        return _run(dry_run, force)
    except Exception as e:  # pragma: no cover - 兜底
        return {"ok": False, "code": 3, "message": "推送异常：%r" % e, "count": 0}


def _run(dry_run: bool, force: bool) -> dict:
    cfg = load_config()
    if not cfg:
        return {"ok": False, "code": 1, "message": "还没配 push_config.json", "count": 0}
    if not cfg.get("enabled"):
        return {"ok": False, "code": 0, "message": "推送未启用（enabled=false），已跳过", "count": 0}

    base = str(cfg.get("baseUrl") or "").strip()
    key = str(cfg.get("ingestKey") or "").strip()
    code = str(cfg.get("bindCode") or "").strip().upper()
    missing = [n for n, v in (("baseUrl", base), ("ingestKey", key), ("bindCode", code)) if not v]
    if missing:
        return {"ok": False, "code": 1,
                "message": "push_config.json 还缺：%s" % "、".join(missing), "count": 0}

    items = build_payload(merge(read_todos_from_snapshot(), read_todos_from_server()))
    all_msgs = build_messages(read_messages_from_snapshot())

    try:
        prev = json.loads(STATE.read_text(encoding="utf-8-sig"))
    except Exception:
        prev = {}

    # 待办：全量比对，内容没变就不重推（云端是 upsert，重复推只是白跑请求）
    sig = signature(items)
    todos_changed = bool(force) or prev.get("signature") != sig

    # 通知：只推本机还没推过的那些。通知数量是待办的几十倍，全量重推会让
    # 云函数每条都做一次数据库写，很容易撞上执行超时。
    pushed_ids = set(str(x) for x in (prev.get("msgIds") or []))
    new_msgs = all_msgs if force else [m for m in all_msgs if m["id"] not in pushed_ids]

    log("准备推送：待办 %d 条（%s）、通知 %d 条（%s）。"
        % (len(items), "有变化" if todos_changed else "无变化，跳过",
           len(new_msgs), "全部" if force else "新增"))
    for it in items[:10]:
        when = ""
        if it["dueAt"]:
            when = datetime.fromtimestamp(it["dueAt"] / 1000).strftime("%m-%d %H:%M")
        log("   · %s%s" % (it["title"], ("  @ " + when) if when else ""))
    for m in new_msgs[:5]:
        log("   · [通知] %s" % m["title"])
    if len(new_msgs) > 5:
        log("   · [通知] …还有 %d 条" % (len(new_msgs) - 5))

    if dry_run:
        return {"ok": True, "code": 0,
                "message": "dry-run：没有真的发送", "count": len(items)}

    if not todos_changed and not new_msgs:
        return {"ok": True, "code": 0, "message": "内容与上次一致，跳过推送", "count": len(items)}

    body = {
        "key": key,
        "bindCode": code,
        # 待办没变就传空数组 —— ingest 那边空数组表示「这次不动待办」，
        # 不会把云端已有的删掉，也不会重写一遍
        "todos": items if todos_changed else [],
        "messages": new_msgs,
    }
    ok, res = post(base, body, key)

    saved_ids = list(pushed_ids | {m["id"] for m in new_msgs}) if ok else list(pushed_ids)
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(
        json.dumps(
            {
                "at": datetime.now().isoformat(timespec="seconds"),
                "ok": ok,
                "count": len(items),
                "msgCount": len(new_msgs),
                "signature": sig if (ok and todos_changed) else prev.get("signature", ""),
                "msgIds": saved_ids[-500:],  # 只会用来做「推过没有」的判断，留最近的就够了
                "response": res,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    if ok:
        return {"ok": True, "code": 0,
                "message": "已推送到手机：%s" % res.get("message", res), "count": len(items)}
    return {"ok": False, "code": 2, "message": "推送失败：%s" % res, "count": len(items)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="把本机待办推送到小程序云端")
    ap.add_argument("--dry-run", action="store_true", help="只打印，不发送")
    ap.add_argument("--force", action="store_true", help="内容没变也重推")
    args = ap.parse_args(argv)
    r = run(dry_run=args.dry_run, force=args.force)
    log(r["message"])
    return r["code"]


if __name__ == "__main__":
    sys.exit(main())
