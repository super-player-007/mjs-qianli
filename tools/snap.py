# -*- coding: utf-8 -*-
"""标定辅助：抓当前帧存成夹具 + 顺手打印关键区域的 OCR 文本。

用法
----
    .venv/Scripts/python.exe tools/snap.py map_layer1
    .venv/Scripts/python.exe tools/snap.py battle_live --region 1400 100 1920 500

存到 ``tests/fixtures/<name>.png``（覆盖同名），同时存一份到
``runtime/shots/snap_<name>.png`` 方便肉眼比对。
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.devices.adb import ADBDevice  # noqa: E402
from src.vision.annotate import read_image, save  # noqa: E402
from src.vision.ocr import OCREngine  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("name", help="夹具名（不带扩展名）")
    ap.add_argument("--region", nargs=4, type=int,
                    metavar=("X1", "Y1", "X2", "Y2"),
                    help="额外打印该区域的 OCR 文本")
    ap.add_argument("--no-ocr", action="store_true", help="不跑 OCR（更快）")
    args = ap.parse_args()

    dev = ADBDevice(os.environ.get("MJS_ADB", "adb"), "emulator-5554",
                    auto_connect=False)
    img = dev.screenshot()
    fx = ROOT / "tests/fixtures" / f"{args.name}.png"
    save(img, fx)
    save(img, ROOT / "runtime/shots" / f"snap_{args.name}.png")
    print(f"已存 {fx.name}  {img.shape[1]}x{img.shape[0]}")

    if not args.no_ocr:
        ocr = OCREngine(device="auto")
        region = tuple(args.region) if args.region else None
        items = ocr.read(img, region)
        print(f"--- OCR {region or '整屏'}：{len(items)} 条 ---")
        for it in items:
            x, y = it.center
            print(f"  ({x:4d},{y:4d}) 框{it.rect} {it.text}  {it.score:.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
