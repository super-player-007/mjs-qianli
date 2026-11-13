"""休息节点（安营驻寨）决策规则（用户口述，逐字落地）。

## 规则原文（用户 2026-09-17）

休息节点内部三选一，共有**四种情况**，按出现的选项组合判别，各有一个优先选项：

* **情况一 → 优先「以逸待劳」**
  【积草屯粮】获得 15 枚太平百钱 /【以逸待劳】手牌上限+2、体力上限+2 /
  【养精蓄锐】回复 4 点体力
* **情况二 → 优先「稳中求进」**
  【研读兵法】随机增强牌堆中 6 张战法牌 /【稳中求进】回复 2 点体力，添加 2 张易至牌堆 /
  【养精蓄锐】回复 4 点体力
* **情况三 → 优先「固本培元」**
  【广纳贤才】失去 8 枚太平百钱，随机添加 1 张武将牌至牌堆 /
  【固本培元】将体力上限变为当前体力值两倍 /【养精蓄锐】回复 4 点体力
* **情况四 → 优先「劫营速战」**（2026-10-12 用户改：原选秣马厉兵）
  【秣马厉兵】速度+2、杀的伤害+1 /【劫营速战】删除牌堆中 2 张休养生息，速度+4 /
  【养精蓄锐】回复 4 点体力

判别方式：每种情况都有**独有选项**（积草屯粮/研读兵法/广纳贤才/秣马厉兵…），
见 ``REST_CASES`` 的 ``markers``。「养精蓄锐」四种情况都有，不能当判别依据。
"""
from __future__ import annotations

from typing import List, Optional, Sequence, Tuple

__all__ = ["REST_CASES", "REST_FALLBACK", "pick_rest_option",
           "REST_OPTION_BAND", "detect_rest_options"]


def _norm(s: str) -> str:
    return "".join(s.split())


#: 四种情况：markers 用于判别（各情况的独有选项），prefer 是该情况的优先选项。
#: 选项名取【】里的名字（OCR 常把【】读丢，只按名字匹配）。
REST_CASES: List[dict] = [
    {"case": "一", "prefer": "以逸待劳",
     "markers": ["积草屯粮", "以逸待劳"],
     "desc": "积草屯粮:得15太平百钱 / 以逸待劳:手牌上限+2体力上限+2 / 养精蓄锐:回4体力"},
    {"case": "二", "prefer": "稳中求进",
     "markers": ["研读兵法", "稳中求进"],
     "desc": "研读兵法:增强6张战法牌 / 稳中求进:回2体力添2张 / 养精蓄锐:回4体力"},
    {"case": "三", "prefer": "固本培元",
     "markers": ["广纳贤才", "固本培元"],
     "desc": "广纳贤才:-8太平百钱加1武将牌 / 固本培元:体力上限x2 / 养精蓄锐:回4体力"},
    {"case": "四", "prefer": "劫营速战",
     "markers": ["秣马厉兵", "劫营速战"],
     "desc": "秣马厉兵:速度+2杀伤+1 / 劫营速战:删2休养生息速度+4 / 养精蓄锐:回4体力"},
]

#: 兜底：四种情况都有「养精蓄锐」（保守回 4 体力）
REST_FALLBACK = "养精蓄锐"


def detect_rest_case(options: Sequence[str]) -> Optional[dict]:
    """按选项组合判别是哪种情况；判别不出返回 ``None``。"""
    normed = [_norm(o) for o in options]
    for case in REST_CASES:
        for marker in case["markers"]:
            if any(marker in o or o in marker for o in normed if o):
                return case
    return None


def pick_rest_option(options: Sequence[str],
                     ) -> Tuple[Optional[int], str]:
    """从休息节点的三（或 N）个选项里选一个，返回 ``(下标, 理由)``。

    ``options`` 为界面上出现的选项名（如 ``["广纳贤才", "固本培元", "养精蓄锐"]``），
    顺序即界面从左到右。
    """
    if not options:
        return None, "没有候选选项"

    case = detect_rest_case(options)
    if case is not None:
        prefer = _norm(case["prefer"])
        for i, o in enumerate(options):
            no = _norm(o)
            if prefer in no or no in prefer:
                return i, f"情况{case['case']}（命中标记「{case['markers'][0]}」）→ 优先「{case['prefer']}」"

    # 判别不出情况：有兜底选项就选它
    fb = _norm(REST_FALLBACK)
    for i, o in enumerate(options):
        no = _norm(o)
        if fb in no or no in fb:
            return i, f"未匹配到已知情况 → 兜底选「{REST_FALLBACK}」"

    # 连兜底都没有 → 选中间，并明确说要人工复核
    mid = len(options) // 2
    return mid, f"未匹配到已知情况且无「{REST_FALLBACK}」→ 兜底选中间「{options[mid]}」（⚠需人工复核）"


# --------------------------------------------------------------------------- #
# 从 OCR 结果里抽候选（实测坐标，1920×1080，2026-09-17 情况三）
# --------------------------------------------------------------------------- #

#: 休息节点选项区的 y 带（【XX】标题 + 描述文字都在这里面）
REST_OPTION_BAND = (790, 940)


def detect_rest_options(items: Sequence) -> List[Tuple[str, Tuple[int, int]]]:
    """从 OCR 条目里抽休息节点候选选项，返回 ``[(选项名, (cx, cy))]``，按 x 升序。

    界面是三列「【选项名】 + 描述文字」，取【选项名】的框做点击点：
    x 用标题中心，y 加 40 落到选项卡中部（标题 y≈830，卡中部 ≈870，实测可点）。
    """
    out: List[Tuple[str, Tuple[int, int]]] = []
    y1, y2 = REST_OPTION_BAND
    for it in items:
        text = _norm(it.text)
        x1, yy1, x2, yy2 = it.rect
        cy = (yy1 + yy2) // 2
        if not (y1 <= cy <= y2):
            continue
        if not (text.startswith("【") and text.endswith("】")):
            continue
        name = text[1:-1].strip()
        if not name or len(name) > 8:
            continue
        out.append((name, ((x1 + x2) // 2, cy + 40)))
    return sorted(out, key=lambda p: p[1][0])
