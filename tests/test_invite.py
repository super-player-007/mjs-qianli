"""游戏邀请弹窗处理测试（2026-10-11 用户需求：模板匹配点「忽略」）。"""
from __future__ import annotations

import logging
import unittest
from pathlib import Path
from unittest.mock import patch

from src.game import invite
from src.game.runner import AutoRunner
from src.vision.annotate import read_image

FIX_CENTER = Path("tests/fixtures/invite_popup_center.png")
FIX_OFFSET = Path("tests/fixtures/invite_popup_offset.png")


class TestFindIgnoreButton(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tpls = invite.load_invite_templates()

    def test_found_on_center_fixture(self):
        img = read_image(FIX_CENTER)
        btn = invite.find_ignore_button(img, templates=self.tpls)
        self.assertIsNotNone(btn)
        # 弹窗贴在画布 (561,324)，忽略按钮在弹窗内 (541,381) → 全局 ~(1102,705)
        self.assertAlmostEqual(btn[0], 561 + 541, delta=4)
        self.assertAlmostEqual(btn[1], 324 + 381, delta=4)

    def test_found_on_offset_fixture(self):
        """弹窗出现位置不同也能匹配（不依赖写死坐标）。"""
        img = read_image(FIX_OFFSET)
        btn = invite.find_ignore_button(img, templates=self.tpls)
        self.assertIsNotNone(btn)
        self.assertAlmostEqual(btn[0], 200 + 541, delta=4)
        self.assertAlmostEqual(btn[1], 120 + 381, delta=4)

    def test_no_false_positive_on_other_pages(self):
        for f in ("settle_next_preview.png", "task_page_claim.png"):
            img = read_image(Path("tests/fixtures") / f)
            self.assertIsNone(invite.find_ignore_button(
                img, templates=self.tpls), msg=f)

    def test_missing_templates_graceful(self):
        img = read_image(FIX_CENTER)
        self.assertIsNone(invite.find_ignore_button(img, templates={}))


class TestStepInvitePrecheck(unittest.TestCase):
    """step() 前置检查：命中弹窗 → 点忽略 → 本步直接返回。"""

    def test_step_dismisses_invite(self):
        r = AutoRunner(ctx=None, log=logging.getLogger("t"))
        img = read_image(FIX_CENTER)
        taps = []
        with patch.object(AutoRunner, "_shot", return_value=img), \
             patch.object(AutoRunner, "_ocr",
                          side_effect=AssertionError("不应走 OCR")), \
             patch.object(AutoRunner, "_tap",
                          side_effect=lambda x, y, wait=0:
                          taps.append((x, y))), \
             patch("src.game.runner.time.sleep"):
            status, msg = r.step()
        self.assertEqual(msg, "忽略游戏邀请")
        self.assertEqual(len(taps), 1)


if __name__ == "__main__":
    unittest.main()
