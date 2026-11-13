"""日志：同时输出到控制台与文件，并支持"关键节点/异常"截图归档。"""
from __future__ import annotations

import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

_FMT = "%(asctime)s [%(levelname)s] %(name)s | %(message)s"
_DATEFMT = "%H:%M:%S"

_configured: dict[str, logging.Logger] = {}


def setup_logger(name: str = "mjs",
                 log_dir: Optional[Path] = None,
                 level: int = logging.INFO,
                 to_console: bool = True) -> logging.Logger:
    """创建（或复用）一个 logger。

    Parameters
    ----------
    log_dir : 若提供，则额外写入 ``<log_dir>/run_YYYYmmdd_HHMMSS.log``。

    Notes
    -----
    重配置时**只重建控制台/文件 handler**，带 ``_persistent = True`` 标记的
    handler（如 GUI 日志队列桥）原样保留——2026-10-10 事故：clear() 把 GUI
    队列桥一起清掉，导致 GUI 进程第一次点启动时界面运行日志空白
    （第二次起 configured 短路不再 clear，反而正常）。
    """
    logger = logging.getLogger(name)
    logger.setLevel(level)
    logger.propagate = False
    # 重建 console/file，保留持久 handler；被移除的 FileHandler 显式关闭防句柄泄漏
    kept, removed = [], []
    for h in logger.handlers:
        (kept if getattr(h, "_persistent", False) else removed).append(h)
    for h in removed:
        h.close()
    logger.handlers = kept

    formatter = logging.Formatter(_FMT, datefmt=_DATEFMT)

    if to_console:
        # Windows 控制台默认 GBK，强制 UTF-8 避免中文乱码
        try:
            sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
        except Exception:
            pass
        already = any(isinstance(h, logging.StreamHandler)
                      and not isinstance(h, logging.FileHandler)
                      for h in logger.handlers)
        if not already:                     # 重配置时不重复挂控制台
            sh = logging.StreamHandler(sys.stdout)
            sh.setFormatter(formatter)
            logger.addHandler(sh)

    if log_dir is not None:
        log_dir = Path(log_dir)
        log_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        fh = logging.FileHandler(log_dir / f"run_{stamp}.log", encoding="utf-8")
        fh.setFormatter(formatter)
        logger.addHandler(fh)

    _configured[name] = logger
    return logger


def get_logger(name: str = "mjs") -> logging.Logger:
    return _configured.get(name) or setup_logger(name)
