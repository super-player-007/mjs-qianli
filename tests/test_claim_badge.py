# -*- coding: utf-8 -*-
"""任务面板「领取」徽章变体测试（2026-10-23 停机事故回归）。"""
from __future__ import annotations

import logging
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import cv2
import numpy as np

from src.game.runner import AutoRunner

STUCK = Path("未加密版/千里单骑助手/runtime/shots/auto_unknown_stuck.png")
TPL = Path("assets/templates/task/btn_claim2.png")
FIX = Path("tests/fixtures/task_claimable.png")


@unittest.skipUnless(STUCK.exists() and TPL.exists() and FIX.exists(),
                     "停机截图/变体模板未就绪")
class TestClaimBadgeVariant(unittest.TestCase):
    def setUp(self):
        self.r = AutoRunner(ctx=None, log=logging.getLogger("t"))
        self.stuck = cv2.imdecode(np.fromfile(str(STUCK), dtype=np.uint8),
                                  cv2.IMREAD_COLOR)

    def test_template_loaded(self):
        self.assertIsNotNone(self.r._claim2_tpl)

    def test_badge_found_on_stuck_page(self):
        """停机页（任务面板带领取徽章）→ claim2 独立匹配有命中。"""
        t = self.r._claim2_tpl
        g = cv2.cvtColor(self.stuck, cv2.COLOR_BGR2GRAY)
        res = cv2.matchTemplate(g, t, cv2.TM_CCOEFF_NORMED)
        self.assertGreaterEqual(float(res.max()), 0.9)

    def test_claim_badges_clicks(self):
        """_claim_task_badges 在停机页上点击徽章并返回点击数。"""
        taps = []
        with patch.object(AutoRunner, "_tap",
                          side_effect=lambda x, y, wait=0: taps.append((x, y))):
            n = self.r._claim_task_badges(self.stuck)
        self.assertGreaterEqual(n, 1)
        self.assertEqual(len(taps), n)

    def test_zero_cross_hit_on_clean_fixtures(self):
        """claim2 锚点对无徽章页面零误报（豁免内嵌徽章的夹具）。"""
        tpl = cv2.imdecode(np.fromfile(str(TPL), dtype=np.uint8),
                           cv2.IMREAD_COLOR)
        g = cv2.cvtColor(tpl, cv2.COLOR_BGR2GRAY)
        exempt = {"task_claimable.png", "task_page_claim.png",
                  "task_page_refresh.png", "settle_run_settle.png",
                  "refresh_popup.png"}
        for f in Path("tests/fixtures").glob("*.png"):
            if f.name in exempt:
                continue
            img = cv2.imdecode(np.fromfile(str(f), dtype=np.uint8),
                               cv2.IMREAD_COLOR)
            if img is None:
                continue
            res = cv2.matchTemplate(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY),
                                    g, cv2.TM_CCOEFF_NORMED)
            self.assertLess(float(res.max()), 0.9, msg=f.name)


if __name__ == "__main__":
    unittest.main()
