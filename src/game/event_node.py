"""事件节点（钱袋）内部选择规则（用户口述落地）。

## 规则原文（用户 2026-09-18）

「当前界面是事件节点内部，遇到固定选中间的。」

## 界面特征（2026-09-18 信陵君「虎符在手」实测）

三个选项**横排**在页面底部一行（y≈842）：
【晓之以理】复制8张装备牌 ｜【中项】速度-2复制8张战法牌 ｜【威逼利诱】消耗太平百钱/失属性
与武将/伙伴事件（纵向三行）不同，判别特征 = **同一 y 上 ≥2 个【…】括号项**。
点击点取 x 居中项（描述在标签下方 ~45px，点标签下沿即可）。

标题/选项文案每局都变（虎符在手/晓之以理…全是事件专属文案），**只认横排【】结构，
不做任何文案假设**——文案变化不影响识别。
"""
from __future__ import annotations

import re
from typing import List, Optional, Sequence, Tuple

__all__ = ["pick_event_node_option", "is_event_node_page", "ROW_Y_BAND"]

#: 【】括号项允许出现的 y 带（页面底部选项行）
ROW_Y_BAND: Tuple[int, int] = (740, 940)
#: 同一横行的 y 容差
ROW_TOLERANCE = 25
#: 括号项正则
_BRACKET_RE = re.compile(r"^【[^【】]+】$")

#: OCR 全部漏检时的兜底点击点（三列中间列，实测 2026-09-18）
FALLBACK_CLICK: Tuple[int, int] = (1089, 880)


def _bracket_items(items: Sequence) -> List[Tuple[int, int, str]]:
    out = []
    for it in items:
        t = "".join(str(getattr(it, "text", "")).split())
        if not _BRACKET_RE.match(t):
            continue
        x1, y1, x2, y2 = it.rect
        cy = (y1 + y2) // 2
        if ROW_Y_BAND[0] <= cy <= ROW_Y_BAND[1]:
            out.append(((x1 + x2) // 2, cy, t))
    return out


def is_event_node_page(items: Sequence) -> bool:
    """判别是否事件节点选项页：同 y 横排上 ≥2 个【…】项。"""
    cands = _bracket_items(items)
    ys = [cy for _, cy, _ in cands]
    for y in set(ys):
        if sum(1 for cy in ys if abs(cy - y) <= ROW_TOLERANCE) >= 2:
            return True
    return False


def pick_event_node_option(items: Sequence) -> Tuple[Optional[Tuple[int, int]], str]:
    """固定选**横排中间**的选项。

    Returns
    -------
    ``(点击点, 理由)``；识别不到横排括号项时退回固定坐标兜底。
    """
    cands = _bracket_items(items)
    # 聚出候选行（以第一个候选的 y 为基准聚同 y 项，取人数最多的行）
    best_row: List[Tuple[int, int, str]] = []
    for y in set(cy for _, cy, _ in cands):
        row = [c for c in cands if abs(c[1] - y) <= ROW_TOLERANCE]
        if len(row) > len(best_row):
            best_row = row
    if len(best_row) >= 2:
        best_row.sort(key=lambda c: c[0])
        mid = best_row[len(best_row) // 2]
        return (mid[0], mid[1] + 45), f"事件节点 → 固定选中间「{mid[2]}」"
    # 兜底：OCR 漏检括号时用实测固定坐标
    return FALLBACK_CLICK, "事件节点 → 固定选中间（OCR 未检出括号项，用兜底坐标）"
