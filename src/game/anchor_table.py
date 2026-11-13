# -*- coding: utf-8 -*-
"""锚点表（阶段 1 试点，2026-11-11）：数据驱动的页面快速分类。

对标 OneDragon screen_info：每个状态一条锚点 = 一个或多个「固定搜索区域
+ 区域内模板匹配」（多区域 AND，防同按钮页面误判）。已知页面 0.1-0.3s
完成分类，整屏 OCR 只做兜底。

yml 结构（assets/screen_info/anchors.yml）：
- state: map                # 状态名（与 runner classify 一致）
  scope: in_run             # in_run=局内才匹配 / global=总是匹配
  needs_ocr: false          # true=命中后仍需 OCR 提供动作参数
  ocr_region: [x1,y1,x2,y2] # needs_ocr 时的 OCR 区域（省略=整屏）
  areas:                    # 多区域 AND：全部命中才算该页面
    - anchor: map.png       # 锚点模板（assets/templates/anchors/ 下）
      rect: [x1, y1, x2, y2]
      threshold: 0.9
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

import cv2
import numpy as np
import yaml

ANCHOR_TABLE_FILE = Path("assets/screen_info/anchors.yml")
ANCHOR_TEMPLATE_DIR = Path("assets/templates/anchors")


@dataclass
class AnchorArea:
    rect: tuple
    threshold: float
    tpl_gray: np.ndarray


@dataclass
class AnchorEntry:
    state: str
    scope: str
    needs_ocr: bool
    areas: list               # List[AnchorArea]，多区域 AND
    ocr_region: Optional[tuple] = None   # needs_ocr 时的 OCR 区域（None=整屏）


def _read_gray_from(img: Optional[np.ndarray]):
    return None if img is None else cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)


def _load_area_tpl(path: Path) -> Optional[np.ndarray]:
    """读锚点模板，返回灰度；模板缺失返回 None。"""
    img = None
    if path.exists():
        img = cv2.imdecode(np.fromfile(str(path), dtype=np.uint8),
                           cv2.IMREAD_COLOR)
    return _read_gray_from(img)


def load_anchor_table(yml_path: Optional[Path] = None,
                      tpl_dir: Optional[Path] = None) -> List[AnchorEntry]:
    """加载锚点表（模板缺失的条目整体跳过）。"""
    p = Path(yml_path or ANCHOR_TABLE_FILE)
    d = Path(tpl_dir or ANCHOR_TEMPLATE_DIR)
    out: List[AnchorEntry] = []
    if not p.exists():
        return out
    for item in yaml.safe_load(p.read_text(encoding="utf-8")) or []:
        areas = []
        for a in item.get("areas", []):
            tg = _load_area_tpl(d / a["anchor"])
            if tg is None:
                continue           # 单个锚点文件缺失 → 该条目失效
            areas.append(AnchorArea(rect=tuple(a["rect"]),
                                    threshold=a.get("threshold", 0.9),
                                    tpl_gray=tg))
        if areas:
            reg = item.get("ocr_region")
            out.append(AnchorEntry(
                state=item["state"], scope=item.get("scope", "global"),
                needs_ocr=bool(item.get("needs_ocr", False)), areas=areas,
                ocr_region=tuple(reg) if reg else None))
    return out


def match_entry(page_gray: np.ndarray, table: List[AnchorEntry],
                in_run: bool = False) -> Optional[AnchorEntry]:
    """按锚点表匹配页面：区域内 matchTemplate，多区域 AND，首个全中即返回。

    scope 剪枝：in_run=False 时只匹配 global 条目（局外不扫局内锚点）。
    """
    if page_gray is None or page_gray.ndim != 2 or not table:
        return None
    for e in table:
        if e.scope == "in_run" and not in_run:
            continue
        ok = True
        for a in e.areas:                 # 多区域 AND：全中才算
            x1, y1, x2, y2 = a.rect
            x2, y2 = min(x2, page_gray.shape[1]), min(y2, page_gray.shape[0])
            region = page_gray[y1:y2, x1:x2]
            if region.shape[0] < a.tpl_gray.shape[0] or \
                    region.shape[1] < a.tpl_gray.shape[1]:
                ok = False
                break
            s = float(cv2.matchTemplate(region, a.tpl_gray,
                                        cv2.TM_CCOEFF_NORMED).max())
            if s < a.threshold:
                ok = False
                break
        if ok:
            return e
    return None
