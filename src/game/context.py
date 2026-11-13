"""运行上下文：把设备、视觉、决策等能力打包，供各界面处理器调用。"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional

import numpy as np

from ..config import Config
from ..core.asker import Asker
from ..devices.adb import ADBDevice
from ..vision.matcher import TemplateMatcher
from ..vision.ocr import OCREngine


@dataclass
class Frame:
    """一帧屏幕画面及其元信息。"""
    image: np.ndarray
    index: int
    ts: float
    path: Optional[Path] = None

    @property
    def size(self):
        return self.image.shape[1], self.image.shape[0]


@dataclass
class GameContext:
    """全局运行上下文。"""
    cfg: Config
    device: ADBDevice
    matcher: TemplateMatcher
    ocr: OCREngine
    asker: Asker
    log: logging.Logger
    # 运行期可变状态（如：是否已进入对局、累计里程等）
    state: Dict[str, Any] = field(default_factory=dict)

    # ------------------------------------------------------------ 便捷封装
    def tap_point(self, point, jitter: bool = True) -> None:
        """点击一个 (x, y)（实际分辨率）。"""
        if point is None:
            raise ValueError("tap_point 收到空坐标")
        x, y = int(point[0]), int(point[1])
        self.device.tap(x, y, jitter_px=2 if jitter else 0)

    def tap_element(self, screen: str, element: str) -> bool:
        """按下述约定点击某个界面元素：
        1) 坐标表里直接有该元素的点 -> 直接点
        2) 坐标表里只有区域 -> 在该区域内做模板匹配，命中则点匹配中心
        3) 都没有 -> 记录告警并返回 False
        """
        from ..common.utils import scale_point

        base = self.cfg.base_size
        actual = self.device.size

        pt = self.cfg.point(screen, element)
        tpl_name = None
        el = self.cfg.element(screen, element)
        if el:
            tpl_name = el.get("template")

        # 优先模板匹配（更抗 UI 微调）
        if tpl_name:
            hit = self.matcher.match_best(
                self._last_frame.image if getattr(self, "_last_frame", None) else
                self.device.screenshot(),
                tpl_name,
                region=None)
            if hit:
                self.tap_point(hit.center)
                return True

        if pt:
            sx, sy = scale_point(pt, base, actual)
            self.tap_point((sx, sy))
            return True
        self.log.warning("坐标表中缺少元素: %s.%s", screen, element)
        return False

    def mark(self, key: str, value: Any) -> None:
        self.state[key] = value

    # ------------------------------------------------------------ OCR 缓存
    def ocr_items(self, frame: "Frame", region=None):
        """按帧缓存 OCR 结果：同一帧、同一区域只识别一次。

        性能关键——多个界面判定各自跑一次全屏 OCR 时，实测一轮耗时从
        3.5s 涨到 14s。缓存挂在 frame 对象上，帧一换自动失效。
        """
        cache: dict = frame.__dict__.setdefault("_ocr_cache", {})
        key = tuple(int(v) for v in region) if region else None
        if key not in cache:
            cache[key] = self.ocr.read(frame.image, region)
        return cache[key]

    def ocr_texts(self, frame: "Frame", region=None):
        """取该帧识别到的全部文本（便于关键词投票）。"""
        return [it.text for it in self.ocr_items(frame, region)]

    def get_state(self, key: str, default: Any = None) -> Any:
        return self.state.get(key, default)

    def elapsed(self) -> float:
        return time.time() - self.get_state("t_start", time.time())
