"""打印截图中的全部 OCR 文本与绝对坐标（标定用，不改动游戏）。

用法:
    .venv/Scripts/python.exe -u tools/probe_text.py [图片] [x1 y1 x2 y2]

例:
    .venv/Scripts/python.exe -u tools/probe_text.py runtime/shots/_cur.png
    .venv/Scripts/python.exe -u tools/probe_text.py runtime/shots/_cur.png 1440 180 1830 980

输出按「行」粗排（y 容差 20px），方便对照右侧/下方的元素量坐标。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.config import Config                      # noqa: E402
from src.core.logger import setup_logger           # noqa: E402
from src.vision.annotate import read_image         # noqa: E402
from src.vision.ocr import OCREngine               # noqa: E402


def main() -> int:
    args = sys.argv[1:]
    path = args[0] if args else "runtime/shots/_cur.png"
    region = [int(v) for v in args[1:5]] if len(args) >= 5 else None

    cfg = Config.load()
    log = setup_logger("mjs", cfg.log_dir)
    ocr = OCREngine(
        engine=cfg.get("ocr.engine", "rapidocr"),
        min_score=float(cfg.get("ocr.min_score", 0.5)),
        normalize=bool(cfg.get("ocr.normalize", True)),
        logger=log,
    )
    img = read_image(path)
    if img is None:
        raise SystemExit("读取失败: %s" % path)

    print("图像: %s  %dx%d  region=%s" % (path, img.shape[1], img.shape[0], region))
    print("-" * 84)
    items = ocr.read(img, region)
    for it in sorted(items, key=lambda i: (i.rect[1] // 20, i.rect[0])):
        x1, y1, x2, y2 = it.rect
        print("  %-16s conf=%.2f box=(%4d,%4d)-(%4d,%4d) center=(%4d,%4d)"
              % (it.text, it.score, x1, y1, x2, y2, (x1 + x2) // 2, (y1 + y2) // 2))
    print("-" * 84)
    print("共 %d 条" % len(items))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
