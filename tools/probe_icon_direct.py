"""直接裁剪法：把节点下方的类型图标整块裁下来，当模板全屏匹配。

用法
----
python tools/probe_icon_direct.py <图> <模板图> [x1 y1 x2 y2] [阈值]

不带区域时用整张模板图；带区域时先在模板图上裁出该区域再匹配。
打印匹配峰值（去重后按分数降序）与峰间距。
"""
from __future__ import annotations

import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.vision.annotate import read_image, save  # noqa: E402


def nms_peaks(res: np.ndarray, thr: float, min_dist: int = 30, top: int = 12):
    ys, xs = np.where(res >= thr)
    if len(xs) == 0:
        return []
    order = np.argsort(-res[ys, xs])
    taken: list = []
    for i in order:
        x, y, s = int(xs[i]), int(ys[i]), float(res[ys[i], xs[i]])
        if all((x - tx) ** 2 + (y - ty) ** 2 >= min_dist ** 2 for tx, ty, _ in taken):
            taken.append((x, y, s))
        if len(taken) >= top:
            break
    return taken


def main() -> None:
    img_path = sys.argv[1]
    tpl_path = sys.argv[2]
    box = [int(v) for v in sys.argv[3:7]] if len(sys.argv) >= 7 else None
    thr = float(sys.argv[7]) if len(sys.argv) >= 8 else 0.55

    img = read_image(img_path)
    tpl = read_image(tpl_path)
    if box:
        tpl = tpl[box[1]:box[3], box[0]:box[2]]
    th, tw = tpl.shape[:2]
    res = cv2.matchTemplate(img, tpl, cv2.TM_CCOEFF_NORMED)
    peaks = nms_peaks(res, thr, min_dist=max(30, th // 2))
    print(f"模板 {tw}x{th}  阈值 {thr}  命中 {len(peaks)} 个")
    for i, (x, y, s) in enumerate(peaks, 1):
        cx, cy = x + tw // 2, y + th // 2
        print(f"  #{i} 左上({x:4d},{y:4d}) 中心({cx:4d},{cy:4d})  分数 {s:.3f}")

    # 可视化：标出峰值
    vis = img.copy()
    for x, y, s in peaks:
        cv2.rectangle(vis, (x, y), (x + tw, y + th), (0, 0, 255), 3)
        cv2.putText(vis, f"{s:.2f}", (x, max(20, y - 6)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2, cv2.LINE_AA)
    save(vis, Path("runtime/icon_probe.png"))
    print("可视化: runtime/icon_probe.png")


if __name__ == "__main__":
    main()
