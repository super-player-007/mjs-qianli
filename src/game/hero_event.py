"""武将节点事件选择规则（用户口述，逐字落地）。

## 规则原文（用户 2026-09-17）

所有事件是下面 6 个随机出 3 个，作为事件一/二/三，**优先级为 1、2、4、3、5、6**：

1. 接下来的 4 场战斗中，你无法打出桃，之后你的体力上限翻倍。
2. 接下来的 3 场战斗中，你的速度降为 1，之后你的速度 + 10。
3. 接下来的 5 场战斗中，你无法打出装备牌，之后增强你的牌堆中的所有装备牌。
4. 接下来的 5 场战斗中，你无法获得太平百钱，之后当你获得的太平百钱时，翻倍获得。
5. 接下来的 4 场战斗中，你打出行动牌后，随机弃置 2 张牌，之后你打出行动牌后，
   随机弃置一名敌方角色的 1 张牌。
6. 接下来的 3 场战斗中，你获得的战法牌全部转化为天雷，之后删除所有天雷，
   并增加等量的夺粮劫营。

判别方式：按**描述文字**里的稳定关键词（标题「XX的蛊惑N」是事件专属美术文案，
换英雄事件会变，不能当判据）。界面固定三行选项，行中心 y≈335/530/715（1920×1080）。
"""
from __future__ import annotations

from typing import List, Optional, Sequence, Tuple

__all__ = ["HERO_EVENTS", "EVENT_PRIORITY", "OPTION_ROWS", "ROW_BAND",
           "pick_hero_event", "detect_event_rows"]

#: 六个事件的判别关键词（描述里的稳定短语；越独特越好，避免互相误伤）
HERO_EVENTS: List[dict] = [
    {"no": 1, "keys": ["无法打出桃"],
     "desc": "4场无桃→体力上限翻倍"},
    {"no": 2, "keys": ["速度降为"],
     "desc": "3场速度降1→速度+10"},
    {"no": 3, "keys": ["无法打出装备牌"],
     "desc": "5场无装备→增强牌堆装备"},
    {"no": 4, "keys": ["无法获得太平百钱"],
     "desc": "5场无太平百钱→之后翻倍"},
    {"no": 5, "keys": ["随机弃置", "行动牌"],
     "desc": "4场行动牌后随机弃2张→之后弃敌方1张"},
    {"no": 6, "keys": ["天雷"],
     "desc": "3场战法转天雷→删天雷加夺粮劫营"},
]

#: 优先级（用户口述）：1 > 2 > 4 > 3 > 5 > 6
EVENT_PRIORITY: Tuple[int, ...] = (1, 2, 4, 3, 5, 6)

#: 三个选项行的中心 y（1920×1080 实测 2026-09-17 十二阉人事件页）
OPTION_ROWS: Tuple[int, int, int] = (335, 530, 715)
#: 归行容差：OCR 条目中心 y 距某行中心 ≤ 此值即归入该行
ROW_BAND = 90


def _norm(s: str) -> str:
    return "".join(s.split())


def detect_event_rows(items: Sequence) -> List[Tuple[int, str]]:
    """把 OCR 条目按 y 归到三个选项行，返回 ``[(行号0~2, 该行拼接文本)]``（按行序）。"""
    rows: List[List[str]] = [[], [], []]
    for it in items:
        text = _norm(it.text)
        if not text:
            continue
        x1, y1, x2, y2 = it.rect
        cy = (y1 + y2) // 2
        best, best_d = None, 10**9
        for i, ry in enumerate(OPTION_ROWS):
            d = abs(cy - ry)
            if d < best_d:
                best, best_d = i, d
        if best is not None and best_d <= ROW_BAND:
            rows[best].append(text)
    return [(i, "".join(t)) for i, t in enumerate(rows) if t]


def _match_event(text: str) -> Optional[int]:
    for ev in HERO_EVENTS:
        if any(k in text for k in ev["keys"]):
            return ev["no"]
    return None


def pick_hero_event(items: Sequence) -> Tuple[Optional[Tuple[int, int]], str]:
    """从武将事件选项页的 OCR 结果里按优先级选一项。

    Returns
    -------
    ``(点击点, 理由)``；点击点为该选项行右半 (x=1200, 行中心 y)，识别失败返回 ``None``。
    """
    rows = detect_event_rows(items)
    if not rows:
        return None, "未识别到任何事件选项行"

    # 每行判别事件编号
    found: List[Tuple[int, int]] = []          # (行号, 事件编号)
    unknown_rows: List[int] = []
    for row_idx, text in rows:
        no = _match_event(text)
        if no is None:
            unknown_rows.append(row_idx)
        else:
            found.append((row_idx, no))

    if not found:
        return None, f"选项行全部无法判别事件（{len(unknown_rows)} 行未知）→ 需人工确认"

    # 按用户优先级选
    for want in EVENT_PRIORITY:
        for row_idx, no in found:
            if no == want:
                y = OPTION_ROWS[row_idx]
                ev = next(e for e in HERO_EVENTS if e["no"] == want)
                return (1200, y), f"命中优先级事件 {want}（{ev['desc']}）"

    # 理论到不了（found 里的编号都来自 EVENT_PRIORITY 覆盖的 1~6）
    row_idx, no = found[0]
    return (1200, OPTION_ROWS[row_idx]), f"兜底选行 {row_idx + 1}（事件 {no}）"
