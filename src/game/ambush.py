"""偷袭事件处理规则（2026-09-20 实测采集，2026-10-08 断行修正）。

## 界面与规则（用户口述 + 实测）

「偷袭」事件：各种武将组合偷袭，底部一个按钮「与XX、XX战斗」
（XX 为敌方武将名，**每局都变**）。用户规则：**点击该按钮即可进入战斗**，
无其他决策。

## 判别方式（两种形态）

① 按钮完整在一行：``与…战斗``（正则 ``^与.{1,20}战斗$``）→ 点 OCR 实时框中心
② **按钮换行断开**（2026-10-08 事故）：敌方 3 人时文案过长，
   「与张良、诸葛亮、司马懿战」+「斗」拆成两行 OCR 条目 → 单行正则失配。
   改用全文拼接检测：页面含「偷袭」标题 **且** 拼接后含 ``与…战斗`` 结构。

## 点击位置

两个实测样本（964,866 / 960,868）证明**按钮位置固定** → 断行形态
直接点固定坐标 ``(960,867)``，不依赖断行的 OCR 框。
"""
from __future__ import annotations

import re
from typing import Optional, Sequence, Tuple

__all__ = ["is_ambush_page", "pick_ambush_button", "AMBUSH_FIXED_POS"]

#: 偷袭按钮固定位置（2026-09-25 与 2026-10-08 两个样本实测一致）
AMBUSH_FIXED_POS = (960, 867)

_BATTLE_RE = re.compile(r"^与.{1,20}战斗$")
_BATTLE_IN_TEXT = re.compile(r"与.{1,20}战斗")
_AMBUSH_ANCHOR = "偷袭"


def _norm_items(items: Sequence) -> Tuple[str, str]:
    """返回 (拼接全文, 逐条归一化文本列表)。"""
    texts = ["".join(str(getattr(it, "text", "")).split()) for it in items]
    return "".join(texts), texts


def _battle_button(items: Sequence) -> Optional[Tuple[int, int, str]]:
    """按钮完整在一行时，返回其 (cx, cy, 原文)；否则 None。"""
    _, texts = _norm_items(items)
    for it, t in zip(items, texts):
        if _BATTLE_RE.match(t):
            x1, y1, x2, y2 = it.rect
            return (x1 + x2) // 2, (y1 + y2) // 2, t
    return None


def is_ambush_page(items: Sequence) -> bool:
    """判别是否偷袭事件页：单行按钮 **或** 「偷袭」标题+断行按钮结构。"""
    if _battle_button(items) is not None:
        return True
    joined, _ = _norm_items(items)
    return _AMBUSH_ANCHOR in joined and bool(_BATTLE_IN_TEXT.search(joined))


def pick_ambush_button(items: Sequence) -> Tuple[Optional[Tuple[int, int]], str]:
    """返回 ``(点击点, 理由)``；非偷袭页返回 ``(None, 理由)``。"""
    hit = _battle_button(items)
    if hit is not None:
        return (hit[0], hit[1]), f"偷袭事件 → 点「{hit[2]}」"
    joined, _ = _norm_items(items)
    if _AMBUSH_ANCHOR in joined and _BATTLE_IN_TEXT.search(joined):
        return AMBUSH_FIXED_POS, "偷袭事件（按钮换行断开）→ 点固定按钮位"
    return None, "未找到「与…战斗」按钮"
