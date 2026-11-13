"""任务奖励巡检测试（用户需求 + 2026-10-07 模板匹配提速）。

任务页 2×3 六槽位：完成显示「领取奖励」、未完成显示「刷新×1」，
两种按钮都可能多个。单循环：出现任一按钮就点，直到全部消失 → 返回。

识别层（task_page.find_buttons）用真实任务页截图夹具离线验证；
流程层 mock find_buttons 验证点击序列。
"""
from __future__ import annotations

import logging
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

import src.game.runner as runner_mod
from src.game import task_page
from src.game.runner import (TASK_BACK_POS, TASK_CHECK_INTERVAL,
                             TASK_ICON_POS, AutoRunner)
from src.vision.annotate import read_image

# 2026-11-13 游戏更新：任务页 UI 改版，夹具换成新版（4 领取奖励 + 1 刷新x1）；
# 旧皮肤夹具 task_page_claim/refresh.png 留档不再使用
FIX_NEW = Path("tests/fixtures/task_page_new.png")
#: 新版任务页上 5 个按钮的真实位置（模板匹配应全部命中）
EXPECT_BUTTONS = {
    "claim": [(1471, 525), (600, 857), (1035, 857), (1471, 857)],
    "refresh": [(561, 525)],
}


class TestFindButtons(unittest.TestCase):
    """识别层：真实夹具上的模板匹配（2026-11-13 新版任务页）。"""

    @classmethod
    def setUpClass(cls):
        cls.tpls = task_page.load_task_templates()
        cls.img = read_image(FIX_NEW)

    def test_find_all_five_buttons(self):
        """新版任务页：4 领取奖励 + 1 刷新x1 全部命中且位置正确。"""
        btns = task_page.find_buttons(self.img, templates=self.tpls)
        self.assertEqual(len(btns), 5, "应命中 4 领取 + 1 刷新")
        for kind in ("claim", "refresh"):
            got = sorted((b.cx, b.cy) for b in btns if b.kind == kind)
            want = sorted(EXPECT_BUTTONS[kind])
            self.assertEqual(len(got), len(want), msg=kind)
            for (gx, gy), (wx, wy) in zip(got, want):
                self.assertAlmostEqual(gx, wx, delta=6, msg=f"{kind} x")
                self.assertAlmostEqual(gy, wy, delta=6, msg=f"{kind} y")

    def test_scores_above_threshold(self):
        for b in task_page.find_buttons(self.img, templates=self.tpls):
            self.assertGreaterEqual(b.score, 0.88, msg=str(b))

    def test_blank_page_no_buttons(self):
        blank = np.full((1080, 1920, 3), 40, dtype=np.uint8)
        self.assertEqual(task_page.find_buttons(blank, templates=self.tpls), [])

    def test_speed(self):
        """模板匹配单页 ≤1.0s（对比整屏 OCR ~2s；防 10 倍级回退，
        阈值放宽容忍系统负载抖动——2026-10-12 高负载下 0.43s 误报）。"""
        t0 = time.time()
        task_page.find_buttons(self.img, templates=self.tpls)
        self.assertLess(time.time() - t0, 1.0)


class TestTaskRewardFlow(unittest.TestCase):
    """流程层：mock find_buttons，验证点击序列与终止条件。"""

    def _make(self):
        r = AutoRunner(ctx=None, log=logging.getLogger("t"))
        taps = []
        return r, taps

    def _run(self, r, taps, find_results):
        """find_results: 每次 find_buttons 调用的返回值序列。"""
        seq = iter(find_results)
        with patch.object(AutoRunner, "_shot", side_effect=lambda: object()), \
             patch.object(task_page, "find_buttons",
                          side_effect=lambda img, **kw: next(seq)), \
             patch.object(AutoRunner, "_ocr", return_value=[]), \
             patch.object(AutoRunner, "_tap",
                          side_effect=lambda x, y, wait=0: taps.append((x, y))), \
             patch("src.game.runner.time.sleep"):
            r._task_reward_flow()

    def test_no_buttons_back_immediately(self):
        """情况 1：无完成（无任何按钮）→ 直接返回。"""
        r, taps = self._make()
        self._run(r, taps, [[]])
        self.assertEqual(taps, [TASK_ICON_POS, TASK_BACK_POS])

    def test_single_loop_claim_refresh_mixed(self):
        """情况 2：领取+刷新混合同屏 → 逐个点完（无按钮）→ 返回。"""
        r, taps = self._make()
        results = [
            [task_page.TaskButton("claim", 900, 920, 0.99),
             task_page.TaskButton("refresh", 1058, 578, 0.98)],
            [task_page.TaskButton("refresh", 1058, 578, 0.98)],
            [],
        ]
        self._run(r, taps, results)
        self.assertEqual(taps, [TASK_ICON_POS, (900, 920), (1058, 578),
                                TASK_BACK_POS])

    def test_missed_click_is_retried(self):
        """没点中自动补点：点完后按钮仍在 → 再点一次。"""
        r, taps = self._make()
        results = [
            [task_page.TaskButton("claim", 900, 920, 0.99)],
            [task_page.TaskButton("claim", 900, 920, 0.99)],   # 仍在=没点中
            [],
        ]
        self._run(r, taps, results)
        self.assertEqual(taps, [TASK_ICON_POS, (900, 920), (900, 920),
                                TASK_BACK_POS])

    def test_exception_falls_back_to_back(self):
        """巡检中途异常 → 吞掉并兜底点返回，不影响主流程。"""
        r, taps = self._make()
        with patch.object(AutoRunner, "_tap",
                          side_effect=lambda x, y, wait=0: taps.append((x, y))), \
             patch.object(AutoRunner, "_shot",
                          side_effect=RuntimeError("boom")), \
             patch("src.game.runner.time.sleep"):
            r._task_reward_flow()                 # 不应抛出
        self.assertEqual(taps, [TASK_ICON_POS, TASK_BACK_POS])

    def test_interval_constant(self):
        """巡检间隔 5 分钟（用户 2026-10-07 修改）。"""
        self.assertEqual(TASK_CHECK_INTERVAL, 300)
        self.assertEqual(TASK_ICON_POS, (1620, 150))
        self.assertEqual(TASK_BACK_POS, (1879, 183))


class TestTokenZeroPrecheck(unittest.TestCase):
    """军令状为 0 的前置判断（2026-10-11 用户需求）：直接返回，不点任何按钮。"""

    class FakeItem:
        def __init__(self, text, cx, cy):
            self.text = text
            self.rect = [cx - 30, cy - 14, cx + 30, cy + 14]

    def _make(self):
        r = AutoRunner(ctx=None, log=logging.getLogger("t"))
        taps = []
        return r, taps

    def _run(self, r, taps, token_region_items, find_results):
        seq = iter(find_results)

        def fake_ocr(img, region=None):
            if region == AutoRunner.TASK_TOKEN_REGION:
                return token_region_items
            return []

        with patch.object(AutoRunner, "_shot", side_effect=lambda: object()), \
             patch.object(task_page, "find_buttons",
                          side_effect=lambda img, **kw: next(seq)), \
             patch.object(AutoRunner, "_ocr", side_effect=fake_ocr), \
             patch.object(AutoRunner, "_tap",
                          side_effect=lambda x, y, wait=0: taps.append((x, y))), \
             patch("src.game.runner.time.sleep"):
            r._task_reward_flow()

    def test_tokens_zero_returns_immediately(self):
        """军令状 0 → 只点任务图标和返回，不碰领奖/刷新按钮。"""
        r, taps = self._make()
        self._run(r, taps, [self.FakeItem("0", 1660, 130)], [[]])
        self.assertEqual(taps, [TASK_ICON_POS, TASK_BACK_POS])

    def test_tokens_nonzero_proceeds(self):
        """军令状非 0（如 10）→ 正常领奖流程。"""
        r, taps = self._make()
        self._run(r, taps, [self.FakeItem("10", 1700, 130)],
                  [[task_page.TaskButton("claim", 900, 920, 0.99)], []])
        self.assertEqual(taps, [TASK_ICON_POS, (900, 920), TASK_BACK_POS])

    def test_tokens_unreadable_proceeds(self):
        """读不到数字 → 按非 0 处理（宁多巡检，不因 OCR 抖动漏领）。"""
        r, taps = self._make()
        self._run(r, taps, [], [[]])
        self.assertEqual(taps, [TASK_ICON_POS, TASK_BACK_POS])


if __name__ == "__main__":
    unittest.main()
