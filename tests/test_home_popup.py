# -*- coding: utf-8 -*-
"""主页弹窗遮挡识别与关闭测试（2026-11-14 麟趾献瑞事故）。

活动弹窗样式会换、✕ 位置不固定 → 方案 A：底部功能栏可见 + 顶部导航
（丹青阁/招募）被挡 = home_popup；动作按候选坐标序列点 ✕，每点探测
主页是否露出；连续 4 步未恢复停机存图（补候选坐标即可）。
"""
from __future__ import annotations

import logging
import unittest
from unittest.mock import patch

from src.game.runner import POPUP_CLOSE_POS, STATE_STOP, AutoRunner


def _item(text, cx=0, cy=0):
    return type("I", (), {"text": text, "center": (cx, cy),
                          "rect": (cx - 40, cy - 16, cx + 40, cy + 16),
                          "score": 1.0})()


def _nav_items():
    """主页被弹窗遮挡帧：底部功能栏可见、顶部导航被挡。"""
    return [_item("S公会", 924, 939), _item("外好友", 1107, 937),
            _item("伙伴", 1293, 938), _item("武将", 1475, 939),
            _item("任务", 1657, 938), _item("麟趾献瑞", 700, 300)]


class TestHomePopup(unittest.TestCase):
    def _runner(self) -> AutoRunner:
        r = AutoRunner(ctx=None, log=logging.getLogger("test"))
        r.poll_sleep = 0.0
        return r

    def test_classify_home_popup(self):
        """底栏可见 + 顶部导航被挡 → home_popup。"""
        r = self._runner()
        self.assertEqual(r.classify(_nav_items()), "home_popup")

    def test_map_page_not_home_popup(self):
        """局内地图页（结束挑战+图例+聊天条公会）→ map 语义，绝不判 home_popup。

        2026-11-15 夜局事故：聊天条给公会、图例给武将、偶发任务 →
        无排除守卫时地图页被误判 home_popup，在地图上点天空，连 4 步停机。
        """
        r = self._runner()
        items = [_item("结束挑战", 1657, 938), _item("当前挑战：21 层", 200, 200),
                 _item("武将·", 1475, 400), _item("伙伴", 1293, 500),
                 _item("【公会招新】", 203, 960)]
        self.assertNotEqual(r.classify(items), "home_popup")

    def test_entry_page_not_home_popup(self):
        """入口页（开始挑战）→ 不判 home_popup。"""
        r = self._runner()
        items = [_item("S公会", 924, 939), _item("好友", 1107, 937),
                 _item("武将", 1475, 939), _item("任务", 1657, 938),
                 _item("开始挑战", 1667, 750), _item("战役属性", 1500, 400),
                 _item("难度选择", 1353, 937)]
        self.assertNotEqual(r.classify(items), "home_popup")

    def test_clean_home_still_home(self):
        """干净主页（顶部导航在）→ home，不受新规则影响。"""
        r = self._runner()
        items = _nav_items() + [_item("丹青阁", 200, 150),
                                _item("招募", 1700, 150)]
        self.assertEqual(r.classify(items), "home")

    def test_in_run_never_home_popup(self):
        """局内（in_run=True）绝不判 home_popup，即使四词凑齐。"""
        r = self._runner()
        r.in_run = True
        items = _nav_items()
        self.assertNotEqual(r.classify(items), "home_popup")

    def test_non_consecutive_streak_resets(self):
        """误判分散在多步里（非连续）→ streak 清零，不会误停机。"""
        r = self._runner()
        r._home_popup_streak = 4
        r._home_popup_last_step = 10   # 当前 steps=0，间隔很远
        with patch.object(AutoRunner, "_shot", return_value=object()),              patch.object(AutoRunner, "_ocr", return_value=[]),              patch.object(AutoRunner, "_tap"):
            status, msg = _run_one_step(r)
        self.assertNotEqual(status, STATE_STOP, msg=msg)
        self.assertEqual(r._home_popup_streak, 1)

    def test_close_candidates_tapped_in_order(self):
        """未恢复 → 按候选顺序点完全部 ✕，等待下一步继续。"""
        r = self._runner()
        taps = []
        with patch.object(AutoRunner, "_shot", return_value=object()), \
             patch.object(AutoRunner, "_ocr", return_value=[]), \
             patch.object(AutoRunner, "_tap",
                          side_effect=lambda x, y, wait=0: taps.append((x, y))):
            _s, msg = _run_one_step(r)
        self.assertEqual(taps, list(POPUP_CLOSE_POS), msg=msg)
        self.assertIn("未关完", msg)

    def test_recovered_mid_candidates(self):
        """点第 2 个候选后主页恢复 → 停止点击并重置计数。"""
        r = self._runner()
        r._home_popup_streak = 1
        taps = []
        rec = iter([False, True])

        def probe():
            return next(rec)

        with patch.object(AutoRunner, "_shot", return_value=object()), \
             patch.object(AutoRunner, "_home_recovered",
                          side_effect=probe), \
             patch.object(AutoRunner, "_tap",
                          side_effect=lambda x, y, wait=0: taps.append((x, y))):
            _s, msg = _run_one_step(r)
        self.assertEqual(taps, list(POPUP_CLOSE_POS)[:2])
        self.assertIn("已关闭", msg)
        self.assertEqual(r._home_popup_streak, 0)

    def test_runaway_stops_after_4_steps(self):
        """连续 4 步未关完 → 第 5 步停机存图。"""
        r = self._runner()
        r._home_popup_streak = 4
        r._home_popup_last_step = r.steps - 1   # 标记为连续步
        with patch.object(AutoRunner, "_shot", return_value=object()), \
             patch.object(AutoRunner, "_save", return_value=None), \
             patch.object(AutoRunner, "_tap"):
            status, msg = _run_one_step(r)
        self.assertEqual(status, STATE_STOP)
        self.assertIn("停机", msg)


def _run_one_step(r: AutoRunner):
    """单步执行 home_popup 动作分支（绕过完整 step 判页链）。"""
    return r._act_home_popup()


if __name__ == "__main__":
    unittest.main()
