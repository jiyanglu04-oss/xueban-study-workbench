# -*- coding: utf-8 -*-
"""微信群消息抓取的测试。

全部用**固定数据**，不依赖真实微信、不截屏、不 OCR —— 这样跑测试不会打扰用户，
也能在没装微信的机器上跑。
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for p in (str(ROOT), str(ROOT / "sync")):
    if p not in sys.path:
        sys.path.insert(0, p)

import wx_chat as CH       # noqa: E402
import wx_watch as W       # noqa: E402
from wx_ocr import TextLine  # noqa: E402


def L(x: float, y: float, text: str, w: float = 60, h: float = 20) -> TextLine:
    return TextLine(x, y, x + w, y + h, text)


# --------------------------------------------------------------------------
# 噪声过滤
# --------------------------------------------------------------------------

class TestNoiseFilter(unittest.TestCase):
    def test_single_char_is_noise(self):
        self.assertTrue(W._looks_like_noise("生"))
        self.assertTrue(W._looks_like_noise("0"))

    def test_symbol_only_is_noise(self):
        self.assertTrue(W._looks_like_noise("..."))
        self.assertTrue(W._looks_like_noise("——"))

    def test_repeated_same_char_is_noise(self):
        # 二维码常被读成"回：回"这种同一个字反复出现
        self.assertTrue(W._looks_like_noise("回：回"))
        self.assertTrue(W._looks_like_noise("田田"))

    def test_normal_text_is_kept(self):
        self.assertFalse(W._looks_like_noise("请大家明天交作业"))
        self.assertFalse(W._looks_like_noise("附件2：某某竞赛院级竞赛汇总表"))
        self.assertFalse(W._looks_like_noise("10.7K"))


# --------------------------------------------------------------------------
# id 稳定性（跨进程必须一致，绝不能用内置 hash()）
# --------------------------------------------------------------------------

class TestStableId(unittest.TestCase):
    def test_same_input_same_id(self):
        a = W.stable_id("群", "张三", "明天交作业")
        b = W.stable_id("群", "张三", "明天交作业")
        self.assertEqual(a, b)

    def test_normalized_equivalents(self):
        """空格 / 标点差异不应该产生新 id（OCR 每次断行位置可能不同）。"""
        a = W.stable_id("群", "张三", "附件2：某某竞赛汇总表")
        b = W.stable_id("群", "张三", "附件2:某某竞赛汇总表")
        c = W.stable_id("群", "张三", "附件2 ： 某某竞赛 汇总表")
        self.assertEqual(a, b)
        self.assertEqual(a, c)

    def test_different_text_different_id(self):
        a = W.stable_id("群", "张三", "明天交作业")
        b = W.stable_id("群", "张三", "后天交作业")
        self.assertNotEqual(a, b)

    def test_prefix(self):
        self.assertTrue(W.stable_id("x").startswith(W.WECHAT_PREFIX))


# --------------------------------------------------------------------------
# 解析：独立聊天窗口
# --------------------------------------------------------------------------

class TestParseIndependentWindow(unittest.TestCase):
    """版面：标题栏 y<0.12H、聊天区、底部输入框 y>0.93H。"""

    SIZE = (824, 948)

    def test_extract_title(self):
        lines = [L(19, 73, "2025级金融工程2班"), L(200, 73, "水群（70）"),
                 L(115, 300, "这是一条消息内容")]
        title = CH.extract_title(lines, self.SIZE, mode="independent")
        self.assertIn("2025级金融工程2班", title)
        self.assertIn("水群", title)

    def test_title_excludes_chat_body(self):
        lines = [L(19, 73, "群名关键词"), L(115, 300, "群名关键词也要出现在这里")]
        title = CH.extract_title(lines, self.SIZE, mode="independent")
        self.assertEqual(title, "群名关键词")

    def test_footer_is_cropped(self):
        """底部输入框里的文字不能被当成消息。"""
        lines = [L(115, 300, "好消息来了"), L(263, 884, "0")]
        msgs = CH.parse_chat(lines, self.SIZE, mode="independent")
        texts = [m.text for m in msgs]
        self.assertIn("好消息来了", texts)
        self.assertNotIn("0", texts)

    def test_avatar_single_char_dropped(self):
        """头像图案被误读成的单字，不该混进消息。"""
        lines = [L(48, 187, "生"), L(100, 180, "田珊瑜"),
                 L(115, 240, "附件2：某某竞赛汇总表")]
        msgs = CH.parse_chat(lines, self.SIZE, mode="independent")
        self.assertNotIn("生", [m.text for m in msgs])

    def test_sender_name_attached_to_next_block(self):
        """发送者名单独成块时，要认领给下面那条消息。"""
        lines = [
            L(100, 587, "田珊瑜"),                       # 名字块
            L(115, 690, "附件2：某某竞赛汇总表"),           # 隔了一段距离
        ]
        msgs = CH.parse_chat(lines, self.SIZE, mode="independent")
        hit = [m for m in msgs if "附件" in m.text]
        self.assertTrue(hit, "文件消息没被识别出来")
        self.assertEqual(hit[0].sender, "田珊瑜")

    def test_self_message_is_right_aligned(self):
        """靠右的短消息判为自己发的。"""
        lines = [L(600, 300, "收到"), L(115, 400, "好的")]
        msgs = CH.parse_chat(lines, self.SIZE, mode="independent")
        by_text = {m.text: m for m in msgs}
        self.assertEqual(by_text["收到"].side, "self")
        self.assertEqual(by_text["好的"].side, "other")


# --------------------------------------------------------------------------
# 关键词过滤（群里哪些消息值得入库）
# --------------------------------------------------------------------------

class TestToRecords(unittest.TestCase):
    NOW = "2026-10-08T18:00:00+08:00"

    def test_attachment_notice_is_kept(self):
        msgs = [CH.ChatMessage(y=100, text="附件2：某某竞赛院级竞赛汇总表.xlsx",
                               sender="田珊瑜", side="other", time_text="")]
        recs, skipped = W.to_records(msgs, "测试群", self.NOW, include_all=False)
        self.assertEqual(len(recs), 1)
        self.assertEqual(recs[0]["group"], "测试群")
        self.assertEqual(recs[0]["sender"], "田珊瑜")
        self.assertEqual(recs[0]["platform"], "wechat")

    def test_at_all_is_kept(self):
        msgs = [CH.ChatMessage(y=1, text="@所有人 明天记得交表", sender="班长",
                               side="other", time_text="")]
        recs, _ = W.to_records(msgs, "群", self.NOW, include_all=False)
        self.assertEqual(len(recs), 1)

    def test_homework_keyword_is_kept(self):
        msgs = [CH.ChatMessage(y=1, text="这周的高数作业有人做了吗", sender="a",
                               side="other", time_text="")]
        recs, _ = W.to_records(msgs, "群", self.NOW, include_all=False)
        self.assertEqual(len(recs), 1)

    def test_chitchat_is_skipped(self):
        msgs = [CH.ChatMessage(y=1, text="哈哈笑死我了", sender="a",
                               side="other", time_text="")]
        recs, skipped = W.to_records(msgs, "群", self.NOW, include_all=False)
        self.assertEqual(recs, [])
        self.assertEqual(len(skipped), 1)

    def test_include_all_keeps_chitchat(self):
        msgs = [CH.ChatMessage(y=1, text="哈哈笑死我了", sender="a",
                               side="other", time_text="")]
        recs, _ = W.to_records(msgs, "群", self.NOW, include_all=True)
        self.assertEqual(len(recs), 1)
        self.assertEqual(recs[0]["kind"], "chat")

    def test_system_lines_are_dropped(self):
        msgs = [CH.ChatMessage(y=1, text="—— 18:00 ——", sender="", side="system",
                               time_text="")]
        recs, _ = W.to_records(msgs, "群", self.NOW, include_all=True)
        self.assertEqual(recs, [])

    def test_noise_is_dropped(self):
        msgs = [CH.ChatMessage(y=1, text="回：回", sender="", side="other",
                               time_text="")]
        recs, skipped = W.to_records(msgs, "群", self.NOW, include_all=True)
        self.assertEqual(recs, [])

    def test_duplicate_text_collapses(self):
        msgs = [CH.ChatMessage(y=1, text="请大家填一下问卷", sender="a",
                               side="other", time_text=""),
                CH.ChatMessage(y=2, text="请大家填一下问卷", sender="a",
                               side="other", time_text="")]
        recs, _ = W.to_records(msgs, "群", self.NOW, include_all=False)
        self.assertEqual(len(recs), 1)


# --------------------------------------------------------------------------
# 合并进工作台状态（幂等 + 尊重"已删"）
# --------------------------------------------------------------------------

class TestMergeIntoState(unittest.TestCase):
    NOW = "2026-10-08T18:00:00+08:00"

    def _rec(self, text="附件1：申报书"):
        return {
            "id": W.stable_id("群", "张三", text),
            "platform": "wechat", "course": "", "courseId": "",
            "title": text, "content": text, "url": "", "time": self.NOW,
            "read": False, "kind": "notice", "deadline": "",
            "group": "群", "sender": "张三",
        }

    def test_adds_new(self):
        state = {"messages": [], "todos": []}
        r = W.merge_into_state(state, [self._rec()], now=self.NOW)
        self.assertEqual(r["added"], 1)
        self.assertEqual(len(state["messages"]), 1)

    def test_idempotent(self):
        state = {"messages": [], "todos": []}
        W.merge_into_state(state, [self._rec()], now=self.NOW)
        r = W.merge_into_state(state, [self._rec()], now=self.NOW)
        self.assertEqual(r["added"], 0)
        self.assertEqual(len(state["messages"]), 1)

    def test_respects_dismissed(self):
        rec = self._rec()
        state = {"messages": [], "todos": [],
                 "settings": {"dismissed": [rec["id"]]}}
        r = W.merge_into_state(state, [rec], now=self.NOW)
        self.assertEqual(r["added"], 0)

    def test_keeps_platform_messages(self):
        state = {"messages": [{"id": "c-sync-1", "platform": "chaoxing",
                               "title": "平台消息"}], "todos": []}
        W.merge_into_state(state, [self._rec()], now=self.NOW)
        ids = [m["id"] for m in state["messages"]]
        self.assertIn("c-sync-1", ids)

    def test_does_not_resurrect_read_state(self):
        """已入库且被标为已读的，重跑不能被改回未读。"""
        rec = self._rec()
        state = {"messages": [], "todos": []}
        W.merge_into_state(state, [rec], now=self.NOW)
        state["messages"][0]["read"] = True
        W.merge_into_state(state, [self._rec()], now=self.NOW)
        self.assertTrue(state["messages"][0]["read"])


if __name__ == "__main__":
    unittest.main()
