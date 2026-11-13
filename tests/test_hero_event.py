"""武将节点事件选择规则测试（对应 src/game/hero_event.py）。"""
from __future__ import annotations

import unittest

from src.game.hero_event import (EVENT_PRIORITY, HERO_EVENTS, OPTION_ROWS,
                                 detect_event_rows, pick_hero_event)


class FakeItem:
    """模拟 OCR 条目（rect=[x1,y1,x2,y2], text）。"""

    def __init__(self, text, cx, cy):
        self.text = text
        self.rect = [cx - 100, cy - 14, cx + 100, cy + 14]


def make_screen_1_3_6():
    """2026-09-17 第 4 层实测：十常侍的蛊惑一/二/三 = 事件 1/3/6。"""
    items = []
    titles = [(957, 295, "十常侍的蛊惑一"), (957, 485, "十常侍的蛊惑二"),
              (957, 675, "十常侍的蛊惑三")]
    descs = [(1205, 341, "接下来的4场战斗中，你无法打出桃，之后你的体力上限翻"),
             (1205, 531, "接下来的5场战斗中，你无法打出装备牌，之后增强你的牌"),
             (1205, 722, "接下来的3场战斗中，你获得的战法牌全部转化为天雷，之")]
    for cx, cy, t in titles + descs:
        items.append(FakeItem(t, cx, cy))
    return items


class TestPriorityTable(unittest.TestCase):
    def test_priority_order(self):
        self.assertEqual(EVENT_PRIORITY, (1, 2, 4, 3, 5, 6))

    def test_six_events_unique_keys(self):
        """任一判别关键词只属于一个事件——防止一行文本命中两个事件。"""
        seen = {}
        for ev in HERO_EVENTS:
            for k in ev["keys"]:
                self.assertNotIn(k, seen, f"关键词 {k} 重复")
                seen[k] = ev["no"]


class TestPickHeroEvent(unittest.TestCase):
    def test_screen_1_3_6_pick_event1(self):
        pt, reason = pick_hero_event(make_screen_1_3_6())
        self.assertEqual(pt, (1200, 335))
        self.assertIn("事件 1", reason)

    def test_screen_2_5_6_pick_event2(self):
        items = [
            FakeItem("蛊惑甲", 957, 295),
            FakeItem("接下来的3场战斗中，你的速度降为1，之后你的速度+10", 1205, 341),
            FakeItem("蛊惑乙", 957, 485),
            FakeItem("接下来的4场战斗中，你打出行动牌后，随机弃置2张牌", 1205, 531),
            FakeItem("蛊惑丙", 957, 675),
            FakeItem("接下来的3场战斗中，你获得的战法牌全部转化为天雷", 1205, 722),
        ]
        pt, reason = pick_hero_event(items)
        self.assertEqual(pt, (1200, 335))   # 事件2 优先于 5/6
        self.assertIn("事件 2", reason)

    def test_screen_3_5_6_pick_event3(self):
        """只剩 3/5/6 时，优先级 3>5>6 → 选事件 3（中行）。"""
        items = [
            FakeItem("甲", 957, 295),
            FakeItem("接下来的5场战斗中，你无法打出装备牌", 1205, 341),
            FakeItem("乙", 957, 485),
            FakeItem("接下来的4场战斗中，你打出行动牌后，随机弃置2张牌", 1205, 531),
            FakeItem("丙", 957, 675),
            FakeItem("接下来的3场战斗中，战法牌全部转化为天雷", 1205, 722),
        ]
        pt, _ = pick_hero_event(items)
        self.assertEqual(pt, (1200, 335))   # 事件3 在第一行，且 3>5>6

    def test_all_unknown_returns_none(self):
        items = [FakeItem("未知事件甲", 957, 295),
                 FakeItem("未知事件乙", 957, 485),
                 FakeItem("未知事件丙", 957, 675)]
        pt, reason = pick_hero_event(items)
        self.assertIsNone(pt)
        self.assertIn("人工确认", reason)

    def test_empty(self):
        pt, _ = pick_hero_event([])
        self.assertIsNone(pt)

    def test_row_grouping_wrapped_text(self):
        """描述换行成两条 OCR 也应归到同一行。"""
        items = make_screen_1_3_6() + [
            FakeItem("倍。", 867, 371),      # 第 1 行描述的折行
            FakeItem("堆中的所有装备牌。", 962, 561),
        ]
        rows = detect_event_rows(items)
        self.assertEqual(len(rows), 3)
        self.assertEqual([r for r, _ in rows], [0, 1, 2])


if __name__ == "__main__":
    unittest.main()
