"""休息节点（安营驻寨）决策规则测试（对应 src/game/rest.py）。"""
from __future__ import annotations

import unittest

from src.game.rest import (REST_CASES, detect_rest_case, detect_rest_options,
                           pick_rest_option)


class TestRestCases(unittest.TestCase):
    """四种情况的判别与优先选择（选项名 = 用户口述原文）。"""

    def test_case1(self):
        opts = ["积草屯粮", "以逸待劳", "养精蓄锐"]
        idx, reason = pick_rest_option(opts)
        self.assertEqual(idx, 1)
        self.assertIn("情况一", reason)

    def test_case2(self):
        opts = ["研读兵法", "稳中求进", "养精蓄锐"]
        idx, reason = pick_rest_option(opts)
        self.assertEqual(idx, 1)
        self.assertIn("情况二", reason)

    def test_case3(self):
        # 2026-09-17 第 3 层实测画面
        opts = ["广纳贤才", "固本培元", "养精蓄锐"]
        idx, reason = pick_rest_option(opts)
        self.assertEqual(idx, 1)
        self.assertIn("情况三", reason)

    def test_case4(self):
        # 2026-10-12 用户改：第 4 情况优先「劫营速战」（原选秣马厉兵）
        opts = ["秣马厉兵", "劫营速战", "养精蓄锐"]
        idx, reason = pick_rest_option(opts)
        self.assertEqual(idx, 1)
        self.assertIn("情况四", reason)

    def test_case4_order_independent(self):
        """选项顺序颠倒（劫营速战在前）也选它。"""
        idx, reason = pick_rest_option(["劫营速战", "秣马厉兵", "养精蓄锐"])
        self.assertEqual(idx, 0)
        self.assertIn("情况四", reason)

    def test_marker_with_brackets_and_noise(self):
        """OCR 可能带【】或换行残片，要能容错。"""
        opts = "【广纳贤才】", "【固本培元 】", "【养精蓄锐】"
        idx, _ = pick_rest_option(opts)
        self.assertEqual(idx, 1)

    def test_unknown_case_fallback_yangjing(self):
        # 编一个未知组合，但有兜底项
        idx, reason = pick_rest_option(["神秘选项甲", "神秘选项乙", "养精蓄锐"])
        self.assertEqual(idx, 2)
        self.assertIn("兜底", reason)

    def test_unknown_no_fallback_pick_middle(self):
        idx, reason = pick_rest_option(["甲", "乙", "丙"])
        self.assertEqual(idx, 1)
        self.assertIn("人工复核", reason)

    def test_empty(self):
        idx, _ = pick_rest_option([])
        self.assertIsNone(idx)

    def test_all_cases_have_unique_markers(self):
        """判别标记彼此不能混淆——防止规则表写重。"""
        all_markers = [m for c in REST_CASES for m in c["markers"]]
        self.assertEqual(len(all_markers), len(set(all_markers)))
        # 养精蓄锐不能当判别标记（四种情况都有）
        self.assertNotIn("养精蓄锐", all_markers)

    def test_detect_case(self):
        self.assertEqual(detect_rest_case(["广纳贤才", "固本培元"])["case"], "三")
        self.assertIsNone(detect_rest_case(["不知所云"]))


class TestRestOnFixture(unittest.TestCase):
    """端到端：真实截图 → OCR → 选项检测 → 决策（慢，约 3~5s）。"""

    def test_layer3_rest_screen(self):
        from src.vision.ocr import OCREngine
        from src.vision.annotate import read_image
        from tests._base import FIXTURES

        eng = OCREngine()
        items = eng.read(read_image(str(FIXTURES / "rest_node.png")))
        opts = detect_rest_options(items)
        self.assertEqual([o for o, _ in opts], ["广纳贤才", "固本培元", "养精蓄锐"])
        idx, reason = pick_rest_option([o for o, _ in opts])
        self.assertEqual(idx, 1)
        self.assertIn("固本培元", reason)
        # 点击点 = 【标题】框中心 y+40（选项卡中部，实测可点）
        self.assertAlmostEqual(opts[1][1][0], 808, delta=6)
        for _, (cx, cy) in opts:
            self.assertTrue(840 <= cy <= 900, (cx, cy))



if __name__ == "__main__":
    unittest.main()
