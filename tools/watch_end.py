# -*- coding: utf-8 -*-
"""等战斗结束（右上角「取消托管」消失），然后连拍结算阶段。

用法：.venv/Scripts/python.exe tools/watch_end.py [最长秒数]
存 runtime/shots/end_0..3.png
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

REGION = (1400, 100, 1920, 500)


def main() -> int:
    secs = int(sys.argv[1]) if len(sys.argv) > 1 else 300
    dev = ADBDevice(os.environ.get("MJS_ADB", "adb"), "emulator-5554",
                    auto_connect=False)
    ocr = OCREngine(device="auto")
    end = time.time() + secs
    i = 0
    while time.time() < end:
        i += 1
        img = dev.screenshot()
        texts = " ".join(it.text for it in ocr.read(img, REGION))
        if "取消托管" not in texts and "离开中" not in texts:
            print(f"[{i}] 托管 HUD 消失，开始连拍")
            for k in range(4):
                save(img if k == 0 else dev.screenshot(),
                     ROOT / "runtime/shots" / f"end_{k}.png")
                full = " ".join(it.text for it in ocr.read(img)) \
                    if k == 0 else ""
                print(f"  end_{k}.png  {full[:70]}")
                time.sleep(2.0)
            return 0
        if i % 5 == 0:
            print(f"[{i}] 还在打… {texts[:40]}")
        time.sleep(4)
    print("超时未结束")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
