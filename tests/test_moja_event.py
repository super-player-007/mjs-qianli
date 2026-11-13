"""墨家巨子制造页规则测试（对应 src/game/moja_event.py）。"""
from __future__ import annotations

import unittest

from src.game.moja_event import pick_moja_event


class FakeItem:
    def __init__(self, text, cx, cy):
        self.text = text
        self.rect = [cx - 100, cy - 14, cx + 100, cy + 14]


def make_screen():
    """2026-09-17 实测墨家巨子页：三行制造选项。"""
    items = []
    rows = [("墨子的制造一", "体力上限-3，获得技能：闭月之姿", 335),
            ("墨子的制造二", "初始手牌-2，获得技能：斧破重围", 530),
            ("墨子的制造三", "战法增伤-1，获得技能：截粮焚辎", 715)]
    for title, desc, cy in rows:
        items.append(FakeItem(title, 940, cy - 25))
        items.append(FakeItem(desc, 1054, cy + 15))
    items.append(FakeItem("请选择一种制造", 960, 942))
    return items


class TestMojaEvent(unittest.TestCase):
    def test_fixed_first_row(self):
        pt, reason = pick_moja_event(make_screen())
        self.assertEqual(pt, (1200, 335))   # 固定选第一个
        self.assertIn("固定选第一个", reason)

    def test_no_zhizao_anchor_rejects(self):
        """非制造页（如蛊惑/赠礼页）必须拒绝——交给上一级池处理。"""
        items = [FakeItem("十常侍的蛊惑一", 957, 310),
                 FakeItem("无法打出桃", 1100, 350),
                 FakeItem("请选择一项蛊惑", 960, 942)]
        pt, reason = pick_moja_event(items)
        self.assertIsNone(pt)
        self.assertIn("不是墨家巨子页", reason)

    def test_empty(self):
        pt, _ = pick_moja_event([])
        self.assertIsNone(pt)


if __name__ == "__main__":
    unittest.main()
