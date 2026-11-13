"""runner 多轮/暂停/停止能力测试（GUI 集成前提）。"""
from __future__ import annotations

import logging
import threading
import unittest
from unittest.mock import patch

from src.game.runner import STATE_DONE, STATE_OK, STATE_STOP, AutoRunner, run_auto


def make_items(state_text):
    class FakeItem:
        def __init__(self, text):
            self.text = text
            self.rect = [0, 0, 10, 10]
    return [FakeItem(state_text)]


class TestControl(unittest.TestCase):
    def _make_runner(self):
        return AutoRunner(ctx=None, log=logging.getLogger("t"))

    def test_tap_counts_and_scale(self):
        r = self._make_runner()
        taps = []
        class Ctx:
            def tap_point(self, pt, **kw):
                taps.append(pt)
        r.ctx = Ctx()
        with patch("src.game.runner.time.sleep"):
            r._tap(1, 2)
        self.assertEqual(taps, [(1, 2)])
        self.assertEqual(r.stats["clicks"], 1)

    def test_stop_event_breaks_wait(self):
        r = self._make_runner()
        r.set_control(threading.Event(), threading.Event())
        r.stop_event.set()
        self.assertFalse(r._wait_if_paused())

    def test_pause_blocks_until_cleared(self):
        r = self._make_runner()
        pause, stop = threading.Event(), threading.Event()
        r.set_control(pause, stop)
        pause.set()
        timer = threading.Timer(0.3, pause.clear)
        timer.start()
        self.assertTrue(r._wait_if_paused())
        timer.join()

    def test_status_cb_called(self):
        r = self._make_runner()
        seen = []
        r.set_control(threading.Event(), threading.Event(),
                      status_cb=lambda s: seen.append(s))
        r._publish("running", "test")
        self.assertEqual(seen[-1]["state"], "running")
        self.assertEqual(seen[-1]["msg"], "test")


if __name__ == "__main__":
    unittest.main()


class TestMaxSteps(unittest.TestCase):
    """步数预算（2026-09-20：无尽深层单局 >500 步，预算提到 2000）。"""

    def _patch_step(self, runner_obj, status, msg="ok"):
        from unittest.mock import patch
        return patch.object(AutoRunner, "step",
                            side_effect=lambda: (status, msg))

    def test_max_steps_skips_run_not_batch(self):
        """单局超步数 → 跳过该局继续下一局（不再连坐 return 3）。"""
        import logging
        from unittest.mock import patch

        def fake_step(self, status=STATE_OK, msg="ok"):
            self.steps += 1          # 真 step 会计数，mock 必须同样计数
            return (status, msg)

        with patch.object(AutoRunner, "step", new=fake_step), \
             patch("src.game.runner.time.sleep"):
            rc = run_auto(object(), logging.getLogger("t"), runs=2,
                          max_steps=3)
        self.assertEqual(rc, 0)   # 两局都因超步数跳过 → 批次正常结束

    def test_done_still_finishes(self):
        import logging
        from unittest.mock import patch

        def fake_step(self):
            self.steps += 1
            return (STATE_DONE, "完成")

        with patch.object(AutoRunner, "step", new=fake_step), \
             patch("src.game.runner.time.sleep"):
            rc = run_auto(object(), logging.getLogger("t"), runs=2,
                          max_steps=5)
        self.assertEqual(rc, 0)


class TestTrusteeBlockedByHeroInfo(unittest.TestCase):
    """托管被「武将技能/武将信息」弹层遮挡（2026-09-20 事故）→
    重试时先关弹层再试，不再 3 连败停机。"""

    def test_retry_closes_hero_info_overlay(self):
        import logging
        from unittest.mock import patch
        r = AutoRunner(ctx=None, log=logging.getLogger("t"))
        taps = []

        class Ctx:
            def tap_point(self, pt, **kw):
                taps.append(pt)

        r.ctx = Ctx()
        overlay = [FakeItem2("武将技能", 700, 100), FakeItem2("武将信息", 950, 120)]
        trustee_on = [FakeItem2("取消托管", 1800, 300)]
        # 2026-11-12 快路径：首轮会先做一次**局部** OCR（右上角托管区），
        # 未命中才整屏 OCR 诊断。所以调用序为：
        #   局部(空) → 整屏(面板) → 关面板 → 局部(取消托管) 成功
        shots = iter([[], overlay, trustee_on])
        with patch.object(AutoRunner, "_shot", side_effect=lambda *a, **k: object()), \
             patch.object(AutoRunner, "_ocr", side_effect=lambda img, region=None: next(shots)), \
             patch.object(AutoRunner, "_tap",
                          side_effect=lambda x, y, wait=0: taps.append((x, y))), \
             patch("src.game.runner.time.sleep"):
            status, msg = r._act_battle([])
        self.assertEqual(status, STATE_OK)
        # 动作序列：金盘→托管→(见面板)点左上空白关闭→金盘→托管→验证成功
        # （2026-09-24/25 两轮 adb 实验验证：(300,100) 有效；(400,300) 落在
        #   蜀汉横幅上无效、(1800,250) 落在面板文字区无效）
        self.assertEqual(taps[2], (300, 100))
        self.assertIn("托管已生效", msg)


class FakeItem2:
    def __init__(self, text, cx, cy):
        self.text = text
        self.rect = [cx - 60, cy - 14, cx + 60, cy + 14]


if __name__ == "__main__":
    unittest.main()


class TestTrusteeTransitionFrame(unittest.TestCase):
    """多局连跑的结算过渡帧被误判 battle（2026-09-21 01:56 事故）→
    托管重试时每轮重分类：不再是 battle 就交回主流程，不死磕。"""

    def test_transition_frame_returns_control(self):
        import logging
        from unittest.mock import patch
        r = AutoRunner(ctx=None, log=logging.getLogger("t"))
        result_page = [FakeItem2("下一步", 960, 940)]
        with patch.object(AutoRunner, "_shot", side_effect=lambda *a, **k: object()), \
             patch.object(AutoRunner, "_ocr", side_effect=lambda img, region=None: result_page), \
             patch.object(AutoRunner, "classify", side_effect=lambda items: "next_preview"), \
             patch.object(AutoRunner, "_tap",
                          side_effect=lambda x, y, wait=0: None), \
             patch("src.game.runner.time.sleep"):
            status, msg = r._act_battle([])
        self.assertEqual(status, STATE_OK)
        self.assertIn("交回主流程", msg)


class TestBlankTransitionFrame(unittest.TestCase):
    """零文字过渡帧（2026-09-24 战绩确认后过场事故）：等待而非停机，
    连续 >12 帧才判真卡死；见到有文字的状态立即复位计数。"""

    def _run_steps(self, blank_times, max_steps=30):
        """模拟：前 blank_times 步全空白帧，之后恢复已知状态。"""
        import logging
        from unittest.mock import patch
        r = AutoRunner(ctx=None, log=logging.getLogger("t"))
        calls = {"n": 0}
        known = [FakeItem2("结束挑战", 1600, 870), FakeItem2("当前挑战", 300, 200)]

        def fake_ocr(img, region=None):
            calls["n"] += 1
            return [] if calls["n"] <= blank_times else known

        with patch.object(AutoRunner, "_shot",
                          side_effect=lambda *a, **k: object()), \
             patch.object(AutoRunner, "_ocr", side_effect=fake_ocr), \
             patch.object(AutoRunner, "_act_map",
                          side_effect=lambda: (STATE_OK, "选节点")), \
             patch("src.game.runner.time.sleep") as sl:
            results = []
            for _ in range(max_steps):
                res = r.step()
                results.append(res)
                if res[0] == STATE_STOP:
                    break                  # 停机后不再继续踩步
        return results, sl

    def test_blank_frames_wait_then_recover(self):
        results, _ = self._run_steps(blank_times=5)
        # 前 5 步是过渡等待，第 6 步恢复地图
        self.assertTrue(all("过渡/未知帧" in m for _, m in results[:5]))
        self.assertEqual(results[5][0], STATE_OK)
        self.assertEqual(results[5][1], "选节点")

    def test_persistent_blank_stops(self):
        results, _ = self._run_steps(blank_times=20)
        waits = [r for r in results if "过渡/未知帧" in r[1]]
        self.assertEqual(len(waits), 12)          # 容忍 12 帧
        self.assertEqual(results[12][0], STATE_STOP)
        self.assertIn("停机等人工", results[12][1])


if __name__ == "__main__":
    unittest.main()


class TestMulliganWait(unittest.TestCase):
    """换手牌「取消」后的等待 3.0（2026-09-24 用户要求 +1s，给弹窗收场动画留时间）"""

    def test_mulligan_tap_wait_3(self):
        import logging
        from unittest.mock import patch
        r = AutoRunner(ctx=None, log=logging.getLogger("t"))
        waits = []

        class Ctx:
            def tap_point(self, pt, **kw):
                pass
        r.ctx = Ctx()
        with patch.object(AutoRunner, "_shot", side_effect=lambda *a, **k: None), \
             patch.object(AutoRunner, "_ocr",
                          return_value=[FakeItem2("是否需要更换初始手牌", 960, 200)]), \
             patch.object(AutoRunner, "_tap",
                          side_effect=lambda x, y, wait=0: waits.append(wait)), \
             patch("src.game.runner.time.sleep"):
            r.step()
        self.assertEqual(waits, [4.0])


class TestTrusteeLocalPolling(unittest.TestCase):
    """托管等待局部轮询（2026-09-25 优化 + 00:45 完胜页 HUD 残留修正）。

    战斗胜利后右上角「取消托管」HUD 会**残留**在完胜页上——只查右上区域
    会永远等不到按钮消失。必须加查底部流程锚点（点击空白区域到下一步等）。
    """

    def _make(self):
        import logging
        from unittest.mock import patch
        r = AutoRunner(ctx=None, log=logging.getLogger("t"), poll_sleep=0.0)
        return r, patch

    def test_local_poll_until_button_gone(self):
        """按钮真的消失（战斗中结束）→ 连续 6 轮确认后交回主流程。

        2026-11-12：退出改为「连续 6 轮空窗」才交回（原来一次为空即退出）。
        原因：右上角 HUD 在敌方回合会短暂隐藏，一次空窗就退出会导致
        主循环→又判 battle→再进轮询的乒乓（实测同一场战斗被拆成 11 步）。
        """
        from src.game.runner import TRUSTEE_CHECK_REGION
        r, patch = self._make()
        on = [FakeItem2("取消托管", 1840, 280)]
        calls = {"region": 0}

        def fake_ocr(img, region=None):
            if region == TRUSTEE_CHECK_REGION:   # 只数右上角检查
                calls["region"] += 1
                return on if calls["region"] <= 2 else []
            return []                            # 底部无锚点

        with patch.object(AutoRunner, "_shot", side_effect=lambda *a, **k: object()), \
             patch.object(AutoRunner, "_ocr", side_effect=fake_ocr), \
             patch("src.game.runner.time.sleep"):
            status, msg = r._act_battle([FakeItem2("取消托管", 1840, 280)])
        self.assertEqual(status, STATE_OK)
        self.assertIn("交回主流程", msg)
        self.assertEqual(calls["region"], 2 + 6)   # 2 轮有 HUD + 6 轮空窗确认

    def test_anchor_fast_path_skips_ocr(self):
        """投降锚点命中 = 战斗进行中 → 轮询不做任何 OCR（2026-11-12）。

        实测：旧逻辑每轮 2 次局部 OCR（~0.6s），且 HUD 一闪就误判结束；
        快路径用 20ms 的锚点匹配替代，轮询周期从 ~4.5s 降到 ~1s。
        """
        r, patch = self._make()
        ocr_calls = {"n": 0}
        pause_calls = {"n": 0}

        def fake_ocr(img, region=None):
            ocr_calls["n"] += 1
            return []

        def fake_pause():
            pause_calls["n"] += 1
            return pause_calls["n"] <= 3          # 第 4 轮让循环停下

        with patch.object(AutoRunner, "_shot", side_effect=lambda *a, **k: object()), \
             patch.object(AutoRunner, "_ocr", side_effect=fake_ocr), \
             patch.object(AutoRunner, "_anchor_state", return_value="battle"), \
             patch.object(AutoRunner, "_wait_if_paused", side_effect=fake_pause), \
             patch("src.game.runner.time.sleep"):
            status, msg = r._act_battle([FakeItem2("取消托管", 1840, 280)])
        self.assertEqual(status, STATE_STOP)      # 由 pause 桩停止
        self.assertEqual(ocr_calls["n"], 0, "快路径不应触发任何 OCR")
        self.assertEqual(pause_calls["n"], 4)

    def test_victory_page_hud_residual(self):
        """完胜页残留取消托管 HUD：底部锚点命中 → 立即交回主流程。"""
        r, patch = self._make()
        on = [FakeItem2("取消托管", 1840, 280)]
        victory = [FakeItem2("完胜", 960, 760),
                   FakeItem2("点击空白区域到下一步", 960, 965)]
        region_calls = {"n": 0}

        def fake_ocr(img, region=None):
            from src.game.runner import (TRUSTEE_CHECK_REGION,
                                         BOTTOM_FLOW_REGION)
            if region == BOTTOM_FLOW_REGION:
                return victory                   # 底部锚点命中
            region_calls["n"] += 1               # 右上：HUD 残留，永远"有"按钮
            return on

        with patch.object(AutoRunner, "_shot", side_effect=lambda *a, **k: object()), \
             patch.object(AutoRunner, "_ocr", side_effect=fake_ocr), \
             patch("src.game.runner.time.sleep"):
            status, msg = r._act_battle([FakeItem2("取消托管", 1840, 280)])
        self.assertEqual(status, STATE_OK)
        self.assertIn("底部流程锚点命中", msg)
        self.assertEqual(region_calls["n"], 1)   # 第一次检查就识别，不死等

    def test_local_poll_timeout_falls_to_retry(self):
        """真在打（按钮在、无底部锚点）120 次后落到托管重试，验证发现托管仍生效。"""
        r, patch = self._make()
        on = [FakeItem2("取消托管", 1840, 280)]
        taps = []

        class Ctx:
            def tap_point(self, pt, **kw):
                taps.append(pt)
        r.ctx = Ctx()
        with patch.object(AutoRunner, "_shot", side_effect=lambda *a, **k: object()), \
             patch.object(AutoRunner, "_ocr",
                          side_effect=lambda img, region=None: on), \
             patch("src.game.runner.time.sleep"):
            status, msg = r._act_battle([FakeItem2("取消托管", 1840, 280)])
        self.assertEqual(status, STATE_OK)
        self.assertIn("托管已生效", msg)         # 重试验证发现托管确实在跑


if __name__ == "__main__":
    unittest.main()


class TestTextfulUnknownFrame(unittest.TestCase):
    """带零星文字的过渡帧（2026-09-25 01:12 事故）：画面有「背包」按钮一词，
    旧条件"零文字才等待"接不住 → 放宽为所有 unknown 一律先等待 12 帧。"""

    def _steps(self, runner_obj, pages):
        import logging
        from unittest.mock import patch
        seq = iter(pages)
        results = []
        with patch.object(AutoRunner, "_shot",
                          side_effect=lambda *a, **k: object()), \
             patch.object(AutoRunner, "_ocr",
                          side_effect=lambda img, region=None: next(seq)), \
             patch.object(AutoRunner, "_act_map",
                          side_effect=lambda: (STATE_OK, "选节点")), \
             patch("src.game.runner.time.sleep"):
            for _ in range(len(pages)):
                res = runner_obj.step()
                results.append(res)
                if res[0] == STATE_STOP:
                    break
        return results

    def test_backpack_frame_waits_then_recovers(self):
        import logging
        r = AutoRunner(ctx=None, log=logging.getLogger("t"))
        backpack = [FakeItem2("背包", 130, 960)]
        known = [FakeItem2("结束挑战", 1600, 870), FakeItem2("当前挑战", 300, 200)]
        results = self._steps(r, [backpack] * 3 + [known])
        self.assertTrue(all("过渡/未知帧" in m for _, m in results[:3]))
        self.assertEqual(results[3][1], "选节点")   # 第 4 步恢复

    def test_persistent_textful_unknown_stops(self):
        import logging
        r = AutoRunner(ctx=None, log=logging.getLogger("t"))
        backpack = [FakeItem2("背包", 130, 960)]
        results = self._steps(r, [backpack] * 20)
        waits = [m for _, m in results if "过渡/未知帧" in m]
        self.assertEqual(len(waits), 12)
        self.assertEqual(results[12][0], STATE_STOP)
        self.assertIn("停机等人工", results[12][1])


if __name__ == "__main__":
    unittest.main()
