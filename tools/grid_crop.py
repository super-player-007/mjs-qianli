"""局部放大 + 绝对坐标网格，用于人工读坐标（标定主力工具）。

用法:
    .venv/Scripts/python.exe -u tools/grid_crop.py <图> <x1> <y1> <x2> <y2> [放大倍数] [网格步长]

例:
    .venv/Scripts/python.exe -u tools/grid_crop.py assets/screenshots/camp_f0.png 0 0 400 200 3 20

输出: assets/screenshots/grid_<图名>_<x1>_<y1>.png
网格线为绝对坐标（不是裁剪后的相对坐标），红=整百、橙=步长。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import cv2  # noqa: E402

from src.vision.annotate import read_image, save  # noqa: E402


def grid_crop(path: str, x1: int, y1: int, x2: int, y2: int,
              scale: float = 3.0, step: int = 20) -> Path:
    img = read_image(path)
    if img is None:
        raise SystemExit("读取失败: %s" % path)
    h, w = img.shape[:2]
    x1, y1 = max(0, x1), max(0, y1)
    x2, y2 = min(w, x2), min(h, y2)
    c = img[y1:y2, x1:x2].copy()

    for x in range(0, c.shape[1], step):
        ax = x1 + x
        red = (ax % 100 == 0)
        cv2.line(c, (x, 0), (x, c.shape[0]), (0, 0, 255) if red else (0, 170, 255), 1)
        if red:
            cv2.putText(c, str(ax), (x + 2, 13), cv2.FONT_HERSHEY_SIMPLEX,
                        0.36, (0, 0, 255), 1, cv2.LINE_AA)
    for y in range(0, c.shape[0], step):
        ay = y1 + y
        red = (ay % 100 == 0)
        cv2.line(c, (0, y), (c.shape[1], y), (0, 0, 255) if red else (0, 170, 255), 1)
        if red:
            cv2.putText(c, str(ay), (2, y + 13), cv2.FONT_HERSHEY_SIMPLEX,
                        0.36, (0, 0, 255), 1, cv2.LINE_AA)

    big = cv2.resize(c, None, fx=scale, fy=scale, interpolation=cv2.INTER_NEAREST)
    out = Path("assets/screenshots") / f"grid_{Path(path).stem}_{x1}_{y1}.png"
    save(big, out)
    print("已保存: %s   (裁剪 %dx%d @(%d,%d) 放大 %.1fx)"
          % (out, c.shape[1], c.shape[0], x1, y1, scale))
    return out


if __name__ == "__main__":
    a = sys.argv[1:]
    if len(a) < 5:
        raise SystemExit(__doc__)
    sc = float(a[5]) if len(a) > 5 else 3.0
    st = int(a[6]) if len(a) > 6 else 20
    grid_crop(a[0], int(a[1]), int(a[2]), int(a[3]), int(a[4]), sc, st)
