# -*- coding: utf-8 -*-
"""资源更新弹窗识别与处理测试（2026-11-14）。

入口页弹「本次登录不再提示/确定/取消」资源更新弹窗 → 锚点（勾选文字带，
唯一性最强）/ OCR 关键词识别为 resource_update → 点确定 (817,713)。
"""
from __future__ import annotations

import logging
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from src.game.runner import AutoRunner
from src.vision.annotate import read_image

FIX = Path("tests/fixtures/resource_update.png")


def _item(text, cx=0, cy=0):
    return type("I", (), {"text": text, "center": (cx, cy),
                          "rect": (cx - 40, cy - 16, cx + 40, cy + 16),
                          "score": 1.0})()


class TestResourceUpdateDialog(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.img = read_image(FIX)

    def _runner(self) -> AutoRunner:
        r = AutoRunner(ctx=None, log=logging.getLogger("test"))
        r.poll_sleep = 0.0
        return r

    def test_anchor_hits_fixture(self):
        """真实夹具：锚点表应判 resource_update。"""
        import cv2
        from src.game import anchor_table
        table = anchor_table.load_anchor_table()
        gray = cv2.cvtColor(self.img, cv2.COLOR_BGR2GRAY)
        e = anchor_table.match_entry(gray, table, in_run=False)
        self.assertIsNotNone(e)
        self.assertEqual(e.state, "resource_update")

    def test_classify_by_keyword(self):
        """OCR 关键词兜底：『本次登录不再提示』→ resource_update。"""
        r = self._runner()
        items = [_item("本次登录不再提示", 985, 647),
                 _item("确定", 817, 713), _item("取消", 1097, 713)]
        self.assertEqual(r.classify(items), "resource_update")

    def test_step_taps_confirm(self):
        """整链：锚点命中 → 走到动作 → 点确定 (817,713)。"""
        r = self._runner()
        taps = []
        it = MagicMock()
        it.text = "本次登录不再提示"
        it.rect = (877, 631, 1094, 664)
        with patch.object(AutoRunner, "_shot", return_value=self.img), \
             patch.object(AutoRunner, "_ocr", return_value=[it]), \
             patch.object(AutoRunner, "_tap",
                          side_effect=lambda x, y, wait=0: taps.append((x, y))):
            _state, msg = r.step()
        self.assertIn((817, 713), taps, msg=msg)
        self.assertIn("资源更新", msg)


if __name__ == "__main__":
    unittest.main()
