"""赠礼决策规则（用户口述规则，逐字落地）。

## 规则原文（用户 2026-09-16）

武将分为三类：

* **信物武将**：荀彧 王异 吕布 关羽 贾诩 马超 陈平 龙且 范增 章邯
  姜维 庞统 司马懿 萧何 刘邦 华佗 左慈 钟离昧
* **驰援武将**：周勃 刘禅 曹丕 樊哙 虞姬 孙坚 鲁肃 大乔
* **资助武将**：袁术 曹操 曹植 张春华 步练师 吕雉 郭嘉 夏侯惇 徐晃 张飞
  张辽 典韦 张良 法正 黄月英 黄盖 魏延 小乔 董卓

赠礼选择的优先级（按**赠礼武将**的类别决定，跟我方出战武将无关）：

| 赠礼武将类别 | 优先级 |
|---|---|
| 信物武将 | 信物 > 驰援 > 资助 > 武将牌 > 并肩作战 |
| 驰援武将 | 驰援 > 资助 > 信物 > 武将牌 > 并肩作战 |
| 资助武将 | 资助 > 驰援 > 信物 > 武将牌 > 并肩作战 |
| 三种都没有 | **固定选中间的**；优先级 驰援 > 资助 > 信物 > 武将牌 > 并肩作战 |

> ⚠ **易错点**：判别条件是「赠礼三选一里出现的武将」，**不是**我方出战武将。
> 2026-09-16 实测：出战钟离眜（信物武将）＋赠礼武将为吕蒙/凌统/韩信（均不在名单）
> → 应按"三种都没有 → 选中间"处理，当时误按钟离眜判成信物，选错了。

## 两级界面

1. **一级**：`请选择接受谁的赠礼？` —— 三张武将立绘 + 名字（如 吕蒙/凌统/韩信）。
   选一位 →  进入二级。
2. **二级**：`<武将字>赠礼` —— 该武将的具体赠礼选项，如
   `信物(获得衣袂)` / `资助(随机添加8张装备牌…获得20枚太平百钱)` / `并肩作战(凌统加入队伍)`。
   按上面的优先级表选。

一级「三个武将都有类别时怎么选」用户尚未给出规则，见 :func:`pick_gift_hero` 的说明。
"""

from __future__ import annotations

from typing import Dict, Iterable, List, Optional, Sequence, Tuple

__all__ = [
    "HERO_CATEGORIES", "CATEGORY_SIGNAL", "CATEGORY_RELAY", "CATEGORY_FUND",
    "GIFT_TYPES", "PRIORITY_BY_CATEGORY", "PRIORITY_FALLBACK",
    "HERO_LABEL_BAND", "TITLE_BAND", "OPTION_BAND", "OCR_ALIASES",
    "classify_hero", "pick_gift_hero", "rank_gift_types", "pick_gift_options",
    "detect_gift_heroes", "detect_gift_options",
]

#: 信物武将
CATEGORY_SIGNAL = "信物"
#: 驰援武将
CATEGORY_RELAY = "驰援"
#: 资助武将
CATEGORY_FUND = "资助"

#: 武将 → 类别。键为游戏内常见写法（含 OCR 易混的异体字）。
HERO_CATEGORIES: Dict[str, str] = {}


def _register(names: Iterable[str], category: str) -> None:
    """注册武将类别。setdefault = **先到先得**（2026-09-20 修正）。

    历史踩坑：内建名单里龙且/范增/马超/周勃/刘邦/曹操/徐晃同时写在信物和
    驰援两个列表，旧逻辑"后写的赢"导致它们在模块加载时被静默降级成驰援
    （正是"有龙且却选了陈宫"事故的根因之一）。现按用户定策统一为
    信物 > 驰援 > 资助 先到先得。
    """
    for n in names:
        HERO_CATEGORIES.setdefault(n, category)


_register([
    "钟离昧", "龙且", "司马懿", "荀彧", "吕布", "关羽", "徐晃", "马超",
    "范增", "英布", "周勃", "曹操", "章邯", "庞统", "萧何", "刘邦",
    "华佗", "左慈", "王异",
], CATEGORY_SIGNAL)

_register([
    "周勃", "项梁", "季布", "刘邦", "刘禅", "曹丕", "樊哙", "虞姬",
    "孙坚", "鲁肃", "大乔", "陈胜", "吕雉", "范增", "龙且", "孙权", "马超",
], CATEGORY_RELAY)

_register([
    "袁术", "曹操", "曹植", "张春华", "步练师", "吕雉", "郭嘉", "夏侯惇",
    "徐晃", "张飞", "张辽", "典韦", "张良", "法正", "黄月英", "黄盖", "魏延",
    "小乔", "董卓",
], CATEGORY_FUND)

#: 名单里的名字都用「钟离昧」，但游戏与 OCR 常出现「钟离眜」，补一个别名。
HERO_CATEGORIES.setdefault("钟离眜", CATEGORY_SIGNAL)
HERO_CATEGORIES.setdefault("钟离眛", CATEGORY_SIGNAL)

#: OCR 误读别名表：误读名 → 正名（2026-09-20 龙且漏检事故沉淀）。
#: 两字生僻名（龙且等）OCR 极易翻车，且 classify_hero 的子串匹配救不了
#: 字形错字（"龙目"和"龙且"互不为子串）——命中别名后按正名查表。
#: 后续每发现一个新误读就往这里追加。
OCR_ALIASES: Dict[str, str] = {
    "龙旦": "龙且",
    "龙目": "龙且",
    "尤且": "龙且",
}

#: 赠礼类型（二级界面的选项），按「优先级表」的固定顺序
GIFT_TYPES: Tuple[str, ...] = ("信物", "驰援", "资助", "武将牌", "并肩作战")

#: 选项别名：OCR 变体 → 标准叫法。标准叫法「武将牌」（2026-11-13 用户澄清：
#: 游戏一直叫武将牌，此前规则记录成"武将卡"是笔误——单选项武将牌赠礼页
#: 曾因白名单无此词 → 识别为空 → 误判事件页停机）
OPTION_ALIASES: Dict[str, str] = {"武将卡": "武将牌"}

#: 按赠礼武将类别给出的优先级（靠前者更优）
PRIORITY_BY_CATEGORY: Dict[str, Tuple[str, ...]] = {
    CATEGORY_SIGNAL: ("信物", "驰援", "资助", "武将牌", "并肩作战"),
    CATEGORY_RELAY: ("驰援", "资助", "信物", "武将牌", "并肩作战"),
    CATEGORY_FUND: ("资助", "驰援", "信物", "武将牌", "并肩作战"),
}

#: 赠礼武将不属于任何类别时的兜底优先级
PRIORITY_FALLBACK: Tuple[str, ...] = ("驰援", "资助", "信物", "武将牌", "并肩作战")


def roster_index(name: str) -> Optional[int]:
    """返回武将在名单里的**枚举顺序**（同类别内排前者优先的依据）。

    名单 dict 的插入顺序即用户口述名单的顺序（信物：荀彧 王异 吕布 …龙且…）。
    匹配规则与 classify_hero 相同：别名表 → 精确 → 子串互含。查不到返回 None。
    """
    if not name:
        return None
    key = "".join(ch for ch in name if ch.isalnum() or "\u4e00" <= ch <= "\u9fff")
    if not key:
        return None
    key = OCR_ALIASES.get(key, key)
    for i, (known, _cat) in enumerate(HERO_CATEGORIES.items()):
        if known == key or known in key or key in known:
            return i
    return None


def classify_hero(name: str) -> Optional[str]:
    """返回武将在三类名单里的类别，查不到返回 ``None``。"""
    i = roster_index(name)
    if i is None:
        return None
    return list(HERO_CATEGORIES.values())[i]


def pick_gift_hero(heroes: Sequence[str]) -> Tuple[Optional[int], str]:
    """一级：从「请选择接受谁的赠礼？」的三（或 N）位武将里选一位。

    Returns
    -------
    ``(index, reason)``；``index`` 为 ``heroes`` 下标，识别不出时返回 ``None``。

    Notes
    -----
    用户明确的规则（2026-09-16 定中间兜底；2026-11-12 确认类别优先）：

    * 三位武将**都不在**任何类别名单 → **固定选中间的**（实测吕蒙/凌统/韩信即此例）。
    * 有类别时按 信物 > 驰援 > 资助 取最优（同类别内多位 → 取排最前的）；
      **位置不参与跨类别比较**（用户 2026-11-12 明确确认维持此规则）。
    """
    if not heroes:
        return None, "没有候选武将"
    cats = [classify_hero(h) for h in heroes]

    if not any(cats):
        mid = len(heroes) // 2
        return mid, f"三位赠礼武将均不在名单 → 固定选中间（{heroes[mid]}）"

    for want in (CATEGORY_SIGNAL, CATEGORY_RELAY, CATEGORY_FUND):
        idxs = [i for i, c in enumerate(cats) if c == want]
        if idxs:
            # 同类别多位 → **按名单枚举顺序**排前者优先（2026-11-12 用户明确：
            # 吕布/龙且同为信物时选名单更靠前的吕布，与屏幕左右无关）
            best = min(idxs, key=lambda i: roster_index(heroes[i])
                       if roster_index(heroes[i]) is not None else 10 ** 9)
            others = [heroes[i] for i in idxs if i != best]
            why = f"命中{want}武将 {heroes[best]}（类别优先；同类别按名单顺序取优"
            if others:
                why += "，" + heroes[best] + " 在名单中先于 " + "/".join(others)
            return best, why + "）"
    return len(heroes) // 2, "需要人工确认"


def rank_gift_types(hero: Optional[str]) -> Tuple[str, ...]:
    """返回某位赠礼武将对应的赠礼类型优先级序列。"""
    cat = classify_hero(hero or "")
    return PRIORITY_BY_CATEGORY.get(cat, PRIORITY_FALLBACK)


def pick_gift_options(options: Sequence[str],
                      hero: Optional[str]) -> Tuple[Optional[int], str]:
    """二级：从该武将的具体赠礼选项里按优先级选一项。

    Parameters
    ----------
    options : 界面上实际出现的选项名（如 ``["信物", "资助", "并肩作战"]``）
    hero    : 一级选中的赠礼武将名，用于决定优先级；``None`` 走兜底。

    Returns
    -------
    ``(index, reason)``；``index`` 为 ``options`` 下标或 ``None``。
    """
    if not options:
        return None, "没有候选赠礼"

    cat = classify_hero(hero or "")
    order = PRIORITY_BY_CATEGORY.get(cat, PRIORITY_FALLBACK)

    def norm(s: str) -> str:
        return "".join(s.split())

    for want in order:
        for i, opt in enumerate(options):
            if norm(want) in norm(opt) or norm(opt) and norm(opt) in norm(want):
                tag = cat if cat else "三类之外"
                return i, f"赠礼武将={hero or '?'}（{tag}）→ 优先级 {order[0]}… 命中「{opt}」"

    # 优先级里没有的选项（真出了没见过的赠礼类型）→ 兜底选中间
    mid = len(options) // 2
    return mid, f"优先级 {order} 未覆盖任何选项 → 兜底选中间「{options[mid]}」"


# --------------------------------------------------------------------------- #
# 从 OCR 结果里抽候选（实测坐标，1920×1080）
# --------------------------------------------------------------------------- #

#: 一级「XX赠礼」标签所在的 y 带（三张武将卡的底部）
HERO_LABEL_BAND = (740, 860)
#: 二级顶部「XX赠礼」大标题的 y 带（用来把它和一级标签区分开）
TITLE_BAND = (60, 200)
#: 二级选项标签（信物/资助/并肩作战…）的 y 带
OPTION_BAND = (220, 780)


def _norm(s: str) -> str:
    return "".join(s.split())


def detect_gift_heroes(items: Sequence) -> List[Tuple[str, Tuple[int, int]]]:
    """从 OCR 条目里抽一级候选武将，返回 ``[(武将名, (cx, cy))]``，按 x 升序。

    一级界面的标签形如「吕蒙赠礼」「凌统赠礼」；二级顶部的「公绩赠礼」是标题，
    用 :data:`HERO_LABEL_BAND` / :data:`TITLE_BAND` 的 y 区间把两者分开。
    """
    out: List[Tuple[str, Tuple[int, int]]] = []
    y1, y2 = HERO_LABEL_BAND
    for it in items:
        text = _norm(it.text)
        x1, yy1, x2, yy2 = it.rect
        cy = (yy1 + yy2) // 2
        if not (y1 <= cy <= y2):
            continue
        if not text.endswith("赠礼") or len(text) <= 2:
            continue
        name = text[:-2]
        if len(name) > 4:          # 「请选择接受谁的赠礼」之类的长句，排除
            continue
        out.append((name, ((x1 + x2) // 2, cy)))
    return sorted(out, key=lambda p: p[1][0])


def detect_gift_options(items: Sequence) -> List[Tuple[str, Tuple[int, int]]]:
    """从 OCR 条目里抽二级候选赠礼，返回 ``[(类型, (cx, cy))]``，按 y 升序。"""
    out: List[Tuple[str, Tuple[int, int]]] = []
    y1, y2 = OPTION_BAND
    for it in items:
        text = _norm(it.text)
        text = OPTION_ALIASES.get(text, text)   # OCR 变体武将卡 → 武将牌
        if text not in GIFT_TYPES:
            continue
        x1, yy1, x2, yy2 = it.rect
        cy = (yy1 + yy2) // 2
        if not (y1 <= cy <= y2):
            continue
        out.append((text, ((x1 + x2) // 2, cy)))
    return sorted(out, key=lambda p: p[1][1])

