"""刷新任务确认弹窗测试（2026-10-18 用户需求：勾选「今日登录不再提示」→确定）。

弹窗锚点：今日登录不再提示 / 消耗军令状（原生坐标 10-09 cal_current.png 标定：
标题 (882,334)-(1051,373)、文本 (877,631)-(1093,664)、确定按钮 (745,693)-(888,730)）。
"""
from __future__ import annotations

import logging
import unittest
from unittest.mock import patch

from src.game.runner import AutoRunner


class FakeOCRItem:
    def __init__(self, text, rect):
        self.text = text
        self.rect = rect


def popup_items():
    """2026-10-18 用户截图 + 10-09 cal_current.png 原生坐标。"""
    return [
        FakeOCRItem("刷新任务", (882, 334, 1051, 373)),
        FakeOCRItem("是否消耗军令状1立即获得1个新的任务？",
                    (662, 489, 1246, 522)),
        FakeOCRItem("今日登录不再提示", (877, 631, 1093, 664)),
        FakeOCRItem("人1确定", (745, 693, 888, 730)),
        FakeOCRItem("取消", (1061, 695, 1135, 731)),
    ]


class TestRefreshConfirm(unittest.TestCase):
    def setUp(self):
        r = AutoRunner(ctx=None, log=logging.getLogger("t"))
        r.in_run = True
        self.r = r
        self.taps = []

    def test_classify(self):
        self.assertEqual(self.r.classify(popup_items()), "refresh_confirm")

    def test_action_ticks_checkbox_then_confirms(self):
        """先勾复选框（文本左侧 45px），再点确定（按钮右侧文字区）。"""
        with patch.object(AutoRunner, "_shot",
                          side_effect=lambda: object()), \
             patch.object(AutoRunner, "_tap",
                          side_effect=lambda x, y, wait=0:
                          self.taps.append((x, y))), \
             patch("src.game.runner.time.sleep"):
            status, msg = self.r._act_refresh_confirm(popup_items())
        self.assertIn("勾选", msg)
        self.assertEqual(len(self.taps), 2)
        bx, by = self.taps[0]
        cx, cy = self.taps[1]
        # 复选框：文本 x1=877 左侧 45px、y 取文本中线
        self.assertAlmostEqual(bx, 832, delta=3)
        self.assertAlmostEqual(by, 647, delta=3)
        # 确定：按钮 x2=888 右侧文字区（x2-45）、y 中线
        self.assertAlmostEqual(cx, 843, delta=3)
        self.assertAlmostEqual(cy, 711, delta=3)

    def test_action_fallback_fixed_coords(self):
        """OCR 没读到按钮/文本 → 用弹窗居中标定的固定兜底坐标。"""
        with patch.object(AutoRunner, "_shot",
                          side_effect=lambda: object()), \
             patch.object(AutoRunner, "_tap",
                          side_effect=lambda x, y, wait=0:
                          self.taps.append((x, y))), \
             patch("src.game.runner.time.sleep"):
            status, msg = self.r._act_refresh_confirm([])
        self.assertEqual(self.taps[0], (832, 647))
        self.assertEqual(self.taps[1], (849, 711))

    def test_classify_not_confused_with_tip_screen(self):
        """温馨提示过场（无按钮）仍是 tip_screen，不误判。"""
        items = [FakeOCRItem("温馨提示", (800, 400, 1100, 450))]
        self.assertEqual(self.r.classify(items), "tip_screen")


if __name__ == "__main__":
    unittest.main()
