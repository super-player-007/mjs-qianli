"""赠礼决策规则测试（对应 src/game/gift.py，规则来自用户 2026-09-16 口述）。"""
from __future__ import annotations

import unittest

from src.game import gift
from src.game.gift import (
    CATEGORY_FUND,
    CATEGORY_RELAY,
    CATEGORY_SIGNAL,
    classify_hero,
    pick_gift_hero,
    pick_gift_options,
    rank_gift_types,
)


class TestClassifyHero(unittest.TestCase):
    """武将 → 三类名单。"""

    def test_signal(self):
        for n in ("荀彧", "吕布", "关羽", "钟离昧", "钟离眜", "钟离眛"):
            self.assertEqual(classify_hero(n), CATEGORY_SIGNAL, n)

    def test_relay(self):
        # 周勃同时写在信物/驰援两个名单 → 2026-09-20 定策按 信物>驰援>资助
        # 先到先得 → 周勃=信物（见 test_duplicate_first_wins）；此处用纯驰援武将
        for n in ("刘禅", "曹丕", "樊哙", "虞姬", "孙坚", "鲁肃", "大乔"):
            self.assertEqual(classify_hero(n), CATEGORY_RELAY, n)

    def test_fund(self):
        # 曹操同时写在信物/资助两个名单 → 先到先得 → 信物（见上）；用纯资助武将
        for n in ("袁术", "张春华", "黄月英", "董卓", "小乔", "夏侯惇"):
            self.assertEqual(classify_hero(n), CATEGORY_FUND, n)

    def test_duplicate_first_wins(self):
        """跨类别重复（用户 2026-09-19/20 定策）：信物 > 驰援 > 资助 先到先得。"""
        for n in ("龙且", "范增", "马超", "周勃", "刘邦", "英布", "曹操", "徐晃"):
            self.assertEqual(
                classify_hero(n), CATEGORY_SIGNAL, f"{n} 应裁决为信物")

    def test_unknown(self):
        # 吕蒙/凌统/韩信：2026-09-16 实测不在任何名单
        for n in ("吕蒙", "凌统", "韩信", "陆逊", ""):
            self.assertIsNone(classify_hero(n), n)

    def test_fuzzy_ocr_name(self):
        """OCR 截断名（如「樊」）要靠子串匹配兜住。"""
        self.assertEqual(classify_hero("樊"), CATEGORY_RELAY)
        self.assertEqual(classify_hero("黄月英赠礼".replace("赠礼", "")), CATEGORY_FUND)


class TestPickGiftHero(unittest.TestCase):
    """一级：请选择接受谁的赠礼。"""

    def test_all_unknown_pick_middle(self):
        # 实测案例：吕蒙/凌统/韩信 → 固定选中间（凌统）
        idx, reason = pick_gift_hero(["吕蒙", "凌统", "韩信"])
        self.assertEqual(idx, 1)
        self.assertIn("中间", reason)

    def test_relay_hit(self):
        # 实测案例：黄月英(资助)/张春华(资助)/樊哙(驰援) → 驰援优先 → 樊哙
        idx, reason = pick_gift_hero(["黄月英", "张春华", "樊哙"])
        self.assertEqual(idx, 2)
        self.assertIn("驰援", reason)

    def test_signal_beats_relay_and_fund(self):
        # 樊哙=驰援、袁术=资助、关羽=信物（都只在一个名单里）→ 信物最优先
        idx, _ = pick_gift_hero(["樊哙", "袁术", "关羽"])
        self.assertEqual(idx, 2)  # 关羽=信物，最优先

    def test_empty(self):
        idx, _ = pick_gift_hero([])
        self.assertIsNone(idx)


class TestPickGiftOptions(unittest.TestCase):
    """二级：XX赠礼 的具体选项。"""

    OPTS = ["信物", "并肩作战", "资助"]

    def test_relay_hero_pick_fund(self):
        # 实测案例：樊哙(驰援) → 优先级 驰援>资助>信物>… 无驰援 → 资助
        idx, reason = pick_gift_options(self.OPTS, "樊哙")
        self.assertEqual(idx, 2)
        self.assertIn("资助", reason)

    def test_signal_hero_pick_signal(self):
        # 实测案例：凌统(三类外)+选项[信物/资助/并肩作战] 走兜底 → 驰援?无 → 资助
        idx, _ = pick_gift_options(["信物", "资助", "并肩作战"], "凌统")
        self.assertEqual(idx, 1)  # 兜底优先级 驰援>资助>信物 → 资助
        # 对照：真信物武将 → 选信物
        idx2, _ = pick_gift_options(self.OPTS, "关羽")
        self.assertEqual(idx2, 0)

    def test_fund_hero_pick_fund(self):
        idx, _ = pick_gift_options(self.OPTS, "黄月英")
        self.assertEqual(idx, 2)

    def test_priority_covered_pick_wukajia(self):
        # 樊哙(驰援)：优先级 驰援>资助>信物>武将牌>并肩作战 → 命中「武将牌」
        idx, reason = pick_gift_options(["武将牌", "并肩作战"], "樊哙")
        self.assertEqual(idx, 0)
        self.assertIn("武将牌", reason)

    def test_no_covered_option_pick_middle(self):
        # 选项全都不在优先级表里 → 兜底选中间
        idx, reason = pick_gift_options(["神秘商店", "军心问答", "随机事件"], "樊哙")
        self.assertEqual(idx, 1)
        self.assertIn("兜底", reason)

    def test_priority_orders(self):
        self.assertEqual(rank_gift_types("关羽")[0], "信物")
        self.assertEqual(rank_gift_types("樊哙")[0], "驰援")
        self.assertEqual(rank_gift_types("黄月英")[0], "资助")
        self.assertEqual(rank_gift_types("吕蒙"), rank_gift_types(None))  # 都走兜底


if __name__ == "__main__":
    unittest.main()


class TestOcrAliases(unittest.TestCase):
    """OCR 误读别名表（2026-09-20 龙且漏检事故）：

    赠礼一级有龙且（信物）却选了陈宫（驰援）——根因是「龙且赠礼」标签
    OCR 误读后分类失败。别名表把误读名映射回正名再查表。
    """

    def test_alias_longmu(self):
        self.assertEqual(gift.classify_hero("龙目"), gift.CATEGORY_SIGNAL)

    def test_alias_longdan(self):
        self.assertEqual(gift.classify_hero("龙旦"), gift.CATEGORY_SIGNAL)

    def test_alias_youqie(self):
        self.assertEqual(gift.classify_hero("尤且"), gift.CATEGORY_SIGNAL)

    def test_correct_name_still_works(self):
        self.assertEqual(gift.classify_hero("龙且"), gift.CATEGORY_SIGNAL)

    def test_alias_in_pick_gift_hero(self):
        """别名命中后必须优先于驰援武将（信物最先查）。"""
        idx, reason = gift.pick_gift_hero(["陈宫", "龙目"])
        self.assertEqual(idx, 1)
        self.assertIn("信物武将 龙目", reason)

class TestRosterOrderTieBreak(unittest.TestCase):
    """同类别多位 → 按名单枚举顺序取优（2026-11-12 用户明确）。"""

    def test_longqie_beats_lvbu_regardless_of_position(self):
        """龙且/吕布同为信物：名单顺序龙且在前 → 恒选龙且。

        2026-11-12 事故：旧逻辑按屏幕位置决胜，吕布在左时误选吕布。
        """
        for heroes in (["龙且", "苏秦", "吕布"], ["吕布", "苏秦", "龙且"]):
            i, why = pick_gift_hero(heroes)
            self.assertEqual(heroes[i], "龙且", msg=why)
            self.assertIn("名单顺序", why)

    def test_uncategorized_never_wins_over_categorized(self):
        """无类别候选不参与决胜：吕布(信物) 压过苏秦/韩信。"""
        i, _ = pick_gift_hero(["苏秦", "吕布", "韩信"])
        self.assertEqual(["苏秦", "吕布", "韩信"][i], "吕布")

class TestOptionAliasWujiangPai(unittest.TestCase):
    """标准叫法「武将牌」（2026-11-13 用户澄清一直叫武将牌，"武将卡"是
    规则记录笔误）→ 选项别名把 OCR 变体"武将卡"归一。

    事故：单选项「武将牌」赠礼页 detect 为空 → classify 掉进
    hero_event_choice（提示词撞"请选择一项"白名单）→ 停机。
    """

    @staticmethod
    def _item(text, cx=900, cy=486):
        x1, y1 = cx - 50, cy - 20
        x2, y2 = cx + 50, cy + 20
        return type("I", (), {"text": text, "center": (cx, cy),
                              "rect": (x1, y1, x2, y2), "score": 1.0})()

    def test_detect_standard_and_variant(self):
        # 标准叫法直接命中；旧记录笔误"武将卡"经别名归一后同样命中
        for label in ("武将牌", "武将卡"):
            opts = gift.detect_gift_options([self._item(label)])
            self.assertEqual([(t, pos) for t, pos in opts],
                             [("武将牌", (900, 486))], msg=label)

    def test_pick_single_wujiangpai_option(self):
        i, why = gift.pick_gift_options(["武将牌"], "徐晃")
        self.assertEqual(i, 0, msg=why)
