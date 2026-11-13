"""临时探针：逐个模板隔离测试，定位崩溃点。

用法:
    .venv/Scripts/python.exe -u tools/probe_scores.py <img> [img2 ...]
结果同时写入 runtime/probe.txt
"""
from __future__ import annotations

import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import cv2  # noqa: E402
import numpy as np  # noqa: E402

from src.vision.annotate import read_image  # noqa: E402
from src.vision.matcher import TemplateMatcher  # noqa: E402

OUT = Path("runtime/probe.txt")


def log(msg: str = "") -> None:
    print(msg, flush=True)
    with OUT.open("a", encoding="utf-8") as fh:
        fh.write(msg + "\n")


def main(paths):
    OUT.write_text("", encoding="utf-8")
    m = TemplateMatcher("assets/templates")
    tpls = m.available()
    log("模板共 %d 个: %s" % (len(tpls), tpls))

    for p in paths:
        log("=" * 70)
        img = read_image(p)
        if img is None:
            log("读取失败(可能中文路径): %s" % p)
            continue
        log("%s  %dx%d" % (p, img.shape[1], img.shape[0]))
        for t in tpls:
            log("  --> 即将匹配 %s" % t)          # 崩溃点会被这行标出
            try:
                h = m.match_best(img, t, threshold=0.0)
                log("      %-28s raw=%.3f  center=%s" %
                    (t, h.score if h else -1.0, h.center if h else "-"))
            except Exception:                     # noqa: BLE001
                log("      %-28s EXCEPTION" % t)
                log(traceback.format_exc())
    log("DONE")


if __name__ == "__main__":
    main(sys.argv[1:])
