"""截图采集工具 —— 标定界面坐标与制作模板素材。

用法示例
--------
# 连续抓 10 张（每 2 秒一张），带坐标网格，便于肉眼读坐标
python tools/capture.py --count 10 --interval 2 --grid --tag run_map

# 只抓一张，不带网格（用于裁剪模板）
python tools/capture.py --count 1 --tag buff_choice
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

# 允许以 `python tools/capture.py` 直接运行
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.common.utils import ensure_dir, now_stamp          # noqa: E402
from src.config import SCREENSHOTS_DIR, Config              # noqa: E402
from src.core.logger import setup_logger                    # noqa: E402
from src.devices.adb import ADBDevice                        # noqa: E402
from src.vision.annotate import draw_grid, save             # noqa: E402


def build_device(cfg: Config, log) -> ADBDevice:
    dev = ADBDevice(
        adb_path=cfg.adb_path,
        serial=cfg.serial,
        auto_connect=bool(cfg.get("device.auto_connect", True)),
        connect_host=cfg.get("device.connect_host", "127.0.0.1:5555"),
        cmd_timeout=float(cfg.get("device.cmd_timeout", 20)),
        logger=log,
    )
    dev.ensure_connected()
    return dev


def capture(cfg: Config, log, tag: str, count: int, interval: float,
            grid: bool, step: int, out_dir: Path) -> list[Path]:
    dev = build_device(cfg, log)
    ensure_dir(out_dir)
    saved: list[Path] = []
    for i in range(count):
        img = dev.screenshot()
        if grid:
            img = draw_grid(img, step=step)
        path = out_dir / f"{now_stamp()}_{tag}_{i:02d}.png"
        save(img, path)
        saved.append(path)
        log.info("已保存 [%d/%d] %s  (分辨率 %dx%d)",
                 i + 1, count, path.name, img.shape[1], img.shape[0])
        if i < count - 1:
            time.sleep(interval)
    return saved


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="名将杀自动化 · 截图采集")
    p.add_argument("--tag", default="shot", help="文件名标签，建议用界面名")
    p.add_argument("--count", type=int, default=1, help="抓取张数")
    p.add_argument("--interval", type=float, default=1.5, help="抓取间隔（秒）")
    p.add_argument("--grid", action="store_true", help="叠加坐标网格")
    p.add_argument("--step", type=int, default=100, help="网格间距（像素）")
    p.add_argument("--out", default=str(SCREENSHOTS_DIR), help="输出目录")
    args = p.parse_args(argv)

    log = setup_logger("mjs.capture")
    cfg = Config.load()
    out_dir = Path(args.out)
    paths = capture(cfg, log, args.tag, args.count, args.interval,
                    args.grid, args.step, out_dir)
    print("\n采集完成，共", len(paths), "张：")
    for pth in paths:
        print("  ", pth)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
