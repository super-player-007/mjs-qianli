"""ADBKeyboard 自动安装测试（2026-10-10 绿色版分发：其他电脑零手工）。"""
from __future__ import annotations

import logging
import unittest
from pathlib import Path
from unittest.mock import patch

from src.devices.adb import ADBDevice


def _device(tmp: Path):
    d = ADBDevice(adb_path="adb", serial="x", logger=logging.getLogger("t"))
    d.ADB_IME_APK_CANDIDATES = (str(tmp / "ADBKeyboard.apk"),)
    return d


class TestImeEnsureAutoInstall(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tmp = Path(tempfile.mkdtemp())
        (self.tmp / "ADBKeyboard.apk").write_bytes(b"apk")

    def test_not_installed_installs_then_ensures(self):
        """未安装 + APK 在 → 自动 adb install → 切输入法成功。"""
        d = _device(self.tmp)
        installed = {"n": False}
        runs = []

        def fake_shell(cmd):
            if "pm list packages" in cmd:
                return ("com.android.adbkeyboard" if installed["n"] else "other")
            if "settings get" in cmd:
                return "com.android.adbkeyboard/.AdbIME"
            return ""
        def fake_run(args):
            runs.append(list(args))
            if "install" in args:
                installed["n"] = True
            return ""
        with patch.object(ADBDevice, "shell", side_effect=fake_shell), \
             patch.object(ADBDevice, "_run", side_effect=fake_run):
            ok = d.ime_ensure()
        self.assertTrue(ok)
        self.assertTrue(any("install" in r for r in runs))   # 触发了自动安装

    def test_no_apk_returns_false(self):
        """未安装且找不到 APK → 明确失败（不再只报错让手工装）。"""
        d = ADBDevice(adb_path="adb", serial="x",
                      logger=logging.getLogger("t"))
        d.ADB_IME_APK_CANDIDATES = (str(self.tmp / "none.apk"),)
        with patch.object(ADBDevice, "shell",
                          side_effect=lambda cmd: "" if "pm" in cmd else ""), \
             patch.object(ADBDevice, "_run",
                          side_effect=AssertionError("不应触发 install")):
            ok = d.ime_ensure()
        self.assertFalse(ok)

    def test_already_installed_no_install(self):
        """已安装 → 不重复 install，直接切输入法。"""
        d = _device(self.tmp)
        runs = []
        def fake_shell(cmd):
            if "pm list packages" in cmd:
                return "com.android.adbkeyboard"
            if "settings get" in cmd:
                return "com.android.adbkeyboard/.AdbIME"
            return ""
        with patch.object(ADBDevice, "shell", side_effect=fake_shell), \
             patch.object(ADBDevice, "_run",
                          side_effect=lambda args: runs.append(args) or ""):
            ok = d.ime_ensure()
        self.assertTrue(ok)
        self.assertFalse(any("install" in r for r in runs))


if __name__ == "__main__":
    unittest.main()
