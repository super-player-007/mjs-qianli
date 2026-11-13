# -*- coding: utf-8 -*-
"""分层架构护栏（2026-11-12 重构，学习一条龙但只取"分层"这一条）。

这些不是功能测试，是**架构测试**：一旦有人把 GUI 依赖写进业务层、
或者把业务依赖写进控件层，测试立刻失败。目的很明确——保持
「业务可脱离界面运行、界面可脱离业务测试」，这是自动化项目最容易腐烂的地方。

允许的唯一例外：``src/core/asker.py``（决策提问要弹 tkinter 窗口，
是"人机交互"本身的职责，不属于 GUI 展示层）。
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

SRC = Path("src")


def _py_files(rel: str):
    return sorted((SRC / rel).rglob("*.py"))


def _import_lines(path: Path):
    """返回 (行号, 行内容)，只挑 import 语句（含函数内 import）。"""
    out = []
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        s = line.strip()
        if re.match(r"^(import|from)\s+", s):
            out.append((i, s))
    return out


def _find(files, pattern: str, allow=()):
    hits = []
    rx = re.compile(pattern)
    for f in files:
        if f.name in allow:
            continue
        for no, line in _import_lines(f):
            if rx.search(line):
                hits.append(f"{f}:{no}: {line}")
    return hits


class TestLayering(unittest.TestCase):
    def test_game_layer_has_no_gui(self):
        """业务层（src/game）不得依赖 GUI —— 否则无法脱离界面跑测试/CLI。"""
        hits = _find(_py_files("game"), r"\btkinter\b|src\.gui|^from src\.gui")
        self.assertEqual(hits, [], "业务层出现 GUI 依赖：\n" + "\n".join(hits))

    def test_perception_layers_have_no_business(self):
        """视觉/设备/核心层不得反向依赖业务层或 GUI。"""
        for rel in ("vision", "devices"):
            hits = _find(_py_files(rel), r"src\.game|src\.gui")
            self.assertEqual(hits, [], f"{rel} 层反向依赖：\n" + "\n".join(hits))

    def test_widgets_stay_dumb(self):
        """控件层只做渲染：不得 import 业务/视觉/设备。"""
        hits = _find([SRC / "gui" / "widgets.py"], r"src\.game|src\.vision|src\.devices")
        self.assertEqual(hits, [], "控件层混入业务依赖：\n" + "\n".join(hits))

    def test_asker_is_documented_exception(self):
        """tkinter 只允许出现在 GUI 层、_deps 聚合文件与 asker（决策弹窗）。"""
        files = (_py_files("game") + _py_files("vision")
                 + _py_files("devices") + _py_files("core"))
        hits = _find(files, r"\btkinter\b", allow={"asker.py"})
        self.assertEqual(hits, [], "tkinter 泄漏到非 UI 模块：\n" + "\n".join(hits))

    def test_gui_app_keeps_run_import_lazy(self):
        """app.py 对 run.py（含设备/OCR 装配）的引用必须放在函数内。

        进程常驻的 GUI 若在模块顶层 import run，会在启动时就加载
        cv2/onnxruntime，拖慢开窗并让「停止→改代码→启动」失效。
        """
        text = (SRC / "gui" / "app.py").read_text(encoding="utf-8")
        bad = [ln for ln in text.splitlines()
               if re.match(r"^(import\s+run\b|from\s+run\s+import)", ln)]
        self.assertEqual(bad, [], "app.py 顶层不得 import run：" + str(bad))


if __name__ == "__main__":
    unittest.main()
