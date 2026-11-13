"""偷袭事件测试（对应 src/game/ambush.py，2026-09-20 实测采集）。"""
from __future__ import annotations

import unittest
from pathlib import Path

from src.game.ambush import is_ambush_page, pick_ambush_button
from src.game.runner import STATE_OK, AutoRunner
from src.vision.annotate import read_image
from src.vision.ocr import OCREngine


class FakeItem:
    def __init__(self, text, cx, cy):
        self.text = text
        self.rect = [cx - 150, cy - 17, cx + 150, cy + 17]


def make_screen_20260920():
    """实测：偷袭/寒芒乍现/杀意满盈…/与张良、诸葛亮、郭嘉战斗。"""
    return [
        FakeItem("偷袭", 972, 519),
        FakeItem("寒芒乍现", 962, 695),
        FakeItem("杀意满盈，偷袭已如雷霆骤降。", 956, 750),
        FakeItem("与张良、诸葛亮、郭嘉战斗", 964, 866),
    ]


class TestAmbush(unittest.TestCase):
    def test_page_detected(self):
        self.assertTrue(is_ambush_page(make_screen_20260920()))

    def test_pick_button_center(self):
        pt, reason = pick_ambush_button(make_screen_20260920())
        self.assertEqual(pt, (964, 866))
        self.assertIn("张良", reason)

    def test_enemy_names_change_still_works(self):
        """敌方武将名每局都变——只认「与…战斗」结构。"""
        items = [FakeItem("偷袭", 972, 519),
                 FakeItem("与吕布、貂蝉战斗", 900, 870)]
        self.assertTrue(is_ambush_page(items))
        pt, _ = pick_ambush_button(items)
        self.assertEqual(pt, (900, 870))

    def test_no_button(self):
        pt, _ = pick_ambush_button([FakeItem("偷袭", 972, 519)])
        self.assertIsNone(pt)

    def test_other_combat_words_not_matched(self):
        """「战斗」单独出现/其他句式不误判。"""
        self.assertFalse(is_ambush_page([FakeItem("准备战斗", 900, 500)]))
        self.assertFalse(is_ambush_page([FakeItem("战斗", 900, 500)]))

    def test_e2e_real_fixture(self):
        """真实截图端到端：截图 → OCR → 分类 → 决策。"""
        r = AutoRunner(ctx=None, log=None)
        items = OCREngine().read(read_image(Path("tests/fixtures/ambush.png")))
        self.assertEqual(r.classify(items), "ambush")
        pt, _ = pick_ambush_button(items)
        self.assertEqual(pt, (964, 866))


if __name__ == "__main__":
    unittest.main()


class TestTargetSelectNotEventPage(unittest.TestCase):
    """战斗选人提示「请选择一名其他角色」不是事件选项页
    （2026-09-21 01:37 事故：泛化「请选择一」误吞 → 停机）。"""

    def _items(self):
        from tests.test_ambush import FakeItem as F  # 复用同文件的 FakeItem
        return [
            F("第1轮", 60, 60), F("147/162", 90, 80),
            F("请选择一名其他角色", 960, 725),
            F("确定", 960, 663), F("取消", 1210, 663),
            F("浑生两仪", 1620, 755), F("混沌未开", 1620, 800),
            F("骨鲠之臣", 1620, 845), F("飞连矢", 1620, 890),
        ]

    def _runner(self):
        import logging
        return AutoRunner(ctx=None, log=logging.getLogger("t"))

    def test_classified_as_battle(self):
        self.assertEqual(self._runner().classify(self._items()), "battle")

    def test_not_hero_event_choice(self):
        self.assertNotEqual(self._runner().classify(self._items()),
                            "hero_event_choice")


class TestAmbushWrappedButton(unittest.TestCase):
    """偷袭按钮换行断开（2026-10-08 00:30 事故）：敌方 3 人文案过长，
    「与张良、诸葛亮、司马懿战」+「斗」拆成两行 OCR 条目 →
    单行正则失配 → unknown。识别用全文拼接，点击用固定按钮位。"""

    def _items(self):
        from tests.test_ambush import FakeItem as F
        # 2026-10-08 偷袭/一击即走 实测条目（斗 拆到第二行）
        return [
            F("偷袭", 540, 320),
            F("一击即走", 540, 417),
            F("你呼吸未定，暗处杀机已动。", 540, 446),
            F("与张良、诸葛亮、司马懿战", 540, 487),
            F("斗", 540, 515),
        ]

    def _runner(self):
        import logging
        from src.game.runner import AutoRunner
        return AutoRunner(ctx=None, log=logging.getLogger("t"))

    def test_classified_as_ambush(self):
        self.assertEqual(self._runner().classify(self._items()), "ambush")

    def test_pick_uses_fixed_pos(self):
        from src.game.ambush import AMBUSH_FIXED_POS
        pt, reason = pick_ambush_button(self._items())
        self.assertEqual(pt, AMBUSH_FIXED_POS)
        self.assertIn("换行", reason)

    def test_single_line_still_prefers_ocr_center(self):
        """按钮完整一行时仍用 OCR 实时框中心（原有行为不回退）。"""
        items = [FakeItem("偷袭", 972, 519),
                 FakeItem("与张良、诸葛亮、郭嘉战斗", 964, 866)]
        pt, _ = pick_ambush_button(items)
        self.assertEqual(pt, (964, 866))

    def test_plain_battle_page_not_ambush(self):
        """普通战斗页（无偷袭标题）不得误判——防止拼接放宽引入误报。"""
        items = [FakeItem("第1轮", 60, 60),
                 FakeItem("与张良、诸葛亮、司马懿战", 540, 487),
                 FakeItem("斗", 540, 515)]
        self.assertFalse(is_ambush_page(items))


if __name__ == "__main__":
    unittest.main()
