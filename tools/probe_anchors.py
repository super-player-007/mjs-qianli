# -*- coding: utf-8 -*-
"""锚点体检：给一张截图，逐条目打印匹配分数与是否通过（标定用）。

用法
----
    .venv/Scripts/python.exe tools/probe_anchors.py runtime/shots/now.png
    .venv/Scripts/python.exe tools/probe_anchors.py --live          # 现抓一帧
    .venv/Scripts/python.exe tools/probe_anchors.py --live --in-run # 局内（默认局外）

输出每行：state / 区域 / 模板尺寸 / 最高分 / 阈值 / 结论（OK / LOW）。
「游戏更新后哪些页认不出来了」用它一眼定位。
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import cv2  # noqa: E402
import numpy as np  # noqa: E402

from src.game import anchor_table  # noqa: E402
from src.vision.annotate import read_image  # noqa: E402


def grab_live() -> np.ndarray:
    from src.devices.adb import ADBDevice
    d = ADBDevice(os.environ.get("MJS_ADB", "adb"), "emulator-5554",
                  auto_connect=False)
    return d.screenshot()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("image", nargs="?", help="截图路径（缺省用 --live）")
    ap.add_argument("--live", action="store_true", help="现抓一帧")
    ap.add_argument("--in-run", action="store_true", help="按局内范围匹配")
    args = ap.parse_args()

    if args.live or not args.image:
        img = grab_live()
    else:
        img = read_image(Path(args.image))
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    table = anchor_table.load_anchor_table()

    print(f"图像 {img.shape[1]}x{img.shape[0]} | 条目 {len(table)} | "
          f"in_run={args.in_run}")
    hit = anchor_table.match_entry(gray, table, in_run=args.in_run)
    print(f"判页结果: {hit.state if hit else None}\n")

    print(f"{'state':18s} {'scope':8s} {'模板':10s} {'最高分':>7s} "
          f"{'阈值':>5s}  结论")
    for e in table:
        if e.scope == "in_run" and not args.in_run:
            continue
        for a in e.areas:
            x1, y1, x2, y2 = a.rect
            h, w = a.tpl_gray.shape[:2]
            region = gray[y1:y2, x1:x2]
            if region.size == 0 or region.shape[0] < h or region.shape[1] < w:
                print(f"{e.state:18s} {e.scope:8s} {w}x{h:<6d} {'-':>7s} "
                      f"{a.threshold:5.2f}  区域过小")
                continue
            score = float(cv2.matchTemplate(
                region, a.tpl_gray, cv2.TM_CCOEFF_NORMED).max())
            verdict = "OK" if score >= a.threshold else \
                ("接近" if score >= a.threshold - 0.15 else "LOW")
            print(f"{e.state:18s} {e.scope:8s} {w}x{h:<6d} {score:7.3f} "
                  f"{a.threshold:5.2f}  {verdict}  区域{a.rect}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
