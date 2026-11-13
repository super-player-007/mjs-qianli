"""最后一层单节点兜底测试（2026-09-20 无尽 35 层事故）。

场景：当前层只剩 1 个战斗节点，右侧两个装饰假圆聚成一列 2 个，
列聚类"按个数优先"反超 → 真节点被剔、只剩装饰列全 unknown。
recover_classified_node 应从全部霍夫圆里找回战斗节点（取最右）。
"""
from __future__ import annotations

import unittest
from pathlib import Path

from src.game.node_icon import (analyze_nodes, load_node_templates,
                                recover_classified_node, select_node)
from src.vision.annotate import read_image

FIXTURE = Path("tests/fixtures/map_last_layer.png")


class TestRecoverNode(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tpls = load_node_templates(Path("assets/templates/run_map"))
        cls.img = read_image(FIXTURE)

    def test_analyze_misses_real_node(self):
        """回归基线：默认管线在该图上只返回装饰列（全 unknown）。"""
        nodes = analyze_nodes(self.img, templates=self.tpls)
        self.assertTrue(nodes)
        self.assertTrue(all(n.kind == "unknown" for n in nodes))

    def test_recover_finds_battle_node(self):
        rec = recover_classified_node(self.img, templates=self.tpls)
        self.assertIsNotNone(rec)
        self.assertEqual(rec.kind, "battle")
        self.assertGreaterEqual(rec.score, 0.70)
        self.assertAlmostEqual(rec.cx, 1104, delta=8)   # 真节点位置
        self.assertAlmostEqual(rec.cy, 568, delta=8)

    def test_recover_takes_rightmost(self):
        """地图向右延伸：多个有类型圆时取最右（已通关在左侧）。"""
        rec = recover_classified_node(self.img, templates=self.tpls)
        self.assertIsNotNone(rec)
        self.assertGreater(rec.cx, 800)   # 必须在已通关列（x≈692）右侧

    def test_select_node_after_recover(self):
        """找回后 select_node 可正常决策（unknown→battle 不再触发兜底点最后一个）。"""
        rec = recover_classified_node(self.img, templates=self.tpls)
        hit, reason = select_node([rec])
        self.assertIs(hit, rec)
        self.assertIn("battle", str(hit))


if __name__ == "__main__":
    unittest.main()
