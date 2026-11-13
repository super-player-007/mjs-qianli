# -*- coding: utf-8 -*-
"""回退导航落点验证测试（2026-11-12）。

局终后游戏弹「战报翻页/本局战绩」，盲点返回会先落在这些页上，导航曾谎报
成功。现在退链走完用 OCR 地标词验证目标页，不对就补按返回（最多 2 次）。
"""
from __future__ import annotations

import logging
import unittest
from unittest.mock import MagicMock, patch

from src.game import nav


def _ctx(screen_texts: str):
    """伪造 ctx：OCR 返回给定文本，点击记录到 taps，coords 走内置默认。"""
    ctx = MagicMock()
    ctx.log = logging.getLogger("test")
    it = type("I", (), {})
    items = []
    for w in screen_texts.split():
        o = it()
        o.text = w
        items.append(o)
    ctx.ocr.read.return_value = items
    ctx.cfg.point.return_value = (1841, 138)
    ctx.cfg.coords.get.return_value = {}    # coords.yaml 无 nav 段 → 用默认
    return ctx


class TestBackVerify(unittest.TestCase):
    def test_success_when_landmark_present(self):
        ctx = _ctx("招募 竞技 煮酒")
        with patch("src.game.nav.time.sleep"):
            self.assertTrue(nav.back(ctx, frm="qianli", to="home"))

    def test_retry_when_replay_page_pops(self):
        """局终战报页遮挡：前两次验证失败，补按返回后见到主页。"""
        ctx = _ctx("下一步 本局战绩")           # 前 2 次都看不到地标
        results = iter([False, False, True])    # 第 3 次（补按 2 次后）通过
        with patch.object(nav, "_landmark_hit",
                          side_effect=lambda c, p: next(results)), \
             patch("src.game.nav.time.sleep"):
            self.assertTrue(nav.back(ctx, frm="qianli", to="home"))
        # 初始 2 次返回 + 补按 2 次 = 4 次点击
        self.assertEqual(ctx.device.tap.call_count, 4)

    def test_fail_after_retries(self):
        ctx = _ctx("下一步 本局战绩")
        with patch.object(nav, "_landmark_hit", return_value=False), \
             patch("src.game.nav.time.sleep"):
            self.assertFalse(nav.back(ctx, frm="qianli", to="home"))
        self.assertEqual(ctx.device.tap.call_count, 4)


if __name__ == "__main__":
    unittest.main()
