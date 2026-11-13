"""临时探针：分析战役页的动静元素，寻找稳定锚点。

用法:
    .venv/Scripts/python.exe -u tools/probe_motion.py <tag> <frames...>
输出 runtime/probe.txt
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import cv2  # noqa: E402

from src.vision.annotate import read_image  # noqa: E402
import numpy as np  # noqa: E402

from src.vision.ocr import OCREngine  # noqa: E402

OUT = Path("runtime/probe.txt")


def log(msg: str = "") -> None:
    print(msg, flush=True)
    with OUT.open("a", encoding="utf-8") as fh:
        fh.write(msg + "\n")


def main(tag, paths):
    OUT.write_text("", encoding="utf-8")
    imgs = []
    for p in paths:
        im = read_image(p)
        if im is None:
            log("读取失败: %s" % p)
            continue
        imgs.append((Path(p).name, im))
    if not imgs:
        return

    base_name, base = imgs[0]
    log("基准: %s   共 %d 帧" % (base_name, len(imgs)))

    # ---- 1) 逐帧差异：定位哪些区域在动 ----
    for name, im in imgs[1:]:
        d = cv2.absdiff(base, im)
        g = cv2.cvtColor(d, cv2.COLOR_BGR2GRAY)
        # 按 120x120 网格统计差异均值
        H, W = g.shape
        bs = 120
        hot = []
        for y in range(0, H - bs + 1, bs):
            for x in range(0, W - bs + 1, bs):
                v = float(g[y:y + bs, x:x + bs].mean())
                if v > 8.0:
                    hot.append((v, x, y))
        hot.sort(reverse=True)
        log("  %s vs %s : 差异>8 的区块 %d 个，最热 %s"
            % (base_name, name, len(hot),
               ", ".join("(%d,%d)=%.0f" % (x, y, v) for v, x, y in hot[:6])))

    # ---- 2) OCR：列出文字元素及其跨帧位置漂移 ----
    ocr = OCREngine(min_score=0.5)
    per = []
    for name, im in imgs:
        items = {it.text: it.center for it in ocr.read(im)}
        per.append((name, items))
    log("-" * 70)
    log("文字元素跨帧位置漂移（像素）：")
    keys = set(per[0][1])
    for k in sorted(keys):
        xs = [d[k] for _, d in per if k in d]
        if len(xs) < 2:
            continue
        dx = max(p[0] for p in xs) - min(p[0] for p in xs)
        dy = max(p[1] for p in xs) - min(p[1] for p in xs)
        flag = "  <== 静止" if max(dx, dy) <= 2 else ("  <== 漂移" if max(dx, dy) > 6 else "")
        log("   %-16s 出现%2d/%d帧  dx=%3d dy=%3d%s"
            % (k, len(xs), len(per), dx, dy, flag))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2:])
