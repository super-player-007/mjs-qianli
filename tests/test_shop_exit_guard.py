# -*- coding: utf-8 -*-
"""商店锚点副作用回归测试（2026-11-12）。

「是否结束购买?」弹窗弹出时左上角吕不韦标题仍可见 → shop 锚点把弹窗页
误判成 shop → _act_shop 又点金盘 → 弹窗开关死循环。修复：决策前发现
弹窗已开就直接点「确定」退出。
"""
from __future__ import annotations

import logging
import unittest
from unittest.mock import patch

from src.game.runner import AutoRunner


def _runner() -> AutoRunner:
    r = AutoRunner(ctx=None, log=logging.getLogger("test"))
    r.poll_sleep = 0.0
    return r


def _item(text: str):
    return type("I", (), {"text": text, "center": (0, 0),
                          "rect": (0, 0, 10, 10), "score": 1.0})()


class TestShopExitGuard(unittest.TestCase):
    def test_exit_popup_confirmed_directly(self):
        """弹窗已开（锚点误判为 shop）→ 直接点确定，不再点金盘。"""
        r = _runner()
        items = [_item("是否结束购买?"), _item("确定"), _item("取消")]
        taps = []
        with patch.object(r, "_shot", return_value=object()), \
             patch.object(r, "_tap", lambda *xy, **kw: taps.append(xy)):
            status, msg = r._act_shop(items)
        self.assertEqual(taps, [(823, 690)], "应点确定而不是金盘")
        self.assertIn("结束购买", msg)

    def test_normal_shop_flow_unaffected(self):
        """正常货架帧（无弹窗）不走退出分支。"""
        r = _runner()
        items = [_item("吕不韦小铺子"), _item("信物专区")]
        taps = []
        with patch.object(r, "_shot", return_value=object()), \
             patch.object(r, "_tap", lambda *xy, **kw: taps.append(xy)), \
             patch.object(r, "_ocr", return_value=[]), \
             patch.object(r, "_shop_price_band_rescan", return_value=([], "")), \
             patch("src.game.runner.shop.pick_shop_purchase",
                   return_value=(None, "货架上没有想要清单里的商品")):
            r._act_shop(items)
        self.assertEqual(taps, [(1845, 127)], "无弹窗时才走金盘退出")


if __name__ == "__main__":
    unittest.main()
