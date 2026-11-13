"""游戏邀请弹窗处理（2026-10-11 用户需求：偶尔弹出，模板匹配点「忽略」）。

弹窗可能出现在**任何界面之上**（战斗/地图/结算……），因此在 step() 的
所有状态识别之前做前置检查；托管等待的局部轮询里也顺带检查（弹窗不影响
托管战斗本身，但要即时关掉避免遮挡后续点击）。

识别：模板匹配「忽略」按钮（青色横幅金text，从用户真实截图裁剪，
assets/templates/invite/btn_ignore.png）。阈值 0.8——弹窗样式固定，
干扰页实测无命中。点中的位置即按钮中心（整按钮可点）。
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, Optional, Tuple

import cv2
import numpy as np

#: 邀请弹窗模板目录
INVITE_TEMPLATE_DIR = Path("assets/templates/invite")

#: 匹配阈值（弹窗样式固定，自页 1.0）
INVITE_MATCH_THRESHOLD = 0.8


def load_invite_templates(tpl_dir: Optional[Path] = None) -> Dict[str, np.ndarray]:
    """加载邀请弹窗模板（btn_ignore.png）。"""
    d = Path(tpl_dir or INVITE_TEMPLATE_DIR)
    p = d / "btn_ignore.png"
    if not p.exists():
        return {}
    img = None
    if p.exists():
        img = cv2.imdecode(np.fromfile(str(p), dtype=np.uint8),
                           cv2.IMREAD_COLOR)
    if img is None:
        return {}
    return {"ignore": cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)}


def find_ignore_button(img: np.ndarray,
                       templates: Optional[Dict[str, np.ndarray]] = None,
                       tpl_dir: Optional[Path] = None,
                       threshold: float = INVITE_MATCH_THRESHOLD,
                       ) -> Optional[Tuple[int, int]]:
    """在截图里找「忽略」按钮；找到返回按钮中心，没有返回 None。"""
    if templates is None:
        templates = load_invite_templates(tpl_dir)
    if not isinstance(img, np.ndarray) or img.size == 0 or not templates:
        return None
    page = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    tpl = templates["ignore"]
    h, w = tpl.shape[:2]
    if h >= page.shape[0] or w >= page.shape[1]:
        return None
    res = cv2.matchTemplate(page, tpl, cv2.TM_CCOEFF_NORMED)
    _, score, _, loc = cv2.minMaxLoc(res)
    if score < threshold:
        return None
    return loc[0] + w // 2, loc[1] + h // 2
