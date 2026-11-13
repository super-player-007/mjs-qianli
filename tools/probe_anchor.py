"""临时探针：候选锚点的跨帧 / 跨页稳定性测试。

用法:
    .venv/Scripts/python.exe -u tools/probe_anchor.py <模板png> <图1> [图2 ...]
输出 runtime/anchor.txt

期望：在「本页各帧」上高分且稳定；在「其它页」上低分（< 阈值）。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import cv2  # noqa: E402

from src.vision.annotate import read_image  # noqa: E402

OUT = Path("runtime/anchor.txt")


def main(tpl_path, paths):
    OUT.write_text("", encoding="utf-8")

    def log(m=""):
        print(m, flush=True)
        with OUT.open("a", encoding="utf-8") as fh:
            fh.write(m + "\n")

    tpl = read_image(tpl_path)
    if tpl is None:
        raise SystemExit("模板读取失败: %s" % tpl_path)
    log("模板: %s  %dx%d" % (tpl_path, tpl.shape[1], tpl.shape[0]))
    for p in paths:
        img = read_image(p)
        if img is None:
            log("  读取失败: %s" % p)
            continue
        res = cv2.matchTemplate(img, tpl, cv2.TM_CCOEFF_NORMED)
        _, mx, _, mloc = cv2.minMaxLoc(res)
        log("  %-34s max=%.3f  at=%s" % (Path(p).name, mx, mloc))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2:])
