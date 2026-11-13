"""通用小工具：随机节奏、坐标缩放、时间戳。"""
from __future__ import annotations

import random
import time
from datetime import datetime
from pathlib import Path
from typing import List, Sequence, Tuple


# ---------------------------------------------------------------- 人工节奏
def rand_delay(rng: Sequence[float]) -> float:
    """在 [min, max] 区间内取随机等待并 sleep，返回实际秒数。

    模拟人工操作的关键：避免固定节奏被识别为脚本。
    """
    lo, hi = float(rng[0]), float(rng[1])
    if hi < lo:
        lo, hi = hi, lo
    secs = random.uniform(lo, hi)
    time.sleep(secs)
    return secs


def jitter(value: float, ratio: float = 0.1) -> float:
    """给数值加上 ±ratio 的随机抖动。"""
    delta = value * ratio
    return value + random.uniform(-delta, delta)


# ------------------------------------------------------------------ 坐标系
def scale_point(point: Sequence[float],
                base: Tuple[int, int],
                actual: Tuple[int, int]) -> Tuple[int, int]:
    """基准分辨率坐标 -> 实际分辨率坐标。"""
    sx = actual[0] / base[0]
    sy = actual[1] / base[1]
    return int(round(point[0] * sx)), int(round(point[1] * sy))


def scale_box(box: Sequence[float],
              base: Tuple[int, int],
              actual: Tuple[int, int]) -> List[int]:
    """基准分辨率矩形 -> 实际分辨率矩形。"""
    x1, y1 = scale_point((box[0], box[1]), base, actual)
    x2, y2 = scale_point((box[2], box[3]), base, actual)
    return [x1, y1, x2, y2]


def offset_point(point: Sequence[float], ox: float, oy: float) -> Tuple[int, int]:
    """给点加偏移（用于把"区域"内的相对坐标转换为屏幕绝对坐标）。"""
    return int(round(point[0] + ox)), int(round(point[1] + oy))


def clamp(value: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, value))


# -------------------------------------------------------------------- 其它
def ensure_dir(path: Path) -> Path:
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)
    return path


def now_stamp(fmt: str = "%Y%m%d_%H%M%S") -> str:
    return datetime.now().strftime(fmt)


def human_secs(seconds: float) -> str:
    seconds = int(max(0, seconds))
    m, s = divmod(seconds, 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h}h{m}m{s}s"
    if m:
        return f"{m}m{s}s"
    return f"{s}s"
