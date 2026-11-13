"""武将事件·墨家巨子选项规则（用户口述落地）。

## 规则原文（用户 2026-09-17）

「墨家巨子优先级比较低，按理说很难选到，如果选到这个节点，就固定选第一个」
（优先级表里墨家巨子低于卧龙/朏朏/十二阉人，通常轮不到；选中则无需决策）。

页面：「请选择一种制造」三行（结构与武将/伙伴事件页同构）：
- 墨子的制造一：体力上限-3，获得技能：闭月之姿
- 墨子的制造二：初始手牌-2，获得技能：斧破重围
- 墨子的制造三：战法增伤-1，获得技能：截粮焚辎

判别方式：页面底部「请选择一种**制造**」——「制造」二字是本页专属锚词
（蛊惑/赠礼页都没有），比逐选项匹配更稳；命中即固定选第一行。
"""
from __future__ import annotations

from typing import Optional, Sequence, Tuple

from src.game.hero_event import OPTION_ROWS, ROW_BAND, detect_event_rows

__all__ = ["pick_moja_event"]


def pick_moja_event(items: Sequence) -> Tuple[Optional[Tuple[int, int]], str]:
    """墨家巨子制造页：确认是「制造」页后**固定选第一行**。"""
    rows = detect_event_rows(items)
    if not rows:
        return None, "未识别到任何事件选项行"
    if not any("制造" in text for _, text in rows):
        return None, f"页面无「制造」锚词（{len(rows)} 行）→ 不是墨家巨子页"
    return (1200, OPTION_ROWS[rows[0][0]]), "墨家巨子（低优先级）→ 固定选第一个"
