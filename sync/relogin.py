# -*- coding: utf-8 -*-
"""只做「重新登录」这一件事：给需要续期的平台弹一次扫码窗口，扫完就走。

为什么单独做一个入口
--------------------
超星 / 雨课堂的登录 cookie 带**服务端写死的**到期时间（实测：反复访问也纹丝不动，
超星 2026-10-15、雨课堂 2026-10-21）。也就是说，登录态每 2~4 周必然要人工续一次，
这是躲不掉的。既然躲不掉，就把它做成最省事的一步：

  * 不动数据 —— 不抓取、不写 sync-data.json、不碰数据库，只更新登录态；
  * 不打扰健康的平台 —— 只对状态是 expiring / expired / unknown 的弹窗；
  * 几秒钟完事 —— 不用陪跑一次 26 秒的全量抓取。

用法：
    python sync/relogin.py              # 只处理需要续期的平台
    python sync/relogin.py --all        # 强制全部重新登录
    python sync/relogin.py --only chaoxing
"""
from __future__ import annotations

import argparse
import asyncio
import importlib.util
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import login_health  # noqa: E402

NEED_LOGIN = {"expiring", "expired", "unknown"}


def load_sync_module():
    """按路径加载 sync.py。

    不能直接 `import sync` —— 包目录也叫 sync，`sync/sync.py` 会反过来把包遮住，
    这是之前踩过的坑。按文件路径显式加载最稳。
    """
    spec = importlib.util.spec_from_file_location("wb_sync_mod", HERE / "sync.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["wb_sync_mod"] = mod
    spec.loader.exec_module(mod)
    return mod


def pick_targets(force_all: bool, only: str | None, health: dict) -> list[str]:
    order = ["chaoxing", "yuketang", "icourse163"]
    if only:
        return [only] if only in order else []
    if force_all:
        return order
    ids = health.get("needAttention") or []
    # 会话级凭证（MOOC）不需要人工登录，体检已经排除，这里只是双保险
    return [k for k in order if k in ids]


async def run(targets: list[str], syncmod) -> dict:
    from playwright.async_api import async_playwright
    from adapters import BY_KEY

    log = syncmod.log
    results: dict[str, bool] = {}
    async with async_playwright() as p:
        ctx = await syncmod.launch_browser(p, log, headless=False)
        try:
            for key in targets:
                label = syncmod.ADAPTER_LABEL.get(key, key)
                log.head("重新登录 · %s" % label)
                adapter = BY_KEY[key](ctx, log, debug=False, dry=False, interactive=True)
                try:
                    results[key] = bool(await adapter.ensure_login(force=True))
                except Exception as e:
                    log("[%s] 登录过程出错：%r" % (label, e), level="err")
                    results[key] = False
        finally:
            try:
                await ctx.close()
            except Exception:
                pass
    return results


def main() -> int:
    ap = argparse.ArgumentParser(description="只处理登录态续期")
    ap.add_argument("--all", action="store_true", help="强制全部平台重新登录")
    ap.add_argument("--only", help="只处理某一个平台")
    args = ap.parse_args()

    syncmod = load_sync_module()
    log = syncmod.log

    log.head("登录态体检（先看看谁需要续期）")
    health = login_health.check_all()
    for _pid, info in health["platforms"].items():
        st = info.get("status")
        if st == "ok":
            log("%-16s 有效，还剩 %s 天" % (info["label"], info["daysLeft"]))
        elif st == "expiring":
            log("%-16s 快到期，还剩 %s 天" % (info["label"], info["daysLeft"]), level="warn")
        elif st == "expired":
            log("%-16s 已过期" % info["label"], level="warn")
        elif st == "unknown":
            log("%-16s 没有登录凭证" % info["label"], level="warn")
        else:
            log("%-16s 会话级凭证，不需要人工登录" % info["label"], level="dim")

    targets = pick_targets(args.all, args.only, health)
    if not targets:
        log("")
        log("所有平台的登录态都还没到期，这次不用扫码。", level="ok")
        log("（超星 / 雨课堂的到期时间可以在平台入口页看到倒计时）")
        log("总耗时 %s。" % log.elapsed())
        return 0

    log("")
    log("需要重新登录：%s" % "、".join(syncmod.ADAPTER_LABEL.get(t, t) for t in targets))
    log("接下来会弹出浏览器窗口，请在窗口里完成扫码（不需要按任何键）。")

    results = asyncio.run(run(targets, syncmod))

    log.head("结果")
    for key, ok in results.items():
        log("%-16s %s" % (syncmod.ADAPTER_LABEL.get(key, key),
                          "登录成功 ✓" if ok else "未完成 ✗"), level="ok" if ok else "warn")

    after = login_health.check_all()
    log("")
    log("续期后的登录态：%s" % after["summary"])
    log("总耗时 %s。" % log.elapsed())
    return 0 if all(results.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
