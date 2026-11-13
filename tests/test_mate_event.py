"""伙伴事件（朏朏池）选择规则测试（对应 src/game/mate_event.py）。"""
from __future__ import annotations

import unittest

from src.game.mate_event import MATE_PRIORITY, pick_mate_event


class FakeItem:
    def __init__(self, text, cx, cy):
        self.text = text
        self.rect = [cx - 100, cy - 14, cx + 100, cy + 14]


def make_screen(order):
    """按给定行序（1/2/3 = 快睡午觉/我来帮你/讨价还价）构造三行选项。"""
    titles = {1: "快睡午觉", 2: "我来帮你", 3: "讨价还价"}
    descs = {1: "需要战斗的概率降低（效果唯一）",
             2: "商店道具价格降低10%（效果唯一）",
             3: "你的伙伴技能触发概率+8%"}
    items = []
    for row, no in enumerate(order):
        cy_title, cy_desc = (335, 530, 715)[row] - 25, (335, 530, 715)[row] + 15
        items.append(FakeItem(titles[no], 957, cy_title))
        items.append(FakeItem(descs[no], 1100, cy_desc))
    return items


class TestMateEvent(unittest.TestCase):
    def test_priority_132(self):
        self.assertEqual(MATE_PRIORITY, (1, 3, 2))

    def test_screen_order_123_pick_kuaisui(self):
        """屏幕顺序 我来帮你/讨价还价/快睡午觉 → 优先级命中快睡午觉（第 3 行）。"""
        pt, reason = pick_mate_event(make_screen((2, 3, 1)))
        self.assertEqual(pt, (1200, 715))
        self.assertIn("事件 1", reason)

    def test_screen_order_231_pick_wolai(self):
        # 行序：讨价还价/快睡午觉/我来帮你 → 优先级 1(快睡午觉) 在第二行
        pt, _ = pick_mate_event(make_screen((3, 1, 2)))
        self.assertEqual(pt, (1200, 530))

    def test_titles_vary_but_desc_stable(self):
        """标题是会变的文案——换标题后仍要靠描述正确判别（用户 2026-09-17 明确）。"""
        items = []
        descs = {1: "需要战斗的概率降低（效果唯一）",
                 2: "商店道具价格降低10%（效果唯一）",
                 3: "你的伙伴技能触发概率+8%"}
        for row, no in enumerate((2, 3, 1)):
            cy_title, cy_desc = (335, 530, 715)[row] - 25, (335, 530, 715)[row] + 15
            items.append(FakeItem(f"换了的新标题{row}", 957, cy_title))  # 标题随便变
            items.append(FakeItem(descs[no], 1100, cy_desc))
        pt, reason = pick_mate_event(items)
        self.assertEqual(pt, (1200, 715))   # 快睡午觉(描述1) 在第 3 行
        self.assertIn("事件 1", reason)

    def test_unknown_options_return_none(self):
        items = [FakeItem("未知甲", 957, 310), FakeItem("未知乙", 957, 505),
                 FakeItem("未知丙", 957, 700)]
        pt, reason = pick_mate_event(items)
        self.assertIsNone(pt)
        self.assertIn("人工确认", reason)

    def test_empty(self):
        pt, _ = pick_mate_event([])
        self.assertIsNone(pt)


if __name__ == "__main__":
    unittest.main()
