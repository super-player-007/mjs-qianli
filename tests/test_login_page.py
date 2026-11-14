# -*- coding: utf-8 -*-
"""登录页识别与处理测试（2026-11-14）。

资源更新确定 → 登录页：更新中（无「点击登录」）→ 等待；更新完成出现
「点击登录」→ 点它进主界面。锚点用底部备案号文案带（更新中也在）。
"""
from __future__ import annotations

import logging
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from src.game.runner import AutoRunner
from src.vision.annotate import read_image

FIX = Path("tests/fixtures/login_page.png")


def _item(text, cx=0, cy=0):
    return type("I", (), {"text": text, "center": (cx, cy),
                          "rect": (cx - 40, cy - 16, cx + 40, cy + 16),
                          "score": 1.0})()


class TestLoginPage(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.img = read_image(FIX)

    def _runner(self) -> AutoRunner:
        r = AutoRunner(ctx=None, log=logging.getLogger("test"))
        r.poll_sleep = 0.0
        return r

    def test_anchor_hits_fixture(self):
        """真实夹具：锚点表应判 login_page。"""
        import cv2
        from src.game import anchor_table
        table = anchor_table.load_anchor_table()
        gray = cv2.cvtColor(self.img, cv2.COLOR_BGR2GRAY)
        e = anchor_table.match_entry(gray, table, in_run=False)
        self.assertIsNotNone(e)
        self.assertEqual(e.state, "login_page")

    def test_classify_by_keyword(self):
        """OCR 关键词兜底：『点击登录』→ login_page。"""
        r = self._runner()
        items = [_item("点击登录", 959, 781)]
        self.assertEqual(r.classify(items), "login_page")

    def test_action_taps_login(self):
        """更新完成：「点击登录」在场 → 点它。"""
        r = self._runner()
        taps = []
        it = MagicMock()
        it.text = "点击登录"
        it.rect = (826, 758, 1093, 805)
        it.center = (959, 781)
        with patch.object(AutoRunner, "_shot", return_value=self.img), \
             patch.object(AutoRunner, "_ocr", return_value=[it]), \
             patch.object(AutoRunner, "_tap",
                          side_effect=lambda x, y, wait=0: taps.append((x, y))):
            _state, msg = r.step()
        self.assertIn((959, 781), taps, msg=msg)
        self.assertIn("登录", msg)

    def test_action_waits_during_update(self):
        """更新中：OCR 读不到「点击登录」→ 不点击，只等待。"""
        r = self._runner()
        taps = []
        with patch.object(AutoRunner, "_shot", return_value=self.img), \
             patch.object(AutoRunner, "_ocr", return_value=[]), \
             patch.object(AutoRunner, "_tap",
                          side_effect=lambda x, y, wait=0: taps.append((x, y))):
            _state, msg = r.step()
        self.assertEqual(taps, [], msg=msg)
        self.assertIn("等待", msg)


if __name__ == "__main__":
    unittest.main()
