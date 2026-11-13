# -*- coding: utf-8 -*-
"""操作序列架构测试（2026-11-11）：帧复用 / 序列超时回退 / 结算序列。"""
from __future__ import annotations

import logging
import unittest
from unittest.mock import MagicMock, patch

import numpy as np

from src.game.runner import AutoRunner


def make_runner():
    return AutoRunner(ctx=None, log=logging.getLogger("t"))


class TestFrameReuse(unittest.TestCase):
    def test_reuse_within_ttl(self):
        """0.35s 内连续截图只截一次。"""
        r = make_runner()
        shot = np.zeros((1080, 1920, 3), np.uint8)
        dev = MagicMock()
        dev.screenshot.return_value = shot
        r.ctx = MagicMock()
        r.ctx.device = dev
        r._shot()
        r._shot()
        self.assertEqual(dev.screenshot.call_count, 1)

    def test_tap_invalidates(self):
        """点击后缓存失效 → 重新截图。"""
        r = make_runner()
        shot = np.zeros((1080, 1920, 3), np.uint8)
        dev = MagicMock()
        dev.screenshot.return_value = shot
        r.ctx = MagicMock()
        r.ctx.device = dev
        r._shot()
        with patch("src.game.runner.time.sleep"):
            r._tap(10, 10, wait=0)
        r._shot()
        self.assertEqual(dev.screenshot.call_count, 2)


class TestRunSteps(unittest.TestCase):
    def test_all_steps_pass(self):
        r = make_runner()
        taps = []
        with patch.object(AutoRunner, "_tap",
                          side_effect=lambda x, y, wait=0: taps.append((x, y))), \
             patch.object(AutoRunner, "_wait_ready", return_value=True), \
             patch("src.game.runner.time.sleep"):
            ok = r._run_steps([
                {"tap": (1, 2), "probe": lambda im: True},
                {"tap": (3, 4), "probe": None},
            ], "测试")
        self.assertTrue(ok)
        self.assertEqual(taps, [(1, 2), (3, 4)])

    def test_timeout_stops_sequence(self):
        """任一步探测超时 → 返回 False（交回主循环）。"""
        r = make_runner()
        taps = []
        with patch.object(AutoRunner, "_tap",
                          side_effect=lambda x, y, wait=0: taps.append((x, y))), \
             patch.object(AutoRunner, "_wait_ready", return_value=False), \
             patch("src.game.runner.time.sleep"):
            ok = r._run_steps([
                {"tap": (1, 2), "probe": lambda im: True},
                {"tap": (3, 4), "probe": lambda im: True},
            ], "测试")
        self.assertFalse(ok)
        self.assertEqual(taps, [(1, 2)])       # 超时后不再执行后续步骤

    def test_conditional_step_skipped(self):
        """if 条件不满足的步骤被跳过。"""
        r = make_runner()
        taps = []
        with patch.object(AutoRunner, "_shot", return_value=object()), \
             patch.object(AutoRunner, "_tap",
                          side_effect=lambda x, y, wait=0: taps.append((x, y))), \
             patch("src.game.runner.time.sleep"):
            ok = r._run_steps([
                {"tap": (1, 2), "if": lambda im: False},
                {"tap": (3, 4)},
            ], "测试")
        self.assertTrue(ok)
        self.assertEqual(taps, [(3, 4)])


class TestSettleSequence(unittest.TestCase):
    def test_next_preview_then_confirm(self):
        """结算序列：next_preview → 点下一步 → settle_confirm → 点确认 → 结束。"""
        r = make_runner()
        taps = []
        kinds = ["preview", "confirm"]
        with patch.object(AutoRunner, "_shot", return_value=object()), \
             patch.object(AutoRunner, "_settle_kind",
                          side_effect=lambda im: kinds.pop(0) if kinds else None), \
             patch.object(AutoRunner, "_tap",
                          side_effect=lambda x, y, wait=0: taps.append((x, y))), \
             patch.object(AutoRunner, "_wait_ready", return_value=True), \
             patch.object(AutoRunner, "_claim_task_badges", return_value=0), \
             patch("src.game.runner.time.sleep"):
            status, msg = r._settle_sequence()
        self.assertEqual(taps, [(958, 953), (960, 953)])
        self.assertIn("下一步", msg)
        self.assertIn("确认", msg)

    def test_no_settle_page_breaks(self):
        """不在结算页 → 零点击直接返回。"""
        r = make_runner()
        taps = []
        with patch.object(AutoRunner, "_shot", return_value=object()), \
             patch.object(AutoRunner, "_settle_kind", return_value=None), \
             patch.object(AutoRunner, "_tap",
                          side_effect=lambda x, y, wait=0: taps.append((x, y))), \
             patch.object(AutoRunner, "_claim_task_badges", return_value=0), \
             patch("src.game.runner.time.sleep"):
            status, msg = r._settle_sequence()
        self.assertEqual(taps, [])
        self.assertIn("已无结算页", msg)


class TestProbeUsesFreshFrames(unittest.TestCase):
    """探测循环必须绕过帧缓存（2026-11-11 事故：缓存 0.35s > 探测间隔
    0.28s，探测反复看同一帧 → 每次耗满超时）。"""

    def test_probe_sees_page_change(self):
        r = make_runner()
        frames = [np.zeros((10, 10, 3), np.uint8),
                  np.ones((10, 10, 3), np.uint8)]
        dev = MagicMock()
        dev.screenshot.side_effect = frames + [frames[-1]] * 5
        r.ctx = MagicMock()
        r.ctx.device = dev
        seen = []

        def probe(img):
            seen.append(float(img.mean()))
            return float(img.mean()) > 0.5      # 第二帧（值 1.0）才算就绪

        ok = r._wait_ready(probe, timeout=2.0, interval=0.05)
        self.assertTrue(ok)
        self.assertGreaterEqual(dev.screenshot.call_count, 2,
                                "探测必须重新截图，不能复用旧帧")
        self.assertEqual(len(set(seen)) >= 1, True)


if __name__ == "__main__":
    unittest.main()
