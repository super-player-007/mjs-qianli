# -*- coding: utf-8 -*-
"""就绪探测（A 优化 2026-10-20）单元测试：_wait_ready / _settle_probe /
地图双击探测。全部 mock，不依赖模拟器。"""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

import logging

from src.game import settle_page
from src.game.runner import AutoRunner


def make_runner():
    return AutoRunner(ctx=None, log=logging.getLogger("t"))


class TestWaitReady(unittest.TestCase):
    def test_probe_true_first_shot(self):
        """probe 首帧即真 → 立即返回 True，不睡满 timeout。"""
        r = make_runner()
        calls = {"n": 0}
        with patch.object(AutoRunner, "_shot",
                          side_effect=lambda *a, **k: object()), \
             patch("src.game.runner.time.sleep") as slp:
            ok = r._wait_ready(lambda img: True, timeout=3.0)
        self.assertTrue(ok)
        slp.assert_not_called()

    def test_probe_false_timeout(self):
        """probe 永假 → 超时返回 False。"""
        r = make_runner()
        with patch.object(AutoRunner, "_shot",
                          side_effect=lambda *a, **k: object()), \
             patch("src.game.runner.time.sleep"):
            ok = r._wait_ready(lambda img: False, timeout=0.2, interval=0.05)
        self.assertFalse(ok)

    def test_probe_exception_counts_as_not_ready(self):
        """probe 抛异常按未就绪处理，不崩。"""
        r = make_runner()

        def boom(img):
            raise RuntimeError("boom")
        with patch.object(AutoRunner, "_shot",
                          side_effect=lambda *a, **k: object()), \
             patch("src.game.runner.time.sleep"):
            ok = r._wait_ready(boom, timeout=0.2, interval=0.05)
        self.assertFalse(ok)

    def test_probe_true_later(self):
        """第 3 帧才就绪 → True，且中途有 sleep。"""
        r = make_runner()
        seq = [False, False, True]
        with patch.object(AutoRunner, "_shot",
                          side_effect=lambda *a, **k: object()), \
             patch("src.game.runner.time.sleep") as slp:
            ok = r._wait_ready(lambda img: seq.pop(0), timeout=5.0)
        self.assertTrue(ok)
        self.assertTrue(slp.called)


class TestSettleProbe(unittest.TestCase):
    def setUp(self):
        self.r = make_runner()
        self.r._settle_templates = {}

    def test_victory_blank_waits_for_any_settle_page(self):
        """victory_blank（OCR 态）→ 出现任意结算模板页才算就绪。"""
        probe = self.r._settle_probe("victory_blank")
        with patch.object(settle_page, "match_state",
                          return_value=None), \
             patch.object(AutoRunner, "_shot",
                          side_effect=lambda *a, **k: object()):
            self.assertFalse(self.r._wait_ready(probe, timeout=0.15,
                                                interval=0.05))
        with patch.object(settle_page, "match_state",
                          return_value="next_preview"), \
             patch.object(AutoRunner, "_shot",
                          side_effect=lambda *a, **k: object()):
            self.assertTrue(self.r._wait_ready(probe, timeout=1.0))

    def test_next_preview_waits_for_other_state(self):
        """next_preview → 仍是 next_preview 不算就绪。"""
        probe = self.r._settle_probe("next_preview")
        with patch.object(settle_page, "match_state",
                          return_value="next_preview"), \
             patch.object(AutoRunner, "_shot",
                          side_effect=lambda *a, **k: object()):
            self.assertFalse(self.r._wait_ready(probe, timeout=0.15,
                                                interval=0.05))
        with patch.object(settle_page, "match_state",
                          return_value="settle_confirm"), \
             patch.object(AutoRunner, "_shot",
                          side_effect=lambda *a, **k: object()):
            self.assertTrue(self.r._wait_ready(probe, timeout=1.0))


class TestMapDoubleTapProbe(unittest.TestCase):
    def _run_map_once(self, persist: bool):
        """persist=True: 节点始终可见（→ 补第二击）；False: 探测即消失。
        返回 _tap 调用次数。"""
        r = make_runner()
        r.layer = 0
        r.tpl_dir = "assets/templates/run_map"
        taps = []
        node = MagicMock()
        node.tap = (667, 397)
        node.kind = "rest"
        calls = {"n": 0}

        def analyzer(img, tpl_dir=None):
            calls["n"] += 1
            if calls["n"] == 1:
                return [node]          # 地图上找到节点
            return [node] if persist else []

        with patch.object(AutoRunner, "_shot",
                          side_effect=lambda *a, **k: object()), \
             patch("src.game.runner.analyze_nodes",
                   side_effect=analyzer), \
             patch.object(AutoRunner, "_tap",
                          side_effect=lambda x, y, wait=0: taps.append((x, y))), \
             patch("src.game.runner.time.sleep"), \
             patch("src.game.runner.recover_classified_node",
                   return_value=None), \
             patch("src.game.runner.load_node_templates", return_value={}), \
             patch("src.game.runner.select_node",
                   return_value=(node, "休息(命中)")):
            r._act_map()
        return taps

    def test_nodes_gone_single_tap(self):
        """第一次探测就节点消失（已进入）→ 只点一次。"""
        taps = self._run_map_once(False)
        self.assertEqual(len(taps), 1)

    def test_nodes_persist_double_tap(self):
        """节点持续可见 → 兜底补第二次点击。"""
        node = MagicMock()
        taps = self._run_map_once(True)
        self.assertEqual(len(taps), 2)


if __name__ == "__main__":
    unittest.main()
