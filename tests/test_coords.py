"""配置与素材完整性测试：保证「六件套」里的坐标 / 模板不断档。

凡是策略文档（docs/02 第四章）承诺过的固定点，这里都必须存在且合法 ——
防止"文档写了、配置漏了"或"坐标改了、文档没跟"的交付事故。
"""
from __future__ import annotations

import unittest
from pathlib import Path

import yaml

from tests._base import PROJECT_ROOT, TPL_DIR

COORDS = PROJECT_ROOT / "config" / "coords.yaml"
WIDTH, HEIGHT = 1920, 1080  # 标定基准分辨率


def load_screens() -> dict:
    data = yaml.safe_load(COORDS.read_text(encoding="utf-8"))
    return data["screens"]


class TestCoordIntegrity(unittest.TestCase):
    """坐标配置完整性与合法性。"""

    @classmethod
    def setUpClass(cls):
        cls.screens = load_screens()

    def get(self, *path):
        node = self.screens
        for p in path:
            node = node[p]
        return node

    def test_yaml_loads(self):
        self.assertIn("battle", self.screens)
        self.assertIn("run_map", self.screens)

    def test_required_points_exist(self):
        """docs/02 第四章策略规则引用的全部固定点。"""
        required = [
            ("battle_confirm", "start_battle"),     # 规则：开始对局
            ("battle_mulligan", "cancel"),          # 规则2：固定取消
            ("battle", "menu_disc"),                # 规则3：托管金盘
            ("battle", "trustee"),                  # 规则3：托管
            ("victory_chain", "blank"),             # 规则4a：完胜空白
            ("victory_chain", "next"),              # 规则4b：下一步
            ("victory_chain", "confirm"),           # 规则4c：确认
            ("run_map", "end_run"),                 # 结束挑战（高风险）
        ]
        for path in required:
            node = self.get(*path)
            xy = node.get("xy") if isinstance(node, dict) else None
            self.assertIsInstance(xy, list, f"缺少坐标点 {path}")
            self.assertEqual(len(xy), 2, f"{path} 坐标必须是 [x, y]")

    def test_points_within_1080p(self):
        """所有 point 类型坐标必须落在 1920×1080 内（适配基准）。"""
        bad = []

        def walk(node, path):
            if isinstance(node, dict):
                if node.get("type") == "point":
                    x, y = node["xy"]
                    if not (0 <= x < WIDTH and 0 <= y < HEIGHT):
                        bad.append(path)
                for k, v in node.items():
                    walk(v, f"{path}.{k}" if path else k)
            elif isinstance(node, list):
                for i, v in enumerate(node):
                    walk(v, f"{path}[{i}]")

        walk(self.screens, "")
        self.assertEqual(bad, [], f"越界坐标: {bad}")

    def test_nav_chain_complete(self):
        nav = yaml.safe_load(COORDS.read_text(encoding="utf-8"))["nav"]
        self.assertEqual(nav["chain"], ["home", "campaign", "qianli"])
        for page in ("home", "campaign"):
            self.assertIn(page, nav["steps"])
        for page in ("campaign", "qianli"):
            self.assertIn(page, nav["back"])


class TestTemplates(unittest.TestCase):
    """图像模板素材。"""

    def test_battle_template_exists(self):
        p = TPL_DIR / "node_battle.png"
        self.assertTrue(p.exists(), f"缺少 {p}")

    def test_shop_and_rest_templates_exist(self):
        """2026-09-17 第 3 层实测新增：商店（圆下图标）+ 休息（圆内本体）。"""
        for name in ("node_shop.png", "node_rest.png"):
            self.assertTrue((TPL_DIR / name).exists(), f"缺少 {name}")

    def test_hero_mate_event_templates_exist(self):
        """2026-09-17 第 4/6 层实测：武将/伙伴按事件存模板；事件=圆内钱袋。"""
        for name in ("node_hero_shier.png", "node_hero_moja.png",
                     "node_mate_dog.png", "node_event.png",
                     "node_hero_wolong.png", "node_hero_fengfeng.png",
                     "node_mate_feifei.png"):
            self.assertTrue((TPL_DIR / name).exists(), f"缺少 {name}")

    def test_all_six_node_types_have_templates(self):
        """6 种节点类型（战斗/商店/事件/休息/武将/伙伴）模板必须齐全。"""
        from src.game.node_icon import NODE_LABELS, load_node_templates, template_kind
        kinds = {template_kind(k) for k in load_node_templates(TPL_DIR)}
        for kind in NODE_LABELS:
            self.assertIn(kind, kinds, f"类型 {kind} 缺模板")

    def test_templates_loadable(self):
        from src.game.node_icon import load_node_templates
        tpls = load_node_templates(TPL_DIR)
        self.assertIn("battle", tpls)
        self.assertIn("shop", tpls)
        self.assertIn("rest", tpls)
        w, h = tpls["battle"].shape[:2][::-1]
        self.assertEqual((w, h), (35, 30))  # 图标模板基准尺寸，改动需同步 ICON_W/H
        w2, h2 = tpls["rest"].shape[:2][::-1]
        self.assertEqual((w2, h2), (64, 64))  # 本体模板基准尺寸，改动需同步 BODY_TPL_SIZE

    def test_no_junk_templates(self):
        """模板目录只允许真实节点图标（*_clip 与印章等已废弃素材不得回流）。"""
        keys = [p.stem[len("node_"):] for p in TPL_DIR.glob("node_*.png")]
        for k in keys:
            self.assertFalse(k.endswith("_clip"), k)
            self.assertNotIn(k, ("done",), "已通关印章模板已证伪，不得回流")


if __name__ == "__main__":
    unittest.main()
