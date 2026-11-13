"""串联执行器状态分类测试（对应 src/game/runner.py classify）。

每个夹具 = 真实对局截图，验证状态机能在每一步认出"现在在哪"。
OCR 较慢（每张 1~3s），全部跑完约 30s 属正常。
"""
from __future__ import annotations

import unittest

from src.game.runner import AutoRunner
from src.vision.annotate import read_image
from src.vision.ocr import OCREngine

from tests._base import FIXTURES

# 夹具名 → 期望状态
CASES = {
    "map_layer1.png": "map",
    "map_layer4.png": "map",
    "battle_confirm.png": "battle_confirm",
    "mulligan.png": "mulligan",
    # 战斗结束屏（无论胜负都显示「胜利」+ 预览 + 下一步）：分类为 next_preview，
    # 胜负判据在下一屏（战绩确认=继续 / 领取奖励=局终），见 docs/02 规则 14
    "battle_end_preview.png": "next_preview",
    "gift1.png": "gift1",
    "gift2.png": "gift2",
    "rest_node.png": "rest",
    "shop_main.png": "shop",
    "shop_confirm.png": "purchase_confirm",
    "hero_event_confirm.png": "hero_event_confirm",
    # 卧龙出山页：按钮 OCR 读成「选择武将」（式/武不分），靠「再想一想」区分入口页
    "hero_event_confirm_wolong.png": "hero_event_confirm",
    "hero_event_choice.png": "hero_event_choice",
    "divination.png": "divination",
    "tip_screen.png": "tip_screen",
    "resume_entry.png": "resume",
    "home_page.png": "home",
    "tap_continue.png": "tap_continue",
    "hero_info.png": "hero_info",
    "run_settle.png": "run_settle",
}


class TestClassify(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.runner = AutoRunner(ctx=None, log=None)
        cls.engine = OCREngine()

    def test_all_fixture_states(self):
        for fname, expect in CASES.items():
            with self.subTest(fixture=fname):
                img = read_image(str(FIXTURES / fname))
                self.assertIsNotNone(img, fname)
                items = self.engine.read(img)
                got = self.runner.classify(items)
                self.assertEqual(got, expect,
                                 f"{fname}: 期望 {expect}，实得 {got}")


if __name__ == "__main__":
    unittest.main()
