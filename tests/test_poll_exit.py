# -*- coding: utf-8 -*-
"""托管轮询退出条件测试（2026-11-12 完胜浮层卡死修复）。

游戏更新后：完胜浮层弹出时金盘面板仍开着，「投降」按钮在浮层下持续可见。
旧快路径只看「投降」→ 轮询永远判「还在打」，卡死 10+ 分钟。
修复：快路径先查结算锚点（next_preview/settle_confirm/run_settle/
reward_overlay），命中即判战斗结束。
"""
from __future__ import annotations

import logging
import unittest
from unittest.mock import patch

from src.game.runner import STATE_OK, AutoRunner


def _runner() -> AutoRunner:
    r = AutoRunner(ctx=None, log=logging.getLogger("test"))
    r.poll_sleep = 0.0
    return r


class TestPollExitOnSettleAnchor(unittest.TestCase):
    def _run_poll(self, anchor_state: str):
        """模拟「取消托管在屏 + 指定锚点状态」的一轮等待，返回结果。"""
        r = _runner()
        items = [type("I", (), {"text": "取消托管", "center": (1846, 280),
                                "rect": (1814, 263, 1879, 296),
                                "score": 1.0})()]
        with patch.object(r, "_shot", return_value=object()), \
             patch.object(r, "_anchor_state", return_value=anchor_state), \
             patch.object(r, "_ocr", return_value=[]), \
             patch.object(r, "_settle_kind", return_value=None), \
             patch("src.game.runner.time.sleep"):
            return r._act_battle(items)

    def test_exits_on_next_preview(self):
        """完胜浮层（结算锚点命中）必须立刻退出轮询——卡死回归。"""
        status, msg = self._run_poll("next_preview")
        self.assertEqual(status, STATE_OK)
        self.assertIn("结算锚点", msg)

    def test_exits_on_run_settle(self):
        status, msg = self._run_poll("run_settle")
        self.assertEqual(status, STATE_OK)
        self.assertIn("run_settle", msg)

    def test_keeps_waiting_while_battle(self):
        """投降可见且无结算锚点 → 维持快路径等待（心跳持续计数）。"""
        r = _runner()
        items = [type("I", (), {"text": "取消托管", "center": (1846, 280),
                                "rect": (1814, 263, 1879, 296),
                                "score": 1.0})()]
        calls = {"n": 0}

        def hb(poll_i):
            calls["n"] += 1
            if calls["n"] >= 5:
                raise KeyboardInterrupt      # 数够 5 轮即跳出，证明一直在等

        with patch.object(r, "_shot", return_value=object()), \
             patch.object(r, "_anchor_state", return_value="battle"), \
             patch.object(r, "_ocr", return_value=[]), \
             patch.object(r, "_poll_heartbeat", hb), \
             patch("src.game.runner.invite.find_ignore_button",
                   return_value=None), \
             patch("src.game.runner.time.sleep"):
            self.assertRaises(KeyboardInterrupt, r._act_battle, items)
        self.assertEqual(calls["n"], 5, "应持续快路径轮询而非退出")


if __name__ == "__main__":
    unittest.main()
