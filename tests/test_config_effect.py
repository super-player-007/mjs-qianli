"""GUI 配置生效链路测试（配置 → 游戏逻辑真实生效）。

背景（用户 2026-09-18 要求）：改完 GUI 配置后必须保证运行时生效——
① 三张赠礼武将名单能影响赠礼决策 ② 节点优先级能影响选节点。
"""
from __future__ import annotations

import unittest
from unittest.mock import patch

from src.game import gift
from src.game.node_icon import NodeInfo, select_node
from src.gui import config_store


class TestConfigTakesEffect(unittest.TestCase):
    def setUp(self):
        # 备份真实名单，测试后恢复（防污染）
        self._orig = dict(gift.HERO_CATEGORIES)

    def tearDown(self):
        gift.HERO_CATEGORIES.clear()
        gift.HERO_CATEGORIES.update(self._orig)

    def test_custom_categories_drive_gift_decision(self):
        """GUI 名单里的新武将 → 赠礼一级决策立刻认得。"""
        config_store.apply_gift_categories({
            "信物": ["测试信物将"],
            "驰援": ["测试驰援将"],
            "资助": ["测试资助将"],
        })
        heroes = ["测试资助将", "无名甲", "无名乙"]
        idx, reason = gift.pick_gift_hero(heroes)
        self.assertEqual(idx, 0)                    # 命中资助 → 选第 0 个
        self.assertIn("资助", reason)

    def test_custom_category_missing_falls_to_middle(self):
        """三人都不是名单内 → 固定选中间（既定规则不受自定义影响）。"""
        config_store.apply_gift_categories({
            "信物": ["测试信物将"], "驰援": [], "资助": [],
        })
        idx, _ = gift.pick_gift_hero(["甲", "乙", "丙"])
        self.assertEqual(idx, 1)

    def test_node_priority_override(self):
        """GUI 自定义优先级 → select_node 按新顺序选（覆盖默认表）。"""
        nodes = [NodeInfo(cx=100, cy=100, r=40, index=1, kind="event",
                          label="事件", score=0.99),
                 NodeInfo(cx=200, cy=100, r=40, index=2, kind="rest",
                          label="休息", score=0.99)]
        # 默认表：event 在表内、rest 也在（rest 靠前）→ 默认会选 rest
        default_hit, _ = select_node(nodes)
        self.assertIs(default_hit, nodes[1])
        # 自定义：event 优先 → 选 event
        hit, reason = select_node(nodes, priority=["event", "rest"])
        self.assertIs(hit, nodes[0])
        self.assertIn("事件", reason)   # select_node 返回中文标签

    def test_gui_default_config_priority_matches_code(self):
        """GUI 默认优先级 = 代码 NODE_SELECTION_PRIORITY（防两处漂移）。"""
        from src.game.node_icon import NODE_SELECTION_PRIORITY
        cfg = config_store.load_config()
        self.assertEqual(tuple(cfg["priority"]), NODE_SELECTION_PRIORITY)


if __name__ == "__main__":
    unittest.main()


class TestDuplicateCategories(unittest.TestCase):
    """同名武将跨类别重复（用户 2026-09-19 定策：允许重复，信物>驰援>资助 先到先得）。"""

    def setUp(self):
        from src.game import gift
        self._orig = dict(gift.HERO_CATEGORIES)

    def tearDown(self):
        from src.game import gift
        gift.HERO_CATEGORIES.clear()
        gift.HERO_CATEGORIES.update(self._orig)

    def test_find_duplicates(self):
        dups = config_store.find_duplicates({
            "信物": ["甲", "乙"],
            "驰援": ["乙", "丙"],
            "资助": ["丙", "丁"],
        })
        self.assertEqual(dups, {"乙": ["信物", "驰援"], "丙": ["驰援", "资助"]})

    def test_first_category_wins(self):
        from src.game import gift
        resolved = config_store.apply_gift_categories({
            "信物": ["重复将"],
            "驰援": ["重复将"],
            "资助": ["重复将"],
        })
        self.assertEqual(gift.HERO_CATEGORIES["重复将"], gift.CATEGORY_SIGNAL)
        self.assertEqual(len(resolved), 2)   # 驰援/资助 两条被忽略的记录

    def test_order_independent_of_dict(self):
        """传入字典顺序打乱，裁决仍按 信物>驰援>资助。"""
        from src.game import gift
        config_store.apply_gift_categories({
            "资助": ["乱序将"],
            "驰援": ["乱序将"],
        })
        self.assertEqual(gift.HERO_CATEGORIES["乱序将"], gift.CATEGORY_RELAY)

    def test_no_duplicates_no_records(self):
        resolved = config_store.apply_gift_categories({
            "信物": ["甲"], "驰援": ["乙"], "资助": ["丙"],
        })
        self.assertEqual(resolved, [])


class TestZhongliSpellings(unittest.TestCase):
    """钟离眜三种写法统一（2026-09-20 赠礼漏检事故）。

    OCR 会把「钟离眜」读成 钟离眜/钟离眛/钟离昧 任一；GUI 重建分类表时
    三个写法必须齐平（旧代码漏了「昧」→ 赠礼一级 0 类别 → 疑似漏检）。
    """

    def setUp(self):
        from src.game import gift
        self._orig = dict(gift.HERO_CATEGORIES)

    def tearDown(self):
        from src.game import gift
        gift.HERO_CATEGORIES.clear()
        gift.HERO_CATEGORIES.update(self._orig)

    def test_all_three_spellings_after_apply(self):
        from src.game import gift
        config_store.apply_gift_categories({
            "信物": ["钟离眜"], "驰援": [], "资助": [],
        })
        for sp in ("钟离眜", "钟离眛", "钟离昧"):
            self.assertEqual(gift.classify_hero(sp), gift.CATEGORY_SIGNAL, sp)

    def test_follows_user_category(self):
        """写法统一跟随名单里实际配置的类别（不写死信物）。"""
        from src.game import gift
        config_store.apply_gift_categories({
            "信物": [], "驰援": ["钟离眛"], "资助": [],
        })
        for sp in ("钟离眜", "钟离眛", "钟离昧"):
            self.assertEqual(gift.classify_hero(sp), gift.CATEGORY_RELAY, sp)

    def test_removed_hero_no_category(self):
        """名单里彻底移除钟离眜 → 三个写法都无类别（不残留）。"""
        from src.game import gift
        config_store.apply_gift_categories({
            "信物": ["关羽"], "驰援": [], "资助": [],
        })
        for sp in ("钟离眜", "钟离眛", "钟离昧"):
            self.assertIsNone(gift.classify_hero(sp), sp)


class TestShopWantedTakesEffect(unittest.TestCase):
    """GUI 商店商品名单 → 商店购买决策真实生效（2026-10-09 需求）。"""

    def setUp(self):
        from src.game import shop
        self._orig = list(shop._shop_wanted)

    def tearDown(self):
        from src.game import shop
        shop._shop_wanted = self._orig

    def test_gui_shop_wanted_drives_purchase(self):
        """GUI 名单应用 → pick_shop_purchase（runner 的调用方式）立刻认得。"""
        config_store.apply_shop_wanted(["测试新商品"])
        from tests.test_shop import make_shop_screen
        goods, why = pick_shop(make_shop_screen(), coins=100)
        self.assertIsNone(goods)                # 默认商品都不在新清单
        self.assertIn("退出商店", why)


def pick_shop(items, coins):
    """模拟 runner 的调用方式（不传 wanted → 用运行时清单）。"""
    from src.game.shop import pick_shop_purchase
    return pick_shop_purchase(items, coins=coins)


if __name__ == "__main__":
    unittest.main()
