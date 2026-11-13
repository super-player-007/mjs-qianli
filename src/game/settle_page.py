"""结算链状态快速识别：模板匹配替代整屏 OCR（2026-10-09 新增）。

## 背景

结算链（victory_blank → next_preview → settle_confirm → run_settle →
reward_overlay）每场战斗连走 4-6 步，每步整屏 OCR ~1.9s 纯为分类。
这些状态的**锚点都是外观固定的美术元素**（金按钮/标题），模板匹配
单页 ~0.13s（4 模板连扫），快 ~15 倍。

## 歧义处理（实测 0.994 互配）

「下一步」与「领取奖励」是几乎同款的金色按钮（同位置、同底色），
灰度模板互相匹配 0.994——阈值分不开。解法：两模板同时命中时，
对按钮文字区 (850,915,1070,995) 做**小范围 OCR**（~0.3s，仍比整屏快
6 倍），读「下一步」→ next_preview，读「领取奖励」→ run_settle。

## 误报防线（实测语料）

地图页/战斗页/任务页全部无命中（阈值 0.9）；battle_target_select
的「确定」按钮与「确认」金按钮外观不同（有测试锁定）。
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable, Dict, Optional

import cv2
import numpy as np

#: 结算模板目录
SETTLE_TEMPLATE_DIR = Path("assets/templates/settle")

#: 匹配阈值（实测自页 1.0，跨页/干扰页 <0.9）
SETTLE_MATCH_THRESHOLD = 0.9
#: 金按钮文字区（下一步/领取奖励 二选一消歧用）
BUTTON_TEXT_REGION = (850, 915, 1070, 995)

#: 模板名 → 状态名（本模块模板与状态一一对应）
TEMPLATE_STATES = ("next_preview", "settle_confirm", "run_settle",
                   "reward_overlay")


def load_settle_templates(tpl_dir: Optional[Path] = None) -> Dict[str, np.ndarray]:
    """加载结算模板。

    同一状态存在多种美术外观时用变体文件 ``{状态}_变体.png``
    （如 next_preview_wansheng.png=完胜预览页的下一步按钮），
    match_state 返回时剥掉变体后缀归入基础状态。
    """
    d = Path(tpl_dir or SETTLE_TEMPLATE_DIR)
    out: Dict[str, np.ndarray] = {}
    for name in TEMPLATE_STATES:
        files = [d / f"{name}.png"]
        files += sorted(d.glob(f"{name}_*.png"))
        for p in files:
            img = None
            if p.exists():
                img = cv2.imdecode(np.fromfile(str(p), dtype=np.uint8),
                                   cv2.IMREAD_COLOR)
            if img is not None:
                key = name if p.stem == name else f"{name}#{p.stem}"
                out[key] = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    return out


def _best_scores(page_gray: np.ndarray,
                 templates: Dict[str, np.ndarray]) -> Dict[str, float]:
    out: Dict[str, float] = {}
    for name, tpl in templates.items():
        h, w = tpl.shape[:2]
        if h >= page_gray.shape[0] or w >= page_gray.shape[1]:
            continue
        res = cv2.matchTemplate(page_gray, tpl, cv2.TM_CCOEFF_NORMED)
        out[name] = float(res.max())
    return out


def match_state(img: np.ndarray,
                templates: Dict[str, np.ndarray],
                threshold: float = SETTLE_MATCH_THRESHOLD,
                ocr_fn: Optional[Callable] = None) -> Optional[str]:
    """识别结算链状态；非结算页返回 None（走原有 OCR 分类）。

    ``ocr_fn``：``callable(img, region=None) -> items``，仅金按钮二选一
    消歧时调用（小范围 OCR）。未提供则取最高分。
    """
    if not isinstance(img, np.ndarray) or img.size == 0 or not templates:
        return None
    page = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    scores = _best_scores(page, templates)
    # 变体模板键（状态#变体名）归并到基础状态，各取最高分
    base: Dict[str, float] = {}
    for k, s in scores.items():
        b = k.split("#")[0]
        base[b] = max(base.get(b, 0.0), s)
    hits = {k: s for k, s in base.items() if s >= threshold}
    if not hits:
        return None
    if len(hits) == 1:
        return next(iter(hits))
    # 多命中：金按钮二选一（next_preview/run_settle 同款按钮）
    if hits.get("next_preview") is not None and hits.get("run_settle") is not None \
            and ocr_fn is not None:
        x1, y1, x2, y2 = BUTTON_TEXT_REGION
        region_img = img[y1:y2, x1:x2]
        texts = [str(getattr(it, "text", ""))
                 for it in ocr_fn(region_img) or []]
        joined = "".join(texts)
        if "领取奖励" in joined:
            return "run_settle"
        if "下一步" in joined:
            return "next_preview"
    return max(hits, key=hits.get)          # 兜底：最高分
