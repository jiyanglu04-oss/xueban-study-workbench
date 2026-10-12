#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
构建单文件学伴。

把 src/template.html + src/style.css + src/js/*.js 内联成
一个可以直接双击打开、零依赖的 HTML 文件。

用法：
    python build.py
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
OUT = ROOT / "学伴.html"

SYNC_RE = re.compile(
    r'(<script id="sync-payload" type="application/json">)(.*?)(</script>)',
    re.S,
)


def read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def keep_injected_payload(built: str) -> str:
    """把现有 HTML 里已经注入的同步数据搬到新构建的 HTML 上。

    ⚠️ 不这么做的话，每次 `python build.py` 都会把「一键同步数据.bat」抓到的
    通知/待办抹掉 —— 因为 build 是从 src/ 重新拼的，src 里那个槽是空的。
    结果就是：改个样式、重新构建一次，单文件模式下的数据就没了。
    """
    if not OUT.exists():
        return built
    try:
        old = read(OUT)
    except OSError:
        return built
    m = SYNC_RE.search(old)
    if not m:
        return built
    block = m.group(2).strip()
    if not block or block in ("{}", "null"):
        return built
    new, n = SYNC_RE.subn(
        lambda _: m.group(1) + "\n" + block + "\n" + m.group(3), built, count=1)
    if n:
        print("  已保留原有同步数据（%d 字节）" % len(block))
    return new or built


def main() -> int:
    template = read(SRC / "template.html")
    css = read(SRC / "style.css")

    js_files = sorted((SRC / "js").glob("*.js"))
    if not js_files:
        print("错误：src/js 下没有找到任何 js 文件", file=sys.stderr)
        return 1

    js_parts = []
    for f in js_files:
        js_parts.append("/* ---------- %s ---------- */\n%s" % (f.name, read(f)))
    js = "\n".join(js_parts)

    # 用函数式替换，避免反斜杠 / $ 被当成转义序列
    out = re.sub(r"/\*__CSS__\*/", lambda m: css, template, count=1)
    out = re.sub(r"/\*__JS__\*/", lambda m: js, out, count=1)

    if "__CSS__" in out or "__JS__" in out:
        print("错误：占位符替换失败", file=sys.stderr)
        return 1

    out = keep_injected_payload(out)
    OUT.write_text(out, encoding="utf-8")

    kb = len(out.encode("utf-8")) / 1024
    print("构建成功 -> %s" % OUT)
    print("  样式 %d 字节 | 脚本 %d 字节（%d 个模块）| 总计 %.1f KB"
          % (len(css.encode("utf-8")), len(js.encode("utf-8")), len(js_files), kb))
    return 0


if __name__ == "__main__":
    sys.exit(main())
