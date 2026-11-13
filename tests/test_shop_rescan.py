# -*- coding: utf-8 -*-
"""商店价格带补扫测试（2026-10-18 姜维 14 事故：全屏 OCR 漏读小价格）。"""
from __future__ import annotations

import logging
import unittest
from unittest.mock import patch

import numpy as np

from src.game import shop
from src.game.runner import AutoRunner


class FakeOCRItem:
    def __init__(self, text, rect):
        self.text = text
        self.rect = rect


def shop_screen_items(with_wupai_price: bool):
    """模拟全屏 OCR：武将牌专区名字在，但价格 14 是否被读到。"""
    items = [
        FakeOCRItem("小铺子", (500, 110, 640, 150)),
        FakeOCRItem("245", (1650, 130, 1710, 165)),
        FakeOCRItem("信物专区", (1350, 185, 1520, 220)),
        FakeOCRItem("筹策", (960, 255, 1060, 290)),
        FakeOCRItem("40", (1020, 510, 1060, 545)),
        FakeOCRItem("武将牌专区", (1330, 610, 1520, 645)),
        FakeOCRItem("姜维", (1290, 690, 1370, 730)),
    ]
    if with_wupai_price:
        items.append(FakeOCRItem("14", (1350, 890, 1390, 925)))
    return items


def band_items():
    """价格带局部 OCR 的返回（相对坐标会被 _shop_price_band_rescan 平移）。"""
    return [FakeOCRItem("已售罄", (115, 94, 197, 120)),
            FakeOCRItem("14", (471, 99, 499, 120)),
            FakeOCRItem("已售罄", (754, 94, 835, 120))]


class TestPriceBandRescan(unittest.TestCase):
    def setUp(self):
        from src.game import shop
        self._orig_w = list(shop._shop_wanted)
        self._orig_r = shop._shop_reserve

    def tearDown(self):
        from src.game import shop
        shop._shop_wanted = self._orig_w
        shop._shop_reserve = self._orig_r

    def _runner(self):
        r = AutoRunner(ctx=None, log=logging.getLogger("t"))
        taps = []
        return r, taps

    def test_rescan_finds_missed_price(self):
        """全屏漏读 14 → 价格带补扫读到 → 购买姜维。"""
        r, taps = self._make_runner()

        def fake_ocr(img, region=None):
            # 调用序：①余额区域 ②价格带补扫（_act_shop 不做全屏 OCR，
            # items 走参数传入）
            if region == shop.SHOP_BALANCE_REGION:
                return [FakeOCRItem("245", (1650, 130, 1710, 165))]
            return band_items()

        with patch.object(AutoRunner, "_shot",
                          side_effect=lambda: np.zeros((1080, 1920, 3), np.uint8)), \
             patch.object(AutoRunner, "_ocr", side_effect=fake_ocr), \
             patch.object(AutoRunner, "_tap",
                          side_effect=lambda x, y, wait=0:
                          taps.append((x, y))), \
             patch("src.game.runner.time.sleep"):
            status, msg = r._act_shop(shop_screen_items(False))
        self.assertIn("购买 姜维", msg)
        self.assertIn("补扫", msg)

    def _make_runner(self):
        r = AutoRunner(ctx=None, log=logging.getLogger("t"))
        taps = []
        return r, taps

    def test_rescan_still_empty_exits(self):
        """补扫也读不到 → 正常退出，不崩。"""
        r, taps = self._make_runner()

        def fake_ocr(img, region=None):
            if region == shop.SHOP_BALANCE_REGION:
                return [FakeOCRItem("245", (1650, 130, 1710, 165))]
            return []                            # 补扫也读不到价格

        with patch.object(AutoRunner, "_shot",
                          side_effect=lambda: np.zeros((1080, 1920, 3), np.uint8)), \
             patch.object(AutoRunner, "_ocr", side_effect=fake_ocr), \
             patch.object(AutoRunner, "_tap",
                          side_effect=lambda x, y, wait=0:
                          taps.append((x, y))), \
             patch("src.game.runner.time.sleep"):
            status, msg = r._act_shop(shop_screen_items(False))
        self.assertIn("退出", msg)


if __name__ == "__main__":
    unittest.main()
