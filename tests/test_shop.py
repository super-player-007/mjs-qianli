"""商店（巴清小铺子）购买规则测试（对应 src/game/shop.py）。"""
from __future__ import annotations

import unittest

from src.game.shop import WANTED_ITEMS, parse_shop, pick_shop_purchase


class FakeItem:
    def __init__(self, text, cx, cy):
        self.text = text
        self.rect = [cx - 60, cy - 14, cx + 60, cy + 14]


def make_shop_screen():
    """2026-09-17 第 6 层实测：牙门旗 5.0折 15 / 行囊 30 / 出手法 80。"""
    return [
        FakeItem("小铺子", 553, 129),
        FakeItem("15", 1724, 132),              # 右上角余额（也是纯数字，应被当价格解析失败→无名字丢弃）
        FakeItem("信物专区", 1373, 194),
        FakeItem("牙门旗", 1048, 272),
        FakeItem("行囊", 1366, 271),
        FakeItem("出手法", 1687, 271),
        FakeItem("5.0折", 977, 310),
        FakeItem("15", 1066, 525),
        FakeItem("30", 1385, 525),
        FakeItem("80", 1704, 525),
        FakeItem("武将牌专区", 1389, 624),
        FakeItem("刘表", 1065, 772),
        FakeItem("99", 1066, 900),              # 武将牌专区价格（y≥600 → wupai）
    ]


class TestParseShop(unittest.TestCase):
    def test_parse_real_layout(self):
        goods = parse_shop(make_shop_screen())
        by_name = {g["name"]: g for g in goods}
        # 三个信物商品都要解析出来，名字不能串列
        self.assertIn("牙门旗", by_name)
        self.assertIn("行囊", by_name)
        self.assertIn("出手法", by_name)
        self.assertEqual(by_name["牙门旗"]["price"], 15)
        self.assertEqual(by_name["行囊"]["price"], 30)
        self.assertEqual(by_name["出手法"]["price"], 80)
        # 「信物专区」标题不能被当商品名
        self.assertNotIn("信物专区", by_name)
        # 按价格降序
        prices = [g["price"] for g in goods]
        self.assertEqual(prices, sorted(prices, reverse=True))

    def test_click_points_in_cards(self):
        for g in parse_shop(make_shop_screen()):
            if g["zone"] == "xinwu":
                self.assertTrue(380 <= g["click"][1] <= 520, g)
            else:   # 武将牌专区卡片在下方
                self.assertTrue(760 <= g["click"][1] <= 900, g)


class TestPickPurchase(unittest.TestCase):
    def setUp(self):
        # 机制测试用旧夹具商品清单（默认清单 2026-10-12 已换新 20 项，
        # 夹具货架还是旧商品——机制测试与默认值解耦）
        from src.game import shop
        self._orig_w = list(shop._shop_wanted)
        shop.apply_shop_wanted(["牙门旗", "行囊", "出手法"])

    def tearDown(self):
        from src.game import shop
        shop._shop_wanted = self._orig_w

    def test_buy_only_affordable_wanted(self):
        got, reason = pick_shop_purchase(make_shop_screen(), coins=15)
        self.assertIsNotNone(got)
        self.assertEqual(got["name"], "牙门旗")
        self.assertIn("15", reason)

    def test_nothing_affordable_exit(self):
        got, reason = pick_shop_purchase(make_shop_screen(), coins=10)
        self.assertIsNone(got)
        self.assertIn("退出", reason)

    def test_coins_equal_price_counts_as_affordable(self):
        """用户 2026-09-17 明确：『大于』改『大于等于』。"""
        got, _ = pick_shop_purchase(make_shop_screen(), coins=15)
        self.assertEqual(got["name"], "牙门旗")

    def test_unwanted_xinwu_but_wupai_bought(self):
        """2026-10-12 新规则：信物专区清单外不买，但武将牌专区全都要
        （999-99=900 ≥ 保留线 150 → 买刘表）。"""
        got, reason = pick_shop_purchase(make_shop_screen(), coins=999,
                                         wanted=("不存在的东西",))
        self.assertIsNotNone(got)
        self.assertEqual(got["name"], "刘表")
        self.assertIn("武将牌专区", reason)

    def test_unwanted_and_reserve_blocks_exit(self):
        """清单外 + 武将牌专区跌破保留线 → 退出。"""
        got, reason = pick_shop_purchase(make_shop_screen(), coins=100,
                                         wanted=("不存在的东西",))
        self.assertIsNone(got)
        self.assertIn("退出商店", reason)

    def test_empty_shop(self):
        got, _ = pick_shop_purchase([], coins=100)
        self.assertIsNone(got)


if __name__ == "__main__":
    unittest.main()


class TestConfigurableWanted(unittest.TestCase):
    """GUI 商店商品名单（2026-10-09 用户需求）：运行时清单可整体重建。"""

    def setUp(self):
        from src.game import shop
        self._orig = list(shop._shop_wanted)

    def tearDown(self):
        from src.game import shop
        shop._shop_wanted = self._orig

    def test_apply_custom_list_drives_purchase(self):
        """应用自定义清单 → 只买清单内的商品。"""
        from src.game import shop
        applied = shop.apply_shop_wanted(["测试丹药", "牙门旗"])
        self.assertEqual(applied, ["测试丹药", "牙门旗"])
        goods, why = pick_shop_purchase(make_shop_screen(), coins=100)
        # 货架：牙门旗 15 / 行囊 30 / 出手法 80；自定义清单只有牙门旗命中
        self.assertEqual(goods["name"], "牙门旗")
        self.assertIn("牙门旗", why)

    def test_custom_list_excludes_default_items(self):
        """清单不含的商品（行囊在默认清单里）→ 不再购买。"""
        from src.game import shop
        shop.apply_shop_wanted(["测试丹药"])
        goods, why = pick_shop_purchase(make_shop_screen(), coins=100)
        self.assertIsNone(goods)                # 牙门旗/行囊/出手法都不在清单
        self.assertIn("退出商店", why)

    def test_empty_falls_back_to_builtin(self):
        """空清单 → 回落内建默认（不会变成什么都不买）。"""
        from src.game import shop
        applied = shop.apply_shop_wanted([])
        self.assertEqual(applied, list(WANTED_ITEMS))
        self.assertEqual(shop.shop_wanted(), WANTED_ITEMS)

    def test_runner_default_uses_runtime_list(self):
        """runner 调用（不传 wanted）→ 走运行时清单而非内建常量。"""
        from src.game import shop
        shop.apply_shop_wanted(["测试丹药"])
        screen = [FakeItem("测试丹药", 1048, 272), FakeItem("99", 1066, 525)]
        goods, _ = pick_shop_purchase(screen, coins=100)
        self.assertEqual(goods["name"], "测试丹药")


class TestZoneReserve(unittest.TestCase):
    """分专区规则（2026-10-12）：保留线 + 信物不受限 + 武将牌全买。"""

    def setUp(self):
        from src.game import shop
        self._orig_w = list(shop._shop_wanted)
        self._orig_r = shop._shop_reserve
        shop.apply_shop_wanted(["牙门旗", "行囊", "出手法"])

    def tearDown(self):
        from src.game import shop
        shop._shop_wanted = self._orig_w
        shop._shop_reserve = self._orig_r

    def test_xinwu_ignores_reserve(self):
        """信物专区：不受保留线约束——coins 恰好够就买（买完可低于保留线）。"""
        from src.game import shop
        shop.apply_shop_reserve(150)
        goods, why = pick_shop_purchase(make_shop_screen(), coins=15)
        # 牙门旗 15 是清单内唯一买得起的（15 ≥ 15），买后余额 0 < 150 也买
        self.assertEqual(goods["name"], "牙门旗")
        self.assertIn("不受保留线约束", why)

    def test_xinwu_preferred_over_wupai(self):
        """信物专区想要商品优先于武将牌专区。"""
        from src.game import shop
        shop.apply_shop_reserve(150)
        goods, why = pick_shop_purchase(make_shop_screen(), coins=300)
        # 信物专区有想要的（出手法 80 最贵）→ 先买它，不碰武将牌专区
        self.assertEqual(goods["name"], "出手法")
        self.assertIn("信物专区", why)

    def test_wupai_buys_all_under_reserve(self):
        """信物专区没想要的 → 武将牌专区全都要（清单外也买），保住保留线。"""
        from src.game import shop
        shop.apply_shop_wanted(["测试不存在商品"])
        shop.apply_shop_reserve(150)
        goods, why = pick_shop_purchase(make_shop_screen(), coins=300)
        # 刘表 99：300-99=201 ≥ 150 → 买（清单外的也买）
        self.assertEqual(goods["name"], "刘表")
        self.assertIn("武将牌专区", why)

    def test_wupai_blocked_by_reserve(self):
        """武将牌专区买后余额 < 保留线 → 不买，退出。"""
        from src.game import shop
        shop.apply_shop_wanted(["测试不存在商品"])
        shop.apply_shop_reserve(150)
        goods, why = pick_shop_purchase(make_shop_screen(), coins=200)
        # 200-99=101 < 150 → 不买
        self.assertIsNone(goods)
        self.assertIn("保留线", why)

    def test_reserve_zero_wupai_free(self):
        """保留线 0 → 武将牌专区只要买得起就买。"""
        from src.game import shop
        shop.apply_shop_wanted(["测试不存在商品"])
        shop.apply_shop_reserve(0)
        goods, _ = pick_shop_purchase(make_shop_screen(), coins=99)
        self.assertEqual(goods["name"], "刘表")

    def test_zone_classification(self):
        """parse_shop 按 y 分界标注专区：信物价格 y≈525、武将牌 y≈900。"""
        zones = {g["name"]: g["zone"] for g in parse_shop(make_shop_screen())}
        self.assertEqual(zones["牙门旗"], "xinwu")
        self.assertEqual(zones["行囊"], "xinwu")
        self.assertEqual(zones["出手法"], "xinwu")
        self.assertEqual(zones["刘表"], "wupai")


if __name__ == "__main__":
    unittest.main()
