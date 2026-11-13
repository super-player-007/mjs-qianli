"""伙伴节点事件选择规则（朏朏池，用户口述落地）。

## 规则原文（用户 2026-09-17）

偶遇朏朏三选一，**优先级为 1、3、2**（即 快睡午觉 > 我来帮你 > 讨价还价）：

1. 【快睡午觉】需要战斗的概率降低（效果唯一）
2. 【我来帮你】商店道具价格降低 10%（效果唯一）
3. 【讨价还价】你的伙伴技能触发概率 +8%

界面结构与武将事件选项页同构（三行，行中心 y≈330/520/710，与武将池的
335/530/715 差 ≤22px，共用行分组即可）。判别用选项**标题关键词**。
伙伴事件池可能不止朏朏一个——遇到新事件（选项关键词全部判别不出）返回
``None``，由执行器停机问用户，裁规则即插即用。
"""
from __future__ import annotations

from typing import Optional, Sequence, Tuple

from src.game.hero_event import OPTION_ROWS, ROW_BAND, detect_event_rows

__all__ = ["MATE_EVENTS", "MATE_PRIORITY", "pick_mate_event"]

#: 朏朏池：判别**只用描述文字关键词**——标题（快睡午觉/我来帮你/讨价还价）
#: 是会变的文案，不能当判据（用户 2026-09-17 明确，与武将事件「描述判别」同理）。
MATE_EVENTS: list = [
    {"no": 1, "keys": ["需要战斗的概率"],
     "desc": "需要战斗的概率降低(唯一)"},
    {"no": 2, "keys": ["商店道具价格"],
     "desc": "商店道具价格-10%(唯一)"},
    {"no": 3, "keys": ["伙伴技能触发"],
     "desc": "伙伴技能触发概率+8%"},
]

#: 优先级（用户口述）：快睡午觉 > 我来帮你 > 讨价还价
MATE_PRIORITY: Tuple[int, ...] = (1, 3, 2)


def pick_mate_event(items: Sequence) -> Tuple[Optional[Tuple[int, int]], str]:
    """从伙伴事件选项页的 OCR 结果里按优先级选一项。

    Returns
    -------
    ``(点击点, 理由)``；识别失败返回 ``(None, 理由)``。
    """
    rows = detect_event_rows(items)
    if not rows:
        return None, "未识别到任何事件选项行"

    found = []
    for row_idx, text in rows:
        for ev in MATE_EVENTS:
            if any(k in text for k in ev["keys"]):
                found.append((row_idx, ev["no"]))
                break

    if not found:
        return None, f"选项行全部无法判别事件（{len(rows)} 行未知）→ 需人工确认"

    for want in MATE_PRIORITY:
        for row_idx, no in found:
            if no == want:
                ev = next(e for e in MATE_EVENTS if e["no"] == want)
                return (1200, OPTION_ROWS[row_idx]), f"命中优先级事件 {want}（{ev['desc']}）"

    row_idx, no = found[0]
    return (1200, OPTION_ROWS[row_idx]), f"兜底选行 {row_idx + 1}（事件 {no}）"
