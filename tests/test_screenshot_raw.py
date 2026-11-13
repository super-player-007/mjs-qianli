# -*- coding: utf-8 -*-
"""raw 截图解析测试（2026-11-12）。

背景：``adb exec-out screencap -p``（PNG）实测 984ms/帧，而 raw 只要 374ms
——换成 raw 是全局最大的单点提速（一局 150+ 次截图）。但 raw 有两个陷阱：
① 头长度随 Android 版本变化（12 / 16 字节）；
② 内存是 RGBA，必须 ``COLOR_RGBA2BGR``，用 BGRA2BGR 或丢 alpha 会红蓝互换。
本测试把这两条锁死，防止以后改坏。
"""
from __future__ import annotations

import struct
import unittest

import cv2
import numpy as np

from src.devices.adb import ADBDevice, DeviceError


def make_raw(img_bgr: np.ndarray, header: int = 16) -> bytes:
    """把 BGR 图编码成 screencap raw 字节流（模拟设备输出）。"""
    h, w = img_bgr.shape[:2]
    rgba = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGBA)
    head = struct.pack("<III", w, h, 1)
    if header == 16:
        head += b"\x00\x00\x00\x00"          # colorspace（Android 8+）
    return head + rgba.tobytes()


def sample_bgr() -> np.ndarray:
    """构造有明显红/蓝差异的图（通道顺序错了必然被抓）。"""
    img = np.zeros((5, 7, 3), np.uint8)
    img[:, :, 0] = 200       # B
    img[:, :, 1] = 60        # G
    img[:, :, 2] = 10        # R
    return img


class TestRawScreencap(unittest.TestCase):
    def test_roundtrip_16_byte_header(self):
        img = sample_bgr()
        out = ADBDevice.parse_raw_screencap(make_raw(img, 16))
        self.assertEqual(out.shape, img.shape)
        self.assertTrue(np.array_equal(out, img), "16 字节头往返应完全一致")

    def test_roundtrip_12_byte_header(self):
        img = sample_bgr()
        out = ADBDevice.parse_raw_screencap(make_raw(img, 12))
        self.assertTrue(np.array_equal(out, img), "12 字节头（旧 Android）应兼容")

    def test_channel_order_not_swapped(self):
        """红蓝通道不能互换（BGRA2BGR / 丢 alpha 都会错）。"""
        img = sample_bgr()
        out = ADBDevice.parse_raw_screencap(make_raw(img))
        self.assertGreater(int(out[0, 0, 0]), int(out[0, 0, 2]),
                           "B 通道应明显大于 R 通道（蓝底）")
        # 反向验证：故意用错转换会得到相反结果
        wrong = cv2.cvtColor(
            cv2.cvtColor(img, cv2.COLOR_BGR2RGBA), cv2.COLOR_BGRA2BGR)
        self.assertFalse(np.array_equal(wrong, img),
                         "错误转换应与正确结果不同（否则测试无意义）")

    def test_truncated_payload_raises(self):
        img = sample_bgr()
        bad = make_raw(img)[:-10]
        with self.assertRaises(DeviceError):
            ADBDevice.parse_raw_screencap(bad)

    def test_too_short_raises(self):
        with self.assertRaises(DeviceError):
            ADBDevice.parse_raw_screencap(b"\x00" * 5)

    def test_absurd_header_raises(self):
        buf = struct.pack("<III", 99999, 99999, 1) + b"\x00" * 64
        with self.assertRaises(DeviceError):
            ADBDevice.parse_raw_screencap(buf)


if __name__ == "__main__":
    unittest.main()
