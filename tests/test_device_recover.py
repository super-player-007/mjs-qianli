# -*- coding: utf-8 -*-
"""设备失联自愈测试（2026-11-12）。

事故背景：连跑两小时后 `adb exec-out screencap` 连续超时，异常一路抛到
工作线程，把 20 局连跑打断。修复分三层，这里锁后两层：
1. `ADBDevice.recover()`：重启 adb 服务 → **用真实截图验证**（只看
   `adb devices` 会误判，模拟器冻死时设备列表仍是通的）；
2. `screenshot()`：首轮 raw+png 都失败 → 自愈一次再重试；
3. `run_auto()`：捕获 DeviceError → 等设备回来（最多 10 分钟）→ 继续本局。
"""
from __future__ import annotations

import subprocess
import time
import unittest
from unittest.mock import patch

from src.devices.adb import ADBDevice, DeviceError


class _Dev(ADBDevice):
    """不走真实 adb 的设备替身。"""

    def __init__(self, serials=("emulator-5554",), shot=b"x" * 2000,
                 shot_fails=False):
        super().__init__("adb.exe", serial="emulator-5554",
                         auto_connect=False)
        self._serials = list(serials)
        self._shot = shot
        self._shot_fails = shot_fails
        self.calls = []

    def list_devices(self):
        return list(self._serials)

    def _run(self, args, timeout=None, binary=False, check=True):
        self.calls.append(list(args))
        if args[:2] == ["exec-out", "screencap"]:
            if self._shot_fails:
                raise DeviceError("adb 命令超时: screencap")
            return subprocess.CompletedProcess(args, 0, self._shot, b"")
        return subprocess.CompletedProcess(args, 0, b"", b"")


class TestRecover(unittest.TestCase):
    def test_recover_ok(self):
        d = _Dev()
        with patch("src.devices.adb.time.sleep"):     # 免等真实 1-2s 间隔
            self.assertTrue(d.recover(timeout=2))
        kinds = [c[0] for c in d.calls]
        self.assertIn("kill-server", kinds)
        self.assertIn("start-server", kinds)

    def test_recover_fails_when_screencap_hangs(self):
        """adb devices 通、但截不到图 → 视为未恢复（模拟器冻死）。"""
        d = _Dev(shot_fails=True)
        with patch("src.devices.adb.time.sleep"):
            self.assertFalse(d.recover(timeout=1))

    def test_recover_fails_without_device(self):
        d = _Dev(serials=())
        with patch("src.devices.adb.time.sleep"):
            self.assertFalse(d.recover(timeout=1))


class TestScreenshotAutoRecover(unittest.TestCase):
    def test_recovers_then_succeeds(self):
        """首轮两种协议都失败 → 自愈一次 → 第二轮成功返回图像。"""
        d = _Dev()
        calls = {"n": 0}

        def fake_run(args, timeout=None, binary=False, check=True):
            if args[:2] == ["exec-out", "screencap"]:
                calls["n"] += 1
                if calls["n"] <= 2:            # raw + png 首轮都失败
                    raise DeviceError("adb 命令超时")
                # 自愈后的验证 + 重试：返回真实 raw 数据
                return subprocess.CompletedProcess(args, 0, raw_frame(), b"")
            return subprocess.CompletedProcess(args, 0, b"", b"")

        d._run = fake_run                    # type: ignore[assignment]
        d.AUTO_RECOVER = True                # 运行期行为，测试里显式开启
        with patch.object(ADBDevice, "recover", autospec=True,
                          return_value=True) as rec:
            img = d.screenshot(retries=1)
        self.assertEqual(rec.call_count, 1, "首轮失败后应尝试自愈一次")
        self.assertEqual(img.shape, (4, 6, 3))

    def test_gives_up_after_retries(self):
        d = _Dev(shot_fails=True)
        errors = {"n": 0}

        def fake_run(args, timeout=None, binary=False, check=True):
            if args[:2] == ["exec-out", "screencap"]:
                errors["n"] += 1
                raise DeviceError("adb 命令超时")
            return subprocess.CompletedProcess(args, 0, b"", b"")

        d._run = fake_run                    # type: ignore[assignment]
        with patch.object(ADBDevice, "recover", autospec=True,
                          return_value=False), \
             patch("src.devices.adb.time.sleep"):
            with self.assertRaises(DeviceError):
                d.screenshot(retries=1)


class TestWaitDeviceBack(unittest.TestCase):
    def test_returns_true_once_recovered(self):
        from src.game.runner import _wait_device_back

        class Ctx:
            class device:
                n = 0

                @staticmethod
                def recover(timeout=15.0):
                    Ctx.device.n += 1
                    return Ctx.device.n >= 2      # 第二次才成功

        with patch("src.game.runner.time.sleep"):     # 不等真实 3s 间隔
            ok = _wait_device_back(Ctx(), _Log(), timeout=10)
        self.assertTrue(ok)
        self.assertEqual(Ctx.device.n, 2)

    def test_returns_false_on_timeout(self):
        from src.game.runner import _wait_device_back

        class Ctx:
            class device:
                @staticmethod
                def recover(timeout=15.0):
                    return False

        t0 = time.time()
        with patch("src.game.runner.time.sleep"):
            ok = _wait_device_back(Ctx(), _Log(), timeout=1)
        self.assertFalse(ok)
        self.assertLess(time.time() - t0, 10)


class _Log:
    def __getattr__(self, _name):
        return lambda *a, **k: None


def raw_frame(w=6, h=4):
    """构造一帧合法的 screencap raw 数据（BGR 全零）。"""
    import struct

    return struct.pack("<III", w, h, 1) + b"\x00" * (w * h * 4 + 4)


if __name__ == "__main__":
    unittest.main()
