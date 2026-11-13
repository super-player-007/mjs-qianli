"""模板素材制作工具 —— 从截图中裁出按钮/图标，沉淀为可复用模板。

用法示例
--------
# 从指定截图裁出一个模板
python tools/make_template.py --src assets/screenshots/xxx.png \
       --box 780,980,1140,1050 --name battle_result/continue

# 交互式：先打网格图，量好坐标再裁
python tools/make_template.py --src assets/screenshots/xxx.png --grid-only
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import cv2                                                   # noqa: E402

from src.common.utils import ensure_dir                       # noqa: E402
from src.config import TEMPLATES_DIR                          # noqa: E402
from src.core.logger import setup_logger                      # noqa: E402
from src.vision.annotate import draw_grid, draw_region, save  # noqa: E402


def make_template(src: Path, box: list[int], name: str,
                  out_dir: Path, log) -> Path:
    """裁剪并保存模板。

    Parameters
    ----------
    box : [x1, y1, x2, y2] 基准分辨率下的像素坐标
    name: 模板名，支持子目录，如 ``battle_result/continue``
    """
    img = cv2.imread(str(src), cv2.IMREAD_COLOR)
    if img is None:
        raise FileNotFoundError(f"截图读取失败: {src}")
    h, w = img.shape[:2]
    x1, y1, x2, y2 = [int(v) for v in box]
    if not (0 <= x1 < x2 <= w and 0 <= y1 < y2 <= h):
        raise ValueError(f"裁剪框 {box} 超出图像范围 {w}x{h}")

    crop = img[y1:y2, x1:x2]
    if crop.size == 0:
        raise ValueError("裁剪结果为空")

    out_path = Path(out_dir) / (name if name.endswith(".png") else name + ".png")
    ensure_dir(out_path.parent)
    save(crop, out_path)
    log.info("模板已生成: %s  (%dx%d，来源 %s)",
             out_path, crop.shape[1], crop.shape[0], src.name)
    return out_path


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="名将杀自动化 · 模板制作")
    p.add_argument("--src", required=True, help="源截图路径")
    p.add_argument("--box", default="", help="裁剪框 x1,y1,x2,y2")
    p.add_argument("--name", default="", help="模板名（可含子目录）")
    p.add_argument("--out", default=str(TEMPLATES_DIR), help="模板输出目录")
    p.add_argument("--grid-only", action="store_true",
                   help="仅在截图上叠加网格并保存，方便量坐标")
    p.add_argument("--step", type=int, default=50, help="网格间距")
    args = p.parse_args(argv)

    log = setup_logger("mjs.template")
    src = Path(args.src)

    if args.grid_only:
        img = cv2.imread(str(src), cv2.IMREAD_COLOR)
        if img is None:
            raise FileNotFoundError(src)
        out = src.with_name(src.stem + "_grid.png")
        save(draw_grid(img, step=args.step), out)
        print("已生成网格图：", out)
        return 0

    if not args.box or not args.name:
        p.error("裁剪模式必须同时提供 --box 与 --name")

    box = [int(v) for v in args.box.split(",")]
    if len(box) != 4:
        p.error("--box 需要 4 个整数：x1,y1,x2,y2")

    # 先在原图上标出裁剪区域，便于复核
    img = cv2.imread(str(src), cv2.IMREAD_COLOR)
    if img is not None:
        preview = src.with_name(src.stem + "_crop_preview.png")
        save(draw_region(img, box, args.name), preview)
        print("裁剪预览：", preview)

    out_path = make_template(src, box, args.name, Path(args.out), log)
    print("模板已保存：", out_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
