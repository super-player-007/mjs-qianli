"""地图节点识别测试（对应 src/game/node_icon.py，夹具为真实截图）。"""
from __future__ import annotations

import unittest

from src.game.node_icon import (
    analyze_nodes,
    classify_patch,
    icon_patch,
    keep_current_layer,
    load_node_templates,
    select_node,
    template_kind,
)

from tests._base import TPL_DIR, load_fixture


class TestKeepCurrentLayer(unittest.TestCase):
    """列聚类选层规则（纯合成数据，不依赖图片）。"""

    def test_layer2_real_case(self):
        # 2026-09-16 第 2 层实测：精灵(1个) / 已通关(1个) / 当前层(3个)
        centers = [(398, 433, 42), (668, 737, 53),
                   (1082, 397, 44), (1081, 567, 51), (1082, 736, 44)]
        keep, drop = keep_current_layer(centers)
        self.assertEqual(len(keep), 3)
        self.assertTrue(all(1000 < x < 1200 for x, _, _ in keep))
        self.assertEqual(len(drop), 2)
        # 结果按 y 升序
        ys = [y for _, y, _ in keep]
        self.assertEqual(ys, sorted(ys))

    def test_single_column(self):
        keep, drop = keep_current_layer([(667, 397, 50), (667, 567, 49)])
        self.assertEqual(len(keep), 2)
        self.assertEqual(drop, [])

    def test_tie_break_rightmost(self):
        # 两列都只有 1 个节点 → 取更靠右的列
        keep, _ = keep_current_layer([(500, 400, 45), (900, 400, 45)])
        self.assertEqual(keep[0][0], 900)

    def test_empty(self):
        self.assertEqual(keep_current_layer([]), ([], []))


class TestAnalyzeNodesOnFixtures(unittest.TestCase):
    """真实截图回归：这是「只认当前层 + 类型判定」的主防线。"""

    @classmethod
    def setUpClass(cls):
        cls.templates = load_node_templates(TPL_DIR)
        assert "battle" in cls.templates, "缺少战斗图标模板 node_battle.png"
        assert "shop" in cls.templates, "缺少商店图标模板 node_shop.png"
        assert "rest" in cls.templates, "缺少休息本体模板 node_rest.png"
        assert "hero_shier" in cls.templates, "缺少武将事件模板 node_hero_shier.png"
        assert "hero_moja" in cls.templates, "缺少武将事件模板 node_hero_moja.png"
        assert "mate_dog" in cls.templates, "缺少伙伴事件模板 node_mate_dog.png"
        assert "event" in cls.templates, "缺少事件本体模板 node_event.png"
        assert "hero_wolong" in cls.templates, "缺少武将事件模板 node_hero_wolong.png"
        assert "hero_fengfeng" in cls.templates, "缺少武将事件模板 node_hero_fengfeng.png"
        assert "mate_feifei" in cls.templates, "缺少伙伴事件模板 node_mate_feifei.png"

    def test_template_kind_prefix(self):
        """事件模板按第一个下划线前缀归类到类型。"""
        self.assertEqual(template_kind("hero_shier"), "hero")
        self.assertEqual(template_kind("mate_dog"), "mate")
        self.assertEqual(template_kind("battle"), "battle")

    def test_layer1_three_battle(self):
        nodes = analyze_nodes(load_fixture("map_layer1.png"),
                              templates=self.templates)
        self.assertEqual(len(nodes), 3)
        for n in nodes:
            self.assertEqual(n.kind, "battle", str(n))
            self.assertGreaterEqual(n.score, 0.70)
            self.assertAlmostEqual(n.cx, 667, delta=8)
        ys = [n.cy for n in nodes]
        self.assertEqual(ys, sorted(ys))
        # 间距 ≈169.5
        self.assertAlmostEqual(ys[1] - ys[0], 169.5, delta=6)
        self.assertAlmostEqual(ys[2] - ys[1], 169.5, delta=6)

    def test_layer2_filters_interference(self):
        dropped: list = []
        nodes = analyze_nodes(load_fixture("map_layer2.png"),
                              templates=self.templates,
                              dropped_out=dropped)
        # 当前层 3 个战斗节点 @x≈1082
        self.assertEqual(len(nodes), 3)
        for n in nodes:
            self.assertEqual(n.kind, "battle", str(n))
            self.assertAlmostEqual(n.cx, 1082, delta=8)
        # 干扰圆必须全部剔掉；param2=34 后云雾假圆变多，只增不减
        self.assertGreaterEqual(len(dropped), 2)
        dropped_xy = [(x, y) for x, y, _ in dropped]
        def has_near(x0, y0):
            return any(abs(x - x0) <= 3 and abs(y - y0) <= 3 for x, y in dropped_xy)

        self.assertTrue(has_near(398, 443), f"精灵未剔除: {dropped_xy}")   # 云中君精灵
        self.assertTrue(has_near(668, 737), f"已通关未剔除: {dropped_xy}")  # 已通关节点
        # 剔除的都不在当前层那一列（x≈1082）
        for x, _, _ in dropped:
            self.assertGreater(abs(x - 1082), 60)

    def test_layer3_mixed_types(self):
        """第 3 层（2026-09-17 实测）：商店 / 休息(篝火) / 商店。

        本层确立两件事：param2 必须降到 34 才能检出篝火圆；
        休息是「本体节点」，靠圆内窗口分类而非圆下图标。
        """
        dropped: list = []
        nodes = analyze_nodes(load_fixture("map_layer3.png"),
                              templates=self.templates,
                              dropped_out=dropped)
        self.assertEqual([n.kind for n in nodes], ["shop", "rest", "shop"])
        for n in nodes:
            self.assertGreaterEqual(n.score, 0.70)
            self.assertAlmostEqual(n.cx, 1100, delta=10)
        ys = [n.cy for n in nodes]
        self.assertAlmostEqual(ys[0], 395, delta=6)
        self.assertAlmostEqual(ys[1], 565, delta=6)
        self.assertAlmostEqual(ys[2], 731, delta=6)
        # param2=34 引入更多假圆，但列聚类必须全部剔掉
        self.assertGreaterEqual(len(dropped), 5)
        # 已通关节点 (691,737) 绝不能混进当前层
        self.assertNotIn((691, 737), [(n.cx, n.cy) for n in nodes])

    def test_layer4_hero_mate(self):
        """第 4 层（2026-09-17 实测）：武将(十二阉人) / 伙伴(小狗) / 武将(墨家巨子)。

        三个都是本体节点（圆下无图标）；武将的两个事件画面完全不同
        （互配仅 0.35），靠「按事件存模板、按前缀归类」打通。
        """
        nodes = analyze_nodes(load_fixture("map_layer4.png"),
                              templates=self.templates)
        self.assertEqual([n.kind for n in nodes], ["hero", "mate", "hero"])
        # 事件级信息也要带上（select_node 的优先级依赖它）
        self.assertEqual([n.event for n in nodes],
                         ["hero_shier", "mate_dog", "hero_moja"])
        for n in nodes:
            self.assertGreaterEqual(n.score, 0.85)
            self.assertAlmostEqual(n.cx, 1104, delta=10)
        # 两个武将节点用的是不同事件模板——各自的分数都来自自己的模板
        self.assertAlmostEqual(nodes[0].cy, 394, delta=6)
        self.assertAlmostEqual(nodes[1].cy, 568, delta=6)
        self.assertAlmostEqual(nodes[2].cy, 737, delta=6)

    def test_layer6_event_shop(self):
        """第 6 层（2026-09-17 实测）：事件(钱袋) / 商店 / 事件(钱袋)。

        事件节点也是本体节点（圆内即钱袋）——至此 6 种类型模板全部集齐。
        """
        nodes = analyze_nodes(load_fixture("map_layer6.png"),
                              templates=self.templates)
        self.assertEqual([n.kind for n in nodes], ["event", "shop", "event"])
        for n in nodes:
            self.assertGreaterEqual(n.score, 0.90)
        self.assertAlmostEqual(nodes[1].cy, 568, delta=6)

    def test_layer5_new_events(self):
        """第 5 层重visit（2026-09-17 实测）：伙伴(偶遇朏朏)/武将(卧龙出山)/武将(疯疯老道)。"""
        nodes = analyze_nodes(load_fixture("map_layer5.png"),
                              templates=self.templates)
        self.assertEqual([n.kind for n in nodes], ["mate", "hero", "hero"])
        self.assertEqual([n.event for n in nodes],
                         ["mate_feifei", "hero_wolong", "hero_fengfeng"])
        for n in nodes:
            self.assertGreaterEqual(n.score, 0.90)

    def test_unknown_type_below_threshold(self):
        """非战斗图标分数必须显著低于阈值，保证不会误判成战斗。"""
        img = load_fixture("map_layer2.png")
        # 已通关节点 (668,737) 的图标窗口是印章，不应判成 battle
        scores = classify_patch(icon_patch(img, 668, 737), self.templates)
        self.assertTrue(scores)
        self.assertLess(scores[0][1], 0.70)


class TestSelectNode(unittest.TestCase):
    """节点选择优先级（用户 2026-09-17：休息 > 商店）。"""

    @staticmethod
    def _node(kind, idx):
        from src.game.node_icon import NODE_LABELS, NodeInfo
        n = NodeInfo(cx=1100, cy=400 + 170 * idx, r=45, index=idx + 1)
        n.kind = kind
        n.label = NODE_LABELS.get(kind, "未知")
        return n

    def test_rest_beats_shop(self):
        # 第 3 层实测：商店/休息/商店 → 选休息（中间那个）
        nodes = [self._node("shop", 0), self._node("rest", 1), self._node("shop", 2)]
        hit, reason = select_node(nodes)
        self.assertIs(hit, nodes[1])
        self.assertIn("休息", reason)

    def test_all_battle_pick_last(self):
        # 3 节点全战斗 → 固定选最后一个（第三个）
        nodes = [self._node("battle", i) for i in range(3)]
        hit, _ = select_node(nodes)
        self.assertIs(hit, nodes[2])

    def test_unknown_types_pick_last(self):
        nodes = [self._node("hero", 0), self._node("mate", 1)]
        hit, _ = select_node(nodes)
        self.assertIs(hit, nodes[1])

    def test_event_level_priority(self):
        """优先级是事件级的：同为武将，十二阉人(hero_shier) >> 墨家巨子(hero_moja)。"""
        nodes = [self._node("hero", 0), self._node("rest", 1), self._node("hero", 2)]
        nodes[0].event = "hero_moja"    # 墨家巨子，优先级低于 rest
        nodes[2].event = "hero_shier"   # 十二阉人，最高优先
        hit, reason = select_node(nodes)
        self.assertIs(hit, nodes[2])
        self.assertIn("hero_shier", reason)

    def test_type_fallback_when_no_event(self):
        """优先级条目为类型 key 时按 kind 匹配（夹具节点常无 event）。"""
        nodes = [self._node("shop", 0), self._node("rest", 1), self._node("shop", 2)]
        hit, _ = select_node(nodes)
        self.assertIs(hit, nodes[1])

    def test_event_type_lowest_priority(self):
        """事件节点排最末：商店在场的场合优先商店。"""
        nodes = [self._node("event", 0), self._node("shop", 1), self._node("event", 2)]
        hit, _ = select_node(nodes)
        self.assertIs(hit, nodes[1])
        # 只剩事件 → 也能选（优先级覆盖所有已知类型）
        nodes2 = [self._node("event", 0), self._node("event", 1)]
        hit2, _ = select_node(nodes2)
        self.assertIs(hit2, nodes2[0])

    def test_empty(self):
        hit, _ = select_node([])
        self.assertIsNone(hit)


if __name__ == "__main__":
    unittest.main()
