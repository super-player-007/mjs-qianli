# -*- coding: utf-8 -*-
"""启动器（无黑窗 exe）测试（2026-11-13）。

启动器本身是 C# WinExe，编译产物不入库可以，但**接线必须锁住**：
文档/批处理/源码位置一旦漂移，用户双击就"没反应"。
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "tools" / "launcher" / "启动控制台.cs"
BUILD = ROOT / "tools" / "build_launcher.bat"
EXE = ROOT / "启动控制台.exe"
BAT = ROOT / "启动控制台.bat"


class TestLauncherWiring(unittest.TestCase):
    def test_source_exists(self):
        self.assertTrue(SOURCE.is_file(), "启动器源码缺失")

    def test_source_targets_winexe_and_pythonw(self):
        text = SOURCE.read_text(encoding="utf-8")
        self.assertIn("pythonw.exe", text, "必须用无控制台解释器")
        self.assertIn("run.py gui", text)
        self.assertIn("CreateNoWindow", text)

    def test_build_script_uses_csc_winexe(self):
        text = BUILD.read_text(encoding="utf-8", errors="replace")
        self.assertIn("csc.exe", text.lower())
        self.assertIn("/target:winexe", text, "target=winexe 才没有黑窗")

    def test_bat_forwards_to_exe(self):
        text = BAT.read_text(encoding="utf-8", errors="replace")
        self.assertIn("启动控制台.exe", text)

    def test_exe_is_gui_subsystem_when_present(self):
        """有产物时校验 PE 子系统=2（Windows GUI），否则跳过（新仓库未编译）。"""
        if not EXE.is_file():
            self.skipTest("尚未编译启动器（tools/build_launcher.bat）")
        data = EXE.read_bytes()
        pe = int.from_bytes(data[0x3C:0x40], "little")
        subsystem = int.from_bytes(data[pe + 0x5C:pe + 0x5E], "little")
        self.assertEqual(subsystem, 2, "子系统必须是 GUI，否则会弹控制台")


if __name__ == "__main__":
    unittest.main()
