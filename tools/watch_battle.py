# -*- coding: utf-8 -*-
"""战斗中轮询：每 5 秒抓一帧，命中关键词就存成阶段截图。

用法：.venv/Scripts/python.exe tools/watch_battle.py
存到 runtime/shots/stage_<kind>.png（每个 kind 只存第一张）。
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.devices.adb import ADBDevice  # noqa: E402
from src.vision.annotate import save  # noqa: E402
from src.vision.ocr import OCREngine  # noqa: E402

RULES = [
    ("wansheng", ("完胜", "胜利")),
    ("settle", ("本局战绩", "领取奖励")),
    ("reward", ("恭喜获得",)),
    ("next_preview", ("下一步", "点击空白区域到下一步")),
]


def main() -> int:
    secs = int(sys.argv[1]) if len(sys.argv) > 1 else 180
    dev = ADBDevice(os.environ.get("MJS_ADB", "adb"), "emulator-5554",
                    auto_connect=False)
    ocr = OCREngine(device="auto")
    seen: set[str] = set()
    end = time.time() + secs
    i = 0
    while time.time() < end:
        i += 1
        img = dev.screenshot()
        texts = " ".join(it.text for it in ocr.read(img))
        hit = None
        for kind, kws in RULES:
            if kind not in seen and any(k in texts for k in kws):
                hit = kind
                break
        if hit:
            seen.add(hit)
            save(img, ROOT / "runtime/shots" / f"stage_{hit}.png")
            print(f"[{i}] {hit} 已存 | {texts[:60]}")
        else:
            print(f"[{i}] ...{texts[:50]}")
        if len(seen) >= len(RULES):
            break
        time.sleep(5)
    print("结束，抓到：", sorted(seen))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
