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



class TestSoldOutExcluded(unittest.TestCase):
    """2026-11-17 事故：已售罄卡的划线原价被补扫读出 → 每步点售罄卡死循环。"""

    @staticmethod
    def _item(text, cx, cy):
        return FakeOCRItem(text, (cx - 40, cy - 16, cx + 40, cy + 16))

    def test_soldout_price_not_parsed(self):
        items = [
            self._item("郭嘉", 1064, 772),
            self._item("57", 1046, 863),      # 划线原价（售罄卡）
            self._item("已售罄", 1056, 956),
        ]
        self.assertEqual(shop.parse_shop(items), [])

    def test_soldout_variant_xin(self):
        """OCR 把「罄」读成「馨」也覆盖。"""
        items = [
            self._item("郭嘉", 1064, 772),
            self._item("57", 1046, 863),
            self._item("已售馨", 1056, 956),
        ]
        self.assertEqual(shop.parse_shop(items), [])

    def test_normal_price_still_parsed(self):
        """同列无售罄标签的正常商品不受影响。"""
        items = [
            self._item("六国相印", 1367, 272),
            self._item("24", 1384, 525),
        ]
        goods = shop.parse_shop(items)
        self.assertEqual(len(goods), 1)
        self.assertEqual(goods[0]["name"], "六国相印")

    def test_real_fixture_exits_shop(self):
        """实拍（郭嘉已售罄 + 补扫 57）→ 决策应为退出，不购买。"""
        from pathlib import Path
        from src.vision.annotate import read_image
        from src.vision.ocr import OCREngine
        img = read_image(Path("tests/fixtures/shop_soldout_wupai.png"))
        ocr = OCREngine(device="auto")
        items = list(ocr.read(img))
        for it in ocr.read(img, (900, 850, 1920, 970)):
            rx1, ry1, rx2, ry2 = it.rect
            items.append(FakeOCRItem(it.text,
                                     (rx1 + 900, ry1 + 850, rx2 + 900, ry2 + 850)))
        g, why = shop.pick_shop_purchase(items, coins=420)
        self.assertIsNone(g, msg=why)
        self.assertIn("退出", why)


if __name__ == "__main__":
    unittest.main()
