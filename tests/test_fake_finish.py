"""假收官防护测试（2026-09-17 第 4 局 7 秒假收官的回归用例）。

多局连跑时，上一局遗留的「恭喜获得」浮层会在下一局 step=1 出现，
若不加区分会误判为本局结算 → 7 秒假 done。
"""
from __future__ import annotations

import unittest
from unittest.mock import patch

from src.game import runner as runner_mod
from src.game import settle_page
from src.game.runner import STATE_DONE, STATE_OK, AutoRunner


class FakeItem:
    def __init__(self, text):
        self.text = text
        self.rect = [0, 0, 10, 10]


def make_runner():
    import logging
    return AutoRunner(ctx=None, log=logging.getLogger("test_fake_finish"))


class TestFakeFinish(unittest.TestCase):
    def test_leftover_overlay_not_done(self):
        """开局就见到奖励浮层（上一局遗留）→ 关闭但不算收官。"""
        r = make_runner()
        items = [FakeItem("恭喜获得"), FakeItem("点击空白处关闭")]
        with patch.object(AutoRunner, "_shot", side_effect=lambda: None), \
             patch.object(AutoRunner, "_ocr", return_value=items), \
             patch.object(settle_page, "match_state", return_value=None), \
             patch.object(AutoRunner, "_tap") as tap, \
             patch.object(runner_mod.time, "sleep"):
            status, msg = r.step()
        self.assertEqual(status, STATE_OK)
        self.assertIn("遗留", msg)
        tap.assert_called_once()            # 确实点了关闭
        self.assertFalse(r.in_run)

    def test_real_settlement_is_done(self):
        """真跑过一局（先见地图）再见到奖励浮层 → 才算收官。"""
        r = make_runner()
        map_items = [FakeItem("结束挑战"), FakeItem("当前挑战")]
        reward_items = [FakeItem("恭喜获得"), FakeItem("点击空白处关闭")]
        with patch.object(AutoRunner, "_shot",
                          return_value=None), \
             patch.object(AutoRunner, "_ocr",
                          side_effect=[map_items, reward_items]), \
             patch.object(settle_page, "match_state",
                          side_effect=[None, None]), \
             patch.object(AutoRunner, "_act_map", return_value=(STATE_OK, "选节点")), \
             patch.object(AutoRunner, "_tap"), \
             patch.object(runner_mod.time, "sleep"):
            r.step()                        # 地图步 → in_run=True
            status, msg = r.step()          # 奖励浮层步
        self.assertEqual(status, STATE_DONE)
        self.assertTrue(r.in_run)


if __name__ == "__main__":
    unittest.main()
