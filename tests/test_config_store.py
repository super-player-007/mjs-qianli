"""GUI 配置存取测试（对应 src/gui/config_store.py）。"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.gui import config_store


class TestConfigRoundtrip(unittest.TestCase):
    def test_load_missing_returns_defaults(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = config_store.load_config(Path(d) / "nope.json")
        self.assertEqual(cfg["hero"], "吕布")   # 2026-11-12 默认英雄改吕布
        self.assertEqual(cfg["runs"], 1)
        self.assertIn("hero_wolong", cfg["priority"])

    def test_load_corrupt_returns_defaults(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "gui.json"
            p.write_text("{broken json", encoding="utf-8")
            cfg = config_store.load_config(p)
        self.assertEqual(cfg["tap_scale"], 0.7)

    def test_save_load_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "gui.json"
            cfg = config_store.load_config(p)
            cfg["hero"] = "韩信"
            cfg["runs"] = 5
            cfg["priority"] = ["shop", "rest", "event"]
            cfg["categories"]["资助"] = ["董卓", "张飞"]
            config_store.save_config(cfg, p)
            cfg2 = config_store.load_config(p)
        self.assertEqual(cfg2["hero"], "韩信")
        self.assertEqual(cfg2["runs"], 5)
        self.assertEqual(cfg2["priority"], ["shop", "rest", "event"])
        self.assertEqual(cfg2["categories"]["资助"], ["董卓", "张飞"])
        # 未改的键保留默认
        self.assertEqual(cfg2["tap_scale"], 0.7)

    def test_apply_gift_categories(self):
        from src.game import gift
        original = dict(gift.HERO_CATEGORIES)
        try:
            with patch.object(gift, "HERO_CATEGORIES", {}) as fake:
                config_store.apply_gift_categories({
                    "信物": ["关羽", "马超", "钟离眜"],
                    "驰援": ["鲁肃"],
                    "资助": ["董卓"],
                })
                self.assertEqual(fake["关羽"], gift.CATEGORY_SIGNAL)
                self.assertEqual(fake["鲁肃"], gift.CATEGORY_RELAY)
                self.assertEqual(fake["董卓"], gift.CATEGORY_FUND)
                # 异体字别名：名单里有钟离眜 → 三种写法齐平
                self.assertEqual(fake["钟离眜"], gift.CATEGORY_SIGNAL)
                self.assertEqual(fake["钟离眛"], gift.CATEGORY_SIGNAL)
                self.assertEqual(fake["钟离昧"], gift.CATEGORY_SIGNAL)
        finally:
            # 无论成败都恢复真实名单（防测试污染其他用例）
            gift.HERO_CATEGORIES.clear()
            gift.HERO_CATEGORIES.update(original)


if __name__ == "__main__":
    unittest.main()

class TestConfigPathFrozenAware(unittest.TestCase):
    """gui.json 路径必须冻结感知，不能依赖 CWD（2026-11-13 事故）。

    从任务栏图标等启动时 CWD ≠ exe 目录，旧相对路径读不到 gui.json，
    静默回落默认清单（20 项无行囊）→ 商店不买行囊。
    """

    def test_load_config_works_from_wrong_cwd(self):
        import os
        import tempfile
        from src.gui import config_store

        old = os.getcwd()
        os.chdir(tempfile.gettempdir())          # 错误的启动目录
        try:
            cfg = config_store.load_config()
            w = cfg.get("shop_wanted", [])
            self.assertGreaterEqual(len(w), 20)
        finally:
            os.chdir(old)
