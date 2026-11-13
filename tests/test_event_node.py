"""事件节点（钱袋）内部选择规则测试（对应 src/game/event_node.py）。"""
from __future__ import annotations

import logging
import unittest
from unittest.mock import patch

from src.game.event_node import (FALLBACK_CLICK, is_event_node_page,
                                 pick_event_node_option)
from src.game import settle_page
from src.game.runner import STATE_OK, AutoRunner


class FakeItem:
    def __init__(self, text, cx, cy):
        self.text = text
        self.rect = [cx - 80, cy - 16, cx + 80, cy + 16]


def make_screen_20260918():
    """2026-09-18 实测：信陵君「虎符在手」，三选项横排 y≈842。

    实际列位：杀帅夺军(187) / 晓之以理(790) / 威逼利诱(1391)。
    """
    return [
        FakeItem("虎符在手", 1283, 223),
        FakeItem("你在魏国遇到了信陵君，他正在苦恼", 1257, 331),
        FakeItem("【杀帅夺军】", 187, 843),
        FakeItem("【晓之以理】", 790, 843),
        FakeItem("【威逼利诱】", 1391, 842),
        FakeItem("失去2点体力，复制牌堆中的8张装备牌", 453, 904),
        FakeItem("速度-2，复制牌堆中的8张战法牌", 923, 904),
        FakeItem("50%消耗6太平百钱，50%失去2点随机属性", 1564, 885),
    ]


class TestEventNode(unittest.TestCase):
    def test_page_detected(self):
        self.assertTrue(is_event_node_page(make_screen_20260918()))

    def test_pick_middle(self):
        pt, reason = pick_event_node_option(make_screen_20260918())
        self.assertEqual(pt, (790, 888))        # 中间项【晓之以理】+ 45px
        self.assertIn("中间", reason)
        self.assertIn("【晓之以理】", reason)     # 文案变化不影响——只认结构

    def test_titles_change_still_middle(self):
        """选项文案每局都变：换一套标题仍选几何中间。"""
        items = [
            FakeItem("随便什么标题", 1283, 223),
            FakeItem("【AAA】", 700, 850),
            FakeItem("【BBB】", 1089, 848),
            FakeItem("【CCC】", 1450, 852),
        ]
        pt, _ = pick_event_node_option(items)
        self.assertEqual(pt[0], 1089)

    def test_vertical_brackets_not_event_page(self):
        """纵排【】（如休息页样式）不判为事件节点页。"""
        items = [FakeItem("【甲】", 400, 800), FakeItem("【乙】", 400, 860),
                 FakeItem("【丙】", 400, 920)]
        self.assertFalse(is_event_node_page(items))

    def test_fallback_when_ocr_misses(self):
        pt, reason = pick_event_node_option([FakeItem("虎符在手", 1283, 223)])
        self.assertEqual(pt, FALLBACK_CLICK)
        self.assertIn("兜底", reason)

    def test_empty(self):
        pt, _ = pick_event_node_option([])
        self.assertEqual(pt, FALLBACK_CLICK)


class TestConfirmOnlyPage(unittest.TestCase):
    """孤立「确认」页（事件节点结果页等）→ 点确认的 OCR 实时位置。

    2026-09-18 踩坑：曾用 expect_event_confirm 标志位限定，但多局连跑时
    上一局遗留的确认页在新一轮开局标志位是 False → unknown 停机。
    现改为通用状态：只认"有确认、无其他按钮组合"，位置取 OCR 实时框中心。
    """

    def _runner(self):
        import logging
        return AutoRunner(ctx=None, log=logging.getLogger("t"))

    def _confirm_items(self):
        return [FakeItem("虎符在手", 1283, 223),
                FakeItem("晓之以理，速度-2，复制牌堆中的8张战法牌", 1100, 300),
                FakeItem("确认", 964, 865)]

    def test_routes_to_confirm_only(self):
        r = self._runner()
        self.assertEqual(r.classify(self._confirm_items()), "confirm_only")

    def test_excluded_combo_pages(self):
        """确认+其他按钮的组合页必须排除（各有专属状态或不应乱点）。"""
        r = self._runner()
        cases = [
            [FakeItem("确认", 900, 860), FakeItem("取消", 1200, 860)],
            [FakeItem("15购买", 743, 745), FakeItem("取消", 1133, 745)],
            [FakeItem("本局战绩", 960, 300), FakeItem("确认", 960, 937)],
            [FakeItem("领取奖励", 959, 942), FakeItem("确认", 960, 500)],
        ]
        for items in cases:
            self.assertNotEqual(r.classify(items), "confirm_only", items)

    def test_step_taps_ocr_center(self):
        r = self._runner()
        taps = []

        class Ctx:
            def tap_point(self, pt, **kw):
                taps.append(pt)
        r.ctx = Ctx()
        with patch.object(AutoRunner, "_shot",
                          side_effect=lambda: None), \
             patch.object(AutoRunner, "_ocr",
                          return_value=self._confirm_items()), \
             patch.object(settle_page, "match_state", return_value=None), \
             patch("src.game.runner.time.sleep"):
            status, msg = r.step()
        self.assertEqual(status, STATE_OK)
        self.assertEqual(taps, [(964, 865)])    # OCR 框中心，非写死

    def test_fallback_when_no_exact_match(self):
        """「确认」文本异常（如 OCR 粘连成确认并继续）时用兜底坐标，不崩。"""
        r = self._runner()
        items = [FakeItem("虎符在手", 1283, 223),
                 FakeItem("确认并继续", 964, 865)]
        taps = []

        class Ctx:
            def tap_point(self, pt, **kw):
                taps.append(pt)
        r.ctx = Ctx()
        with patch.object(AutoRunner, "_shot",
                          side_effect=lambda: None), \
             patch.object(AutoRunner, "_ocr", return_value=items), \
             patch.object(settle_page, "match_state", return_value=None), \
             patch("src.game.runner.time.sleep"):
            status, _ = r.step()
        self.assertEqual(status, STATE_OK)
        self.assertEqual(taps, [(964, 865)])


if __name__ == "__main__":
    unittest.main()
