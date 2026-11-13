"""任务页按钮识别：模板匹配「领取奖励」「刷新」按钮（2026-10-07 新增）。

为什么用模板匹配而不是 OCR
--------------------------
任务页按钮是**外观固定的美术横幅**（领取奖励=金色、刷新×1=蓝色），
模板匹配单次 ~40ms，整屏 OCR ~2s——快 50 倍，且不受按钮文字识别
波动影响。按钮在 2×3 槽位的位置固定，模板直接从真实任务页截图裁剪
（assets/templates/task/btn_claim.png / btn_refresh.png）。

匹配细节
--------
* ``TM_CCOEFF_NORMED`` 灰度匹配，阈值 0.75（实测正确按钮 0.99+，
  跨按钮误配 <0.75——领取奖励(金)/刷新(蓝) 颜色差异大）
* 多目标：``np.where`` 候选按分数排序 + 最小距离 NMS
  （⚠ 候选上限 200——低阈值海选 NMS O(n²) 曾打爆内存，见 matcher 教训）
* 中心点 = 模板框中心，即按钮可点击区域
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np

#: 按钮模板目录
TASK_TEMPLATE_DIR = Path("assets/templates/task")

#: 匹配阈值（实测：正确按钮 ≥0.99，跨按钮误配 ≤0.75）
TASK_MATCH_THRESHOLD = 0.75
#: 同类按钮最小间距（NMS 去重）
TASK_MIN_DIST = 80
#: 候选上限（防低阈值海选打爆内存）
_MAX_CANDIDATES = 200
#: 单页最多按钮数（6 槽位 + 余量）
_MAX_BUTTONS = 6


@dataclass
class TaskButton:
    """任务页一个可点按钮。"""

    kind: str          # "claim" | "refresh"
    cx: int
    cy: int
    score: float

    @property
    def pos(self) -> Tuple[int, int]:
        return self.cx, self.cy


def load_task_templates(tpl_dir: Optional[Path] = None) -> Dict[str, np.ndarray]:
    """加载任务页按钮模板（btn_claim.png / btn_refresh.png）。

    ⚠ btn_claim2.png（任务面板「领取」徽章变体）不进本池——它外观大众脸
    （0.75 阈值下全页数百候选），会挤占 NMS 槽位导致刷新按钮漏检。
    仅由 runner._claim_task_badges 以 0.9 阈值独立使用（2026-10-23）。
    """
    d = Path(tpl_dir or TASK_TEMPLATE_DIR)
    out: Dict[str, np.ndarray] = {}
    for key, name in (("claim", "btn_claim.png"), ("refresh", "btn_refresh.png")):
        p = d / name
        img = None
        if p.exists():
            img = cv2.imdecode(np.fromfile(str(p), dtype=np.uint8),
                               cv2.IMREAD_COLOR)
        if img is not None:
            out[key] = img
    return out


def _gray(img: np.ndarray) -> np.ndarray:
    return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)


def find_buttons(img: np.ndarray,
                 templates: Optional[Dict[str, np.ndarray]] = None,
                 tpl_dir: Optional[Path] = None,
                 threshold: float = TASK_MATCH_THRESHOLD,
                 ) -> List[TaskButton]:
    """在任务页截图里找出全部「领取奖励」「刷新」按钮（含 NMS 去重）。

    按分数降序返回（先点最像的）。
    """
    if templates is None:
        templates = load_task_templates(tpl_dir)
    if img is None or img.size == 0 or not templates:
        return []
    page = _gray(img)
    found: List[Tuple[int, int, float, str]] = []
    for kind, tpl in templates.items():
        tg = _gray(tpl)
        h, w = tg.shape[:2]
        if h >= page.shape[0] or w >= page.shape[1]:
            continue
        res = cv2.matchTemplate(page, tg, cv2.TM_CCOEFF_NORMED)
        ys, xs = np.where(res >= threshold)
        pts = sorted(zip(xs.tolist(), ys.tolist(), res[ys, xs].tolist()),
                     key=lambda p: -p[2])[:_MAX_CANDIDATES]
        for x, y, s in pts:
            if any(abs(x - ox) < TASK_MIN_DIST and abs(y - oy) < TASK_MIN_DIST
                   for ox, oy, _, k in found):
                continue                      # 已有更高分按钮占据此槽位
            found.append((x, y, s, kind))
            if len(found) >= _MAX_BUTTONS:
                break
        if len(found) >= _MAX_BUTTONS:
            break
    # 按分数降序输出，坐标换算为模板中心
    found.sort(key=lambda t: -t[2])
    return [TaskButton(kind=k, cx=x + w // 2, cy=y + h // 2, score=s)
            for x, y, s, k in found
            for w, h in [(templates[k].shape[1], templates[k].shape[0])]]
