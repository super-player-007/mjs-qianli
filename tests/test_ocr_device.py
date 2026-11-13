# -*- coding: utf-8 -*-
"""识别设备选择（CPU / GPU-DirectML）测试（2026-11-12）。

GPU 开关的正确性有两层：
1. ``resolve_device`` 纯函数——什么情况下允许用 GPU、什么情况必须回落 CPU；
2. ``OCREngine._ensure``——是否真的把 ``det/cls/rec_use_dml=True`` 传给
   RapidOCR（只传全局 ``use_dml`` 是无效的，实测仍是 CPU 速度）。
"""
from __future__ import annotations

import sys
import types
import unittest

from src.vision import ocr as ocr_mod
from src.vision.ocr import OCREngine, resolve_device


class TestResolveDevice(unittest.TestCase):
    DML = ["DmlExecutionProvider", "CPUExecutionProvider"]
    CPU_ONLY = ["CPUExecutionProvider"]

    def test_cpu_always_cpu(self):
        self.assertEqual(resolve_device("cpu", self.DML, "Windows"), "cpu")

    def test_auto_with_dml(self):
        self.assertEqual(resolve_device("auto", self.DML, "Windows"), "dml")

    def test_auto_without_dml(self):
        self.assertEqual(resolve_device("auto", self.CPU_ONLY, "Windows"), "cpu")

    def test_force_dml_without_provider_falls_back(self):
        self.assertEqual(resolve_device("dml", self.CPU_ONLY, "Windows"), "cpu")

    def test_non_windows_falls_back(self):
        self.assertEqual(resolve_device("auto", self.DML, "Darwin"), "cpu")

    def test_unknown_value_treated_as_auto(self):
        self.assertEqual(resolve_device("gpu?", self.DML, "Windows"), "dml")

    def test_default_is_auto(self):
        self.assertIn(resolve_device("", self.CPU_ONLY, "Windows"), ("cpu", "dml"))


class _FakeRapidOCR:
    """记录每次构造参数；可选在 DML 参数时抛错（验证回落到 CPU）。"""

    calls: list = []
    fail_on_dml = False

    def __init__(self, **kwargs):
        type(self).calls.append(kwargs)
        if type(self).fail_on_dml and kwargs.get("det_use_dml"):
            raise RuntimeError("DML 初始化失败（模拟）")

    def __call__(self, canvas):
        return []


class TestEngineDeviceWiring(unittest.TestCase):
    def setUp(self):
        _FakeRapidOCR.calls = []
        _FakeRapidOCR.fail_on_dml = False
        self._orig_mod = sys.modules.get("rapidocr_onnxruntime")
        fake = types.ModuleType("rapidocr_onnxruntime")
        fake.RapidOCR = _FakeRapidOCR
        sys.modules["rapidocr_onnxruntime"] = fake
        self._orig_resolve = ocr_mod.resolve_device

    def tearDown(self):
        if self._orig_mod is not None:
            sys.modules["rapidocr_onnxruntime"] = self._orig_mod
        else:
            sys.modules.pop("rapidocr_onnxruntime", None)
        ocr_mod.resolve_device = self._orig_resolve

    def test_dml_passes_per_model_flags(self):
        ocr_mod.resolve_device = lambda *_a, **_k: "dml"
        eng = OCREngine(device="dml")
        self.assertTrue(eng.available)
        self.assertEqual(eng.device, "dml")
        kw = _FakeRapidOCR.calls[-1]
        self.assertTrue(kw.get("det_use_dml"))
        self.assertTrue(kw.get("cls_use_dml"))
        self.assertTrue(kw.get("rec_use_dml"))

    def test_cpu_does_not_pass_dml_flags(self):
        ocr_mod.resolve_device = lambda *_a, **_k: "cpu"
        eng = OCREngine(device="cpu")
        self.assertTrue(eng.available)
        self.assertEqual(eng.device, "cpu")
        self.assertNotIn("det_use_dml", _FakeRapidOCR.calls[-1])

    def test_dml_failure_falls_back_to_cpu(self):
        ocr_mod.resolve_device = lambda *_a, **_k: "dml"
        _FakeRapidOCR.fail_on_dml = True
        eng = OCREngine(device="dml")
        self.assertTrue(eng.available, "GPU 初始化失败也必须能继续跑")
        self.assertEqual(eng.device, "cpu")
        self.assertEqual(len(_FakeRapidOCR.calls), 2)       # 先 DML 再 CPU
        self.assertNotIn("det_use_dml", _FakeRapidOCR.calls[-1])


if __name__ == "__main__":
    unittest.main()
