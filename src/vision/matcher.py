"""模板匹配：用于识别固定按钮、图标、界面特征。

为什么用模板匹配而不是纯 OCR
--------------------------
游戏 UI 多为美术字体/图形按钮，OCR 对它们不稳定；而模板匹配在分辨率
固定（雷电锁定 1920x1080）时准确率极高、耗时极低（单次 ~5-20ms）。

鲁棒性措施
----------
* 多尺度搜索：应对模拟器轻微渲染差异
* TM_CCOEFF_NORMED：对亮度整体偏移不敏感
* NMS 去重：同一目标被多次命中时只保留最优
* **候选数上限（max_candidates）**：防止"低阈值 / 近似纯色模板"导致命中点爆炸
  （曾实测：threshold=0.0 + 1920x1080 会产生约 200 万候选点，随后 NMS 的
  O(n^2) 比较直接把进程吃爆，表现为「无异常栈的静默崩溃」。）
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import cv2
import numpy as np

from .annotate import read_image

DEFAULT_MAX_CANDIDATES = 256      # 单次单尺度匹配保留的最大候选点数


@dataclass
class MatchResult:
    """一次模板匹配结果。"""
    name: str
    score: float
    center: Tuple[int, int]
    box: Tuple[int, int, int, int]      # x1, y1, x2, y2
    scale: float = 1.0

    def __str__(self) -> str:  # pragma: no cover - 便于日志
        return f"<{self.name} score={self.score:.3f} at {self.center}>"


class TemplateMatcher:
    """模板库 + 匹配器。"""

    def __init__(self,
                 template_dir: Path,
                 threshold: float = 0.86,
                 multi_scale: Optional[Sequence[float]] = None,
                 nms_iou: float = 0.35,
                 logger: Optional[logging.Logger] = None,
                 max_candidates: int = DEFAULT_MAX_CANDIDATES) -> None:
        self.dir = Path(template_dir)
        self.threshold = threshold
        self.scales = list(multi_scale or [1.0])
        self.nms_iou = nms_iou
        self.max_candidates = max(1, int(max_candidates))
        self.log = logger or logging.getLogger("mjs.vision")
        self._cache: Dict[str, np.ndarray] = {}

    # ----------------------------------------------------------------- 加载
    def template_path(self, name: str) -> Path:
        """支持 ``"menu/start.png"`` 形式的子目录引用。"""
        p = Path(name)
        if p.suffix == "":
            p = p.with_suffix(".png")
        return self.dir / p

    def load(self, name: str) -> Optional[np.ndarray]:
        if name in self._cache:
            return self._cache[name]
        path = self.template_path(name)
        if not path.exists():
            self.log.debug("模板缺失: %s", path)
            return None
        img = read_image(path)          # 中文路径安全
        if img is None:
            self.log.warning("模板读取失败: %s", path)
            return None
        self._cache[name] = img
        return img

    def available(self) -> List[str]:
        """列出可用模板（忽略 ``_`` 开头的目录，如 ``_deprecated``）。"""
        if not self.dir.exists():
            return []
        out = []
        for p in self.dir.rglob("*.png"):
            rel = p.relative_to(self.dir)
            if any(part.startswith("_") for part in rel.parts[:-1]):
                continue
            out.append(str(rel).replace("\\", "/"))
        return sorted(out)

    def clear_cache(self) -> None:
        self._cache.clear()

    # ----------------------------------------------------------------- 匹配
    def _cv_match(self, screen: np.ndarray, tpl: np.ndarray,
                  threshold: float) -> List[Tuple[float, Tuple[int, int], Tuple[int, int]]]:
        """单尺度匹配，返回 [(score, (x,y), (w,h)), ...]。

        只保留**得分最高的前 max_candidates 个**候选点：
        低阈值或"近似纯色模板"会让几乎每个像素都超过阈值，若不设上限，
        候选点可达数百万，随后的 NMS 会耗尽内存与 CPU（静默崩溃）。
        """
        sh, sw = screen.shape[:2]
        th, tw = tpl.shape[:2]
        if th > sh or tw > sw:
            return []
        res = cv2.matchTemplate(screen, tpl, cv2.TM_CCOEFF_NORMED)
        # 常量模板会产生 NaN/Inf，先清洗，避免 argpartition 行为异常
        res = np.nan_to_num(res, nan=-1.0, posinf=1.0, neginf=-1.0)
        flat = res.ravel()
        k = min(self.max_candidates, flat.size)
        if k <= 0:
            return []
        # argpartition 取 top-k（O(n)），比全量 where 快得多且内存可控
        idx = np.argpartition(flat, -k)[-k:]
        grades = flat[idx]
        keep = grades >= threshold
        idx, grades = idx[keep], grades[keep]
        if idx.size == 0:
            return []
        order = np.argsort(-grades)              # 降序，NMS 需要最优在前
        idx, grades = idx[order], grades[order]
        w = res.shape[1]
        out: List[Tuple[float, Tuple[int, int], Tuple[int, int]]] = []
        for i, g in zip(idx.tolist(), grades.tolist()):
            y, x = divmod(int(i), w)
            out.append((float(g), (x, y), (tw, th)))
        return out

    @staticmethod
    def _iou(a: Tuple[int, int, int, int], b: Tuple[int, int, int, int]) -> float:
        ax1, ay1, ax2, ay2 = a
        bx1, by1, bx2, by2 = b
        ix1, iy1 = max(ax1, bx1), max(ay1, by1)
        ix2, iy2 = min(ax2, bx2), min(ay2, by2)
        iw, ih = max(0, ix2 - ix1), max(0, iy2 - iy1)
        inter = iw * ih
        if inter == 0:
            return 0.0
        area_a = (ax2 - ax1) * (ay2 - ay1)
        area_b = (bx2 - bx1) * (by2 - by1)
        return inter / float(area_a + area_b - inter)

    def match_all(self,
                  screen: np.ndarray,
                  name: str,
                  threshold: Optional[float] = None,
                  scales: Optional[Sequence[float]] = None,
                  region: Optional[Sequence[int]] = None) -> List[MatchResult]:
        """返回所有命中（已去重），按 score 降序。"""
        tpl = self.load(name)
        if tpl is None:
            return []
        thr = self.threshold if threshold is None else threshold
        use_scales = list(scales or self.scales)

        ox, oy = 0, 0
        canvas = screen
        if region is not None:
            x1, y1, x2, y2 = [int(v) for v in region]
            canvas = screen[y1:y2, x1:x2]
            ox, oy = x1, y1
        if canvas.size == 0:
            return []

        raw: List[Tuple[float, Tuple[int, int], Tuple[int, int]]] = []
        for s in use_scales:
            if abs(s - 1.0) < 1e-6:
                t = tpl
            else:
                interp = cv2.INTER_AREA if s < 1.0 else cv2.INTER_CUBIC
                t = cv2.resize(tpl, None, fx=s, fy=s, interpolation=interp)
            raw.extend(self._cv_match(canvas, t, thr))

        if not raw:
            return []

        # 按分数降序，逐个做 NMS
        raw.sort(key=lambda it: it[0], reverse=True)
        kept: List[MatchResult] = []
        for score, (x, y), (tw, th) in raw:
            box = (x + ox, y + oy, x + tw + ox, y + th + oy)
            if any(self._iou(box, k.box) > self.nms_iou for k in kept):
                continue
            center = (int((box[0] + box[2]) / 2), int((box[1] + box[3]) / 2))
            kept.append(MatchResult(name=name, score=score, center=center, box=box))
        return kept

    def match_best(self,
                   screen: np.ndarray,
                   name: str,
                   threshold: Optional[float] = None,
                   scales: Optional[Sequence[float]] = None,
                   region: Optional[Sequence[int]] = None) -> Optional[MatchResult]:
        """返回得分最高的命中；无命中返回 None。"""
        hits = self.match_all(screen, name, threshold, scales, region)
        return hits[0] if hits else None

    def exists(self,
               screen: np.ndarray,
               name: str,
               threshold: Optional[float] = None,
               region: Optional[Sequence[int]] = None) -> bool:
        return self.match_best(screen, name, threshold, None, region) is not None

    def any_exists(self,
                   screen: np.ndarray,
                   names: Sequence[str],
                   threshold: Optional[float] = None) -> Optional[MatchResult]:
        """在一组模板中返回首个命中（按给定顺序优先）。"""
        for n in names:
            hit = self.match_best(screen, n, threshold)
            if hit:
                return hit
        return None

    def best_of(self,
                screen: np.ndarray,
                names: Sequence[str],
                threshold: Optional[float] = None) -> Optional[MatchResult]:
        """在一组模板中返回得分最高的命中（不按顺序，按实际得分）。"""
        best: Optional[MatchResult] = None
        for n in names:
            hit = self.match_best(screen, n, threshold)
            if hit and (best is None or hit.score > best.score):
                best = hit
        return best
