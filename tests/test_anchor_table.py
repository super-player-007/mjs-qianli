# -*- coding: utf-8 -*-
"""锚点表测试（阶段 1 试点 2026-11-11）+ 刷新弹窗经锚点表处理的回归。"""
from __future__ import annotations

import logging
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import cv2
import numpy as np

from src.game import anchor_table, settle_page
from src.game.runner import AutoRunner

FIX = Path("tests/fixtures")
POPUP_FIXTURE = FIX / "refresh_popup.png"
POPUP_TPL = Path("assets/templates/popup/refresh_confirm.png")


def _load(name: str):
    return cv2.imdecode(np.fromfile(str(FIX / name), dtype=np.uint8),
                        cv2.IMREAD_COLOR)


def make_runner():
    return AutoRunner(ctx=None, log=logging.getLogger("t"))


class TestAnchorTable(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.table = anchor_table.load_anchor_table()

    def test_table_loaded(self):
        states = [e.state for e in self.table]
        for st in ("hero_info", "map", "battle_confirm", "mulligan",
                   "tip_screen", "refresh_confirm"):
            self.assertIn(st, states)

    def test_map_dual_anchor(self):
        """map 双锚点 AND：结束挑战+当前挑战 同时命中才算。"""
        me = [e for e in self.table if e.state == "map"][0]
        self.assertEqual(len(me.areas), 2)

    def test_fixture_classification(self):
        """夹具 → 锚点表分类正确（核心回归）。"""
        cases = {
            # 2026-11-12 游戏更新：按钮皮肤变了，锚点改从新皮肤夹具裁；
            # map_layer1/2..6 等旧皮肤夹具仅作节点识别测试素材（见生成器 LEGACY_SKIP）
            "map_new_skin.png": "map",
            "map_layer2_new.png": "map",
            "battle_confirm.png": "battle_confirm",
            "mulligan.png": "mulligan", "tip_screen.png": "tip_screen",
            "refresh_popup.png": "refresh_confirm",
            "hero_info.png": "hero_info",
            # 第二轮扩展：战斗 + 战斗子页 + 结算链全 4 页 + 变体
            "battle_live.png": "battle",
            "battle_target_select.png": "battle",
            "settle_settle_confirm.png": "settle_confirm",
            "settle_reward_overlay.png": "reward_overlay",
            "settle_next_preview.png": "next_preview",
            "next_preview_wansheng.png": "next_preview",
        }
        for f, want in cases.items():
            img = _load(f)
            g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            e = anchor_table.match_entry(g, self.table, in_run=True)
            self.assertIsNotNone(e, msg=f)
            self.assertEqual(e.state, want, msg=f)

    def test_no_cross_hit_on_clean_pages(self):
        """干净页面（结算/战斗/商店/任务夹具）不应被锚点表误判。"""
        for f in ("shop_main.png", "task_page_claim.png",
                  "home_page.png", "ambush.png", "divination.png"):
            g = cv2.cvtColor(_load(f), cv2.COLOR_BGR2GRAY)
            e = anchor_table.match_entry(g, self.table, in_run=True)
            self.assertIsNone(e, msg=f)

    def test_scope_pruning(self):
        """in_run=False（局外）时局内锚点不参与匹配。"""
        g = cv2.cvtColor(_load("map_layer1.png"), cv2.COLOR_BGR2GRAY)
        e = anchor_table.match_entry(g, self.table, in_run=False)
        self.assertIsNone(e, "局外不应命中局内锚点")

    def test_speed(self):
        """锚点表扫描耗时上限（性能回归）。"""
        g = cv2.cvtColor(_load("map_layer1.png"), cv2.COLOR_BGR2GRAY)
        t0 = time.perf_counter()
        anchor_table.match_entry(g, self.table, in_run=True)
        dt = (time.perf_counter() - t0) * 1000
        self.assertLess(dt, 500, f"锚点表扫描 {dt:.0f}ms 超上限")


@unittest.skipUnless(POPUP_FIXTURE.exists() and POPUP_TPL.exists(),
                     "弹窗夹具未就绪")
class TestRefreshPopupViaAnchorTable(unittest.TestCase):
    """刷新弹窗经锚点表处理（取代 2026-10-23 的个案预检查）。"""

    def test_popup_bypasses_settle_fast_path(self):
        r = make_runner()
        popup = _load("refresh_popup.png")
        it = MagicMock()
        it.text = "今日登录不再提示"
        it.rect = (877, 631, 1094, 664)
        it2 = MagicMock()
        it2.text = "确定"
        it2.rect = (786, 694, 888, 729)
        with patch.object(AutoRunner, "_shot", return_value=popup), \
             patch.object(settle_page, "match_state") as ms, \
             patch.object(AutoRunner, "_ocr", return_value=[it, it2]), \
             patch.object(AutoRunner, "_tap"):
            _state, msg = r.step()
        ms.assert_not_called()          # 快速路径被锚点表短路
        self.assertIn("刷新任务", msg)   # 走到刷新弹窗处理动作


class TestBattleActWithoutItems(unittest.TestCase):
    """锚点表命中 battle 时 items=None 的崩溃回归（2026-11-11 实测事故：
    TypeError: 'NoneType' object is not iterable）。"""

    def test_battle_act_with_none_items(self):
        r = make_runner()
        img = np.zeros((1080, 1920, 3), np.uint8)
        with patch.object(AutoRunner, "_shot", return_value=img),              patch.object(AutoRunner, "_ocr", return_value=[]),              patch.object(AutoRunner, "_tap"),              patch.object(AutoRunner, "_wait_if_paused", return_value=True),              patch.object(AutoRunner, "_publish"),              patch.object(AutoRunner, "_save"),              patch.object(AutoRunner, "classify", return_value="battle"),              patch("src.game.runner.time.sleep"):
            try:
                status, msg = r._act_battle(None)
            except TypeError as exc:
                self.fail(f"items=None 仍崩溃: {exc}")
        self.assertIsInstance(status, str)
        self.assertIsInstance(msg, str)


class TestGiftRegionOcr(unittest.TestCase):
    """赠礼一级：锚点判页 + 区域 OCR（2026-11-11）。
    区域 OCR 的武将识别结果必须与整屏 OCR 完全一致。"""

    @classmethod
    def setUpClass(cls):
        from src.vision.ocr import OCREngine
        cls.ocr = OCREngine(intra_threads=2)

    def test_region_ocr_matches_full_ocr(self):
        from src.game import gift
        img = _load("gift1.png")
        full = self.ocr.read(img)
        region = self.ocr.read(img, region=(300, 700, 1650, 1000))
        heroes_full = {h for h, _ in gift.detect_gift_heroes(full)}
        heroes_region = {h for h, _ in gift.detect_gift_heroes(region)}
        self.assertEqual(heroes_region, heroes_full)
        self.assertTrue(heroes_region, "区域 OCR 应识别到赠礼武将")

    def test_gift1_anchor_has_ocr_region(self):
        table = anchor_table.load_anchor_table()
        e = [x for x in table if x.state == "gift1"]
        self.assertTrue(e, "gift1 应在锚点表中")
        self.assertTrue(e[0].needs_ocr)
        self.assertEqual(tuple(e[0].ocr_region), (300, 700, 1650, 1000))


if __name__ == "__main__":
    unittest.main()
