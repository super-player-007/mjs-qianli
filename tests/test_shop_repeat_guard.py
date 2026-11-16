# -*- coding: utf-8 -*-
"""商店兜底防死循环测试（2026-11-17）。"""
from __future__ import annotations

import logging
import unittest
from unittest.mock import patch

from src.game.runner import AutoRunner
from src.game import shop


def _item(text, cx=1000, cy=500):
    return type("I", (), {"text": text, "center": (cx, cy),
                          "rect": (cx - 30, cy - 15, cx + 30, cy + 15),
                          "score": 1.0})()


class _FixedGoods:
    def __init__(self, name, price, coins):
        self.g = {"name": name, "price": price, "click": (1000, 500),
                  "zone": "xinwu"}
        self.coins = coins


class TestShopRepeatGuard(unittest.TestCase):
    def _runner(self):
        r = AutoRunner(ctx=None, log=logging.getLogger("test"))
        r.poll_sleep = 0.0
        return r

    def test_third_repeat_forces_exit(self):
        """同名同价同余额连点 3 次 → 第 3 次强制退出并点金盘。"""
        r = self._runner()
        taps = []
        g = {"name": "郭嘉", "price": 57, "click": (1000, 500),
             "zone": "wupai"}
        with patch.object(AutoRunner, "_shot", return_value=object()), \
             patch.object(AutoRunner, "_save", return_value=None), \
             patch.object(AutoRunner, "_ocr", return_value=[_item("420")]), \
             patch.object(shop, "parse_shop", return_value=[]), \
             patch.object(shop, "pick_shop_purchase",
                          return_value=(g, "武将牌专区")), \
             patch.object(AutoRunner, "_tap",
                          side_effect=lambda x, y, wait=0: taps.append((x, y))):
            msgs = [r._act_shop([])[1] for _ in range(3)]
        self.assertIn("购买", msgs[0])
        self.assertIn("购买", msgs[1])
        self.assertIn("强制退出", msgs[2])
        self.assertEqual(taps[-1], (1845, 127))

    def test_progress_resets_counter(self):
        """余额变化（购买生效）→ 计数清零，不会误强制退出。"""
        r = self._runner()
        g = {"name": "行囊", "price": 18, "click": (1000, 500),
             "zone": "xinwu"}
        balances = iter(["420", "420", "402", "384", "366"])
        with patch.object(AutoRunner, "_shot", return_value=object()), \
             patch.object(AutoRunner, "_save", return_value=None), \
             patch.object(AutoRunner, "_ocr",
                          side_effect=lambda *a, **k: [_item(next(balances))]), \
             patch.object(shop, "parse_shop", return_value=[]), \
             patch.object(shop, "pick_shop_purchase",
                          return_value=(g, "信物专区")), \
             patch.object(AutoRunner, "_tap"):
            msgs = [r._act_shop([])[1] for _ in range(5)]
        self.assertTrue(all("购买" in m for m in msgs), msg=str(msgs))


if __name__ == "__main__":
    unittest.main()
