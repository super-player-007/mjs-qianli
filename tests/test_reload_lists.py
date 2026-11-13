# -*- coding: utf-8 -*-
"""reload 重置运行时名单的回归测试（2026-11-13 行囊事故）。

GUI on_start 先 apply 名单 → worker 里 importlib.reload(shop/gift) 会把
模块级清单重置回内建默认 → 必须在 reload 之后重新应用。
"""
from __future__ import annotations

import importlib
import unittest


class TestReloadResetsRuntimeLists(unittest.TestCase):
    def test_reload_wipes_and_reapply_restores(self):
        from src.game import shop

        shop.apply_shop_wanted(["行囊", "玉珏"])
        self.assertIn("行囊", shop.shop_wanted())

        # 模拟 worker 里的热重载：名单被重置回内建默认（不含行囊）
        importlib.reload(shop)
        self.assertNotIn("行囊", shop.shop_wanted(),
                         "reload 应重置运行时清单（事故前提）")

        # 修复动作：重载后重新应用
        shop.apply_shop_wanted(["行囊", "玉珏"])
        self.assertIn("行囊", shop.shop_wanted())

    def test_reserve_reset_and_reapply(self):
        from src.game import shop

        shop.apply_shop_reserve(200)
        self.assertEqual(shop.shop_reserve(), 200)
        importlib.reload(shop)
        self.assertEqual(shop.shop_reserve(), 150)   # 重置回默认
        shop.apply_shop_reserve(200)
        self.assertEqual(shop.shop_reserve(), 200)


if __name__ == "__main__":
    unittest.main()
