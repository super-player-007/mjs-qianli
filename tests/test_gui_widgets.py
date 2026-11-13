# -*- coding: utf-8 -*-
"""GUI 控件与 OCR 帧缓存测试（2026-11-12 重构）。

* ``plan_log_append`` 是纯函数 → 离线可测（不依赖 tkinter/显示器）。
* OCR 帧缓存：同一帧同区域只推理一次，换帧/换区域必须重新推理。
"""
from __future__ import annotations

import unittest

import numpy as np

from src.gui.widgets import (format_metrics, group_log_levels,
                             line_level, plan_log_append, STATE_LABELS)
from src.vision.ocr import OCREngine


class TestPlanLogAppend(unittest.TestCase):
    def test_empty_input(self):
        self.assertEqual(plan_log_append(10, [], 100), (0, ""))

    def test_block_gets_newlines(self):
        overflow, block = plan_log_append(0, ["a", "b\n"], 100)
        self.assertEqual(overflow, 0)
        self.assertEqual(block, "a\nb\n")

    def test_overflow_trims_head(self):
        # 现有 8 行 + 新 5 行 = 13 > 上限 10 → 从头部删 3 行
        overflow, block = plan_log_append(8, ["x"] * 5, 10)
        self.assertEqual(overflow, 3)
        self.assertEqual(block.count("\n"), 5)

    def test_large_batch_single_block(self):
        """批量追加必须拼成一个块（一次 insert），这是降 CPU 的关键。"""
        lines = [f"line {i}" for i in range(200)]
        overflow, block = plan_log_append(0, lines, 2000)
        self.assertEqual(overflow, 0)
        self.assertEqual(block.count("\n"), 200)

    def test_overflow_capped_by_incoming(self):
        """上限小于本批行数时，删除量不应超过已有行数（避免删掉刚插入的）。"""
        overflow, _ = plan_log_append(0, ["x"] * 50, 20)
        self.assertEqual(overflow, 30)

    def test_state_labels_cover_runner_states(self):
        for key in ("idle", "running", "paused", "stopped", "finished"):
            self.assertIn(key, STATE_LABELS)


class TestLogLevels(unittest.TestCase):
    def test_line_level(self):
        self.assertEqual(line_level("10:00:00 [ERROR] 崩了"), "error")
        self.assertEqual(line_level("10:00:00 [WARNING] 漏检"), "warn")
        self.assertEqual(line_level("10:00:00 [INFO] 正常"), "info")
        self.assertEqual(line_level("普通文本"), "info")

    def test_grouping_merges_consecutive(self):
        lines = ["[INFO] a", "[INFO] b", "[WARNING] c", "[INFO] d"]
        groups = group_log_levels(lines)
        self.assertEqual([g[0] for g in groups], ["info", "warn", "info"])
        self.assertEqual(groups[0][1], "[INFO] a\n[INFO] b\n")
        self.assertEqual(groups[1][1], "[WARNING] c\n")

    def test_grouping_single_insert_per_level(self):
        """批量 200 行 INFO 只应产生 1 组（即 1 次 insert）。"""
        groups = group_log_levels(["[INFO] x"] * 200)
        self.assertEqual(len(groups), 1)


class TestFormatMetrics(unittest.TestCase):
    def test_basic(self):
        m = format_metrics({"run": 3, "runs": 20, "layer": 5, "clicks": 128,
                            "step_s": 1.6, "steps": 47})
        self.assertEqual([x[0] for x in m], ["局次", "层数", "点击", "上步耗时"])
        self.assertEqual(m[0][1], "3/20")
        self.assertEqual(m[3][1], "1.6s")

    def test_no_steps_yet(self):
        m = format_metrics({"run": 0, "runs": 1})
        self.assertEqual(m[3][1], "-")

    def test_slow_step_uses_warn_color(self):
        m = format_metrics({"step_s": 12.0, "steps": 9})
        self.assertEqual(m[3][2], "warn")

    def test_runs_never_zero(self):
        m = format_metrics({"run": 1, "runs": 0})
        self.assertEqual(m[0][1], "1/1")


class FakeEngine(OCREngine):
    """跳过真实 onnx 推理，只数调用次数。"""

    def __init__(self):
        super().__init__()
        self.calls = 0

    def _ensure(self) -> bool:          # noqa: D401 — 测试替身
        return True

    def _run_engine(self, canvas):
        self.calls += 1
        return [[[[0, 0], [10, 0], [10, 10], [0, 10]], "测试", 0.99]]


class TestOcrFrameCache(unittest.TestCase):
    def test_same_frame_same_region_uses_cache(self):
        eng = FakeEngine()
        img = np.zeros((100, 100, 3), np.uint8)
        first = eng.read(img)
        second = eng.read(img)
        self.assertEqual(eng.calls, 1, "同一帧同区域不应重复推理")
        self.assertEqual([i.text for i in first], ["测试"])
        self.assertEqual([i.text for i in second], ["测试"])

    def test_new_frame_recomputes(self):
        eng = FakeEngine()
        a = np.zeros((100, 100, 3), np.uint8)
        b = np.ones((100, 100, 3), np.uint8)
        eng.read(a)
        eng.read(b)
        self.assertEqual(eng.calls, 2)

    def test_region_change_recomputes(self):
        eng = FakeEngine()
        img = np.zeros((200, 200, 3), np.uint8)
        eng.read(img, region=(0, 0, 100, 100))
        eng.read(img, region=(0, 0, 100, 100))       # 命中缓存
        eng.read(img, region=(50, 50, 150, 150))     # 新区域 → 重新推理
        self.assertEqual(eng.calls, 2)

    def test_cache_stats(self):
        eng = FakeEngine()
        img = np.zeros((50, 50, 3), np.uint8)
        eng.read(img)
        eng.read(img)
        st = eng.stats()
        self.assertEqual(st["runs"], 1)
        self.assertEqual(st["cache_hits"], 1)

    def test_cache_disabled(self):
        eng = FakeEngine()
        eng.cache_frames = False
        img = np.zeros((50, 50, 3), np.uint8)
        eng.read(img)
        eng.read(img)
        self.assertEqual(eng.calls, 2)


if __name__ == "__main__":
    unittest.main()
