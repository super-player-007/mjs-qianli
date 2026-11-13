"""结算链快速分类测试（2026-10-09：模板匹配替代整屏 OCR）。

覆盖：4 状态正确识别、互相不串、干扰页零命中、金按钮二选一消歧、
模板缺失优雅回退、速度上限。
"""
from __future__ import annotations

import logging
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np

from src.game import settle_page
from src.game.runner import AutoRunner
from src.vision.annotate import read_image

FIX = Path("tests/fixtures")


class FakeItem:
    def __init__(self, text, cx, cy):
        self.text = text
        self.rect = [cx - 80, cy - 16, cx + 80, cy + 16]


class TestSettleMatch(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tpls = settle_page.load_settle_templates()
        cls.pages = {k: read_image(FIX / f"settle_{k}.png")
                     for k in ("next_preview", "settle_confirm",
                               "run_settle", "reward_overlay")}

    def test_each_state_matches_itself(self):
        for state, img in self.pages.items():
            self.assertEqual(settle_page.match_state(
                img, self.tpls), state, msg=state)

    def test_gold_button_pair_disambiguated(self):
        """下一步/领取奖励金按钮同款（互配 0.994）→ 小范围 OCR 消歧。"""
        # next_preview 页：按钮区 OCR 应读到「下一步」
        self.assertEqual(settle_page.match_state(
            self.pages["next_preview"], self.tpls), "next_preview")
        # run_settle 页：按钮区 OCR 应读到「领取奖励」
        self.assertEqual(settle_page.match_state(
            self.pages["run_settle"], self.tpls), "run_settle")

    def test_disambiguation_uses_ocr(self):
        """消歧确实调用了小范围 OCR（按钮文字区域）。"""
        calls = []

        def fake_ocr(img, region=None):
            calls.append(region)
            return [FakeItem("下一步", 958, 953)]

        with patch.object(settle_page, "_best_scores",
                          return_value={"next_preview": 0.99,
                                        "run_settle": 0.994}):
            state = settle_page.match_state(
                self.pages["next_preview"], self.tpls, ocr_fn=fake_ocr)
        self.assertEqual(state, "next_preview")
        self.assertEqual(len(calls), 1)       # 消歧只调一次小范围 OCR

    def test_no_false_positive_on_other_pages(self):
        """地图/战斗/任务页零命中（0.9 阈值）。"""
        for f in ("map_last_layer.png", "battle_target_select.png",
                  "task_page_claim.png"):
            img = read_image(FIX / f)
            self.assertIsNone(settle_page.match_state(img, self.tpls),
                              msg=f)

    def test_missing_templates_graceful(self):
        """模板目录为空 → 返回 None（回退 OCR 分类），不抛异常。"""
        self.assertIsNone(settle_page.match_state(
            self.pages["next_preview"], {}))

    def test_speed(self):
        """4 模板连扫单页 ≤1.5s（对比整屏 OCR ~1.9s；防 10 倍级回退，
        阈值放宽容忍系统负载抖动——2026-10-12 高负载下 0.63s 误报）。"""
        t0 = time.time()
        settle_page.match_state(self.pages["run_settle"], self.tpls)
        self.assertLess(time.time() - t0, 1.5)


class TestStepFastPath(unittest.TestCase):
    """step() 快速路径：结算页命中模板时不做整屏 OCR。"""

    def test_settle_state_skips_ocr(self):
        import logging
        r = AutoRunner(ctx=None, log=logging.getLogger("t"))
        img = read_image(FIX / "settle_next_preview.png")
        ocr_calls = []

        def fake_ocr(target, region=None):
            ocr_calls.append(region)
            return []
        with patch.object(AutoRunner, "_shot", return_value=img), \
             patch.object(settle_page, "match_state",
                          return_value="next_preview"), \
             patch.object(AutoRunner, "_ocr",
                          side_effect=fake_ocr), \
             patch.object(AutoRunner, "_tap",
                          side_effect=lambda x, y, wait=0: None), \
             patch("src.game.runner.time.sleep"):
            status, msg = r.step()
        # 2026-11-11 操作序列架构：结算链在单个动作内完成（空白→下一步→确认），
        # 消息变为「结算序列（...）」；关键契约仍是整屏 OCR 零调用。
        self.assertIn("结算序列", msg)
        self.assertEqual(ocr_calls, [])       # 整屏 OCR 未被调用



class TestNextPreviewWanshengVariant(unittest.TestCase):
    """完胜预览页「下一步」按钮变体（2026-10-21）。
    完胜页按钮外观与普通预览页不同（原模板仅 0.584）→ 独立变体锚点。
    夹具 next_preview_wansheng.png 来自用户实测截图。"""

    FIXTURE = Path("tests/fixtures/next_preview_wansheng.png")
    TPL = Path("assets/templates/settle/next_preview_wansheng.png")

    def setUp(self):
        if not (self.FIXTURE.exists() and self.TPL.exists()):
            self.skipTest("完胜页变体模板未安装")

    def test_wansheng_page_matches_next_preview(self):
        img = read_image(self.FIXTURE)
        tpls = settle_page.load_settle_templates()
        self.assertIn("next_preview", tpls)
        self.assertEqual(settle_page.match_state(img, tpls), "next_preview")

    def test_original_template_still_covers_ordinary_page(self):
        """普通预览页夹具仍由原模板命中（变体不挤掉原有覆盖）。"""
        img = read_image(Path("tests/fixtures/settle_next_preview.png"))
        tpls = settle_page.load_settle_templates()
        self.assertEqual(settle_page.match_state(img, tpls), "next_preview")

    def test_variant_zero_cross_hit(self):
        """变体锚点对全部其他夹具零误报。"""
        tpl = cv2.imdecode(np.fromfile(str(self.TPL), dtype=np.uint8),
                           cv2.IMREAD_COLOR)
        g = cv2.cvtColor(tpl, cv2.COLOR_BGR2GRAY)
        for f in Path("tests/fixtures").glob("*.png"):
            if f.name == self.FIXTURE.name:
                continue
            img = read_image(f)
            if img is None:
                continue
            res = cv2.matchTemplate(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY),
                                    g, cv2.TM_CCOEFF_NORMED)
            self.assertLess(float(res.max()), 0.9, msg=f.name)


if __name__ == "__main__":

    unittest.main()
