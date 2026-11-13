# -*- coding: utf-8 -*-
"""unknown 过渡帧主动探测测试（2026-11-12）。

选节点后必经过渡动画（0.5~1.5s），原实现盲睡 2.5s 每次白等 ~2s。
改为每 0.5s 抓帧只跑锚点表，命中即提前结束等待。
"""
from __future__ import annotations

import logging
import time
import unittest
from unittest.mock import patch

from src.game.runner import AutoRunner


def _runner() -> AutoRunner:
    r = AutoRunner(ctx=None, log=logging.getLogger("test"))
    r.poll_sleep = 0.0
    return r


class TestWaitTransitionSettled(unittest.TestCase):
    def test_exits_early_when_anchor_hits(self):
        """第二次探测锚点命中 → 提前返回（只探测 2 次）。"""
        r = _runner()
        calls = {"n": 0}

        def anchor(img):
            calls["n"] += 1
            return "battle_confirm" if calls["n"] >= 2 else None

        with patch.object(r, "_shot", return_value=object()), \
             patch.object(r, "_anchor_state", side_effect=anchor), \
             patch("src.game.runner.time.sleep"):
            t0 = time.time()
            r._wait_transition_settled(timeout=10)
        self.assertEqual(calls["n"], 2, "锚点命中应立即返回")

    def test_falls_back_to_full_wait_when_never_hits(self):
        """锚点始终不认识（如休息页过渡）→ 走满原时长兜底。"""
        r = _runner()
        with patch.object(r, "_shot", return_value=object()), \
             patch.object(r, "_anchor_state", return_value=None), \
             patch("src.game.runner.time.sleep") as sl:
            r._wait_transition_settled(timeout=2.5)
        # sleep 被mock成 no-op 时循环按真实时钟空转，次数远超 5；
        # 只需断言"探测贯穿了整个兜底窗口"（≥ 0.5s 间隔的理论次数 5）
        self.assertGreaterEqual(sl.call_count, 5)

    def test_probe_error_falls_back(self):
        """探测抛异常（截图失败等）→ 静默走兜底，不抛出。"""
        r = _runner()
        with patch.object(r, "_shot", side_effect=RuntimeError("x")), \
             patch("src.game.runner.time.sleep"):
            r._wait_transition_settled(timeout=1)   # 不应抛出


if __name__ == "__main__":
    unittest.main()
