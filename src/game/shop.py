"""商店（巴清小铺子）购买规则（用户口述，逐字落地）。

## 规则原文（用户 2026-09-17）

想要的商品：【行囊、飞将翎、大斧、纱锦囊、草鞋、龟甲、出手法、薄曲、将印、牙门旗】

购买逻辑：识别右上角拥有的太平百钱，和信物专区/武将牌专区的商品价格——
拥有的太平百钱 >（能覆盖）至少一个想要的商品价格 → 进行购买；
否则直接退出商品界面。

## 实现
- 界面：信物专区三列（名称 y≈271，价格 y≈525，列 x≈1048/1366/1687）+
  武将牌专区（名称 y≈772，价格在下方）。价格是纯数字 OCR 条目，
  其**同列上方最近的中文名**即商品名。
- 判定"想要"：商品名与 ``WANTED_ITEMS`` 做双向子串匹配（容忍 OCR 漏字）。
- 多个想买的都买得起时：取**价格最高**者（太平百钱稀缺，花在刀刃上）。
  ⚠ 此细节用户未明确，已标注待确认。
- 点击点 = 价格数字位置（商品卡整卡可点）。
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional, Sequence, Tuple

__all__ = ["WANTED_ITEMS", "SHOP_BALANCE_REGION", "parse_shop",
           "pick_shop_purchase", "apply_shop_wanted", "shop_wanted",
           "apply_shop_reserve", "shop_reserve", "SHOP_ZONE_Y_BOUNDARY"]

#: 内建默认想要清单（用户 2026-10-12 口述 20 项；GUI 未配置时的兜底）
WANTED_ITEMS: Tuple[str, ...] = (
    "衔枚", "玉珏", "将印", "刺字", "骨鲠", "象棋", "白蛇皮",
    "九章律", "薄曲", "西园帐薄", "鸠杯", "青囊书", "龟甲",
    "孟德新书", "大斧", "熏炉", "纱锦囊", "蒲元传", "草鞋", "调兵符",
)

#: 运行时想要清单（GUI 商店商品名单应用后生效，2026-10-09 新增）
_shop_wanted: List[str] = list(WANTED_ITEMS)


def apply_shop_wanted(names: Sequence[str]) -> List[str]:
    """整体重建想要清单（GUI「商店商品名单」启动时应用）。

    空/全空白 → 回落内建默认 ``WANTED_ITEMS``。
    返回实际生效的清单（供 GUI 日志展示）。
    """
    global _shop_wanted
    cleaned = [_norm(str(n)) for n in names if _norm(str(n))]
    _shop_wanted = cleaned or list(WANTED_ITEMS)
    return list(_shop_wanted)


def shop_wanted() -> Tuple[str, ...]:
    """当前生效的想要清单。"""
    return tuple(_shop_wanted)

#: 右上角太平百钱余额区域（1920×1080 实测）
SHOP_BALANCE_REGION: Tuple[int, int, int, int] = (1620, 110, 1780, 160)

#: 专区 y 分界（价格中心）：信物专区价格 y≈525、武将牌专区名称 y≈772
SHOP_ZONE_Y_BOUNDARY = 600

#: 运行时保留线（GUI「太平百钱保留线」，默认 150）
_shop_reserve: int = 150


def apply_shop_reserve(value: int) -> int:
    """设置太平百钱保留线（武将牌专区购物后余额不得低于它）。"""
    global _shop_reserve
    _shop_reserve = max(0, int(value))
    return _shop_reserve


def shop_reserve() -> int:
    """当前生效的保留线。"""
    return _shop_reserve

_PRICE_RE = re.compile(r"^\d{1,4}$")


def _norm(s: str) -> str:
    return "".join(s.split())


def _is_wanted(name: str, wanted: Sequence[str] = WANTED_ITEMS) -> bool:
    n = _norm(name)
    return any(w in n or n in w for w in wanted if n and w)


def parse_shop(items: Sequence) -> List[Dict]:
    """从 OCR 条目解析商品，返回 ``[{'name','price','click':(x,y)}]``（按价格降序）。

    规则：**纯数字条目视为价格**；其同列（|dx|<130）上方最近的中文短语即商品名；
    点击点取价格位置（商品卡整卡可点，实测可行）。
    """
    texts = []
    for it in items:
        t = _norm(it.text)
        if t:
            x1, y1, x2, y2 = it.rect
            texts.append((t, (x1 + x2) // 2, (y1 + y2) // 2))

    goods: List[Dict] = []
    for t, px, py in texts:
        if not _PRICE_RE.match(t):
            continue
        # 同列（|dx|≤130）且在价格**正上方**的名字里取最靠近价格的。
        # ⚠ 三个坑（2026-09-17 第 6 层实测）：
        #   ① 栏目标题「信物专区」x 恰与中列对齐，会抢名字 → 过滤「专区」；
        #   ② 折扣标签「5.0折」在名称与价格之间且含中文，会冒充名字 →
        #      商品名必须是**纯中文**（含数字/小数点的一律不要）——商品随机刷新，
        #      名字全靠 OCR 现场识别，没有任何固定清单假设；
        #   ③ 价格正下方可能还有别的数字，这里只取上方。
        cands = [(y2, t2) for t2, x2, y2 in texts
                 if y2 < py and abs(x2 - px) <= 130
                 and 2 <= len(t2) <= 8
                 and "专区" not in t2 and "折" not in t2
                 and not any(ch.isdigit() for ch in t2)
                 and sum("\u4e00" <= ch <= "\u9fff" for ch in t2) >= 2]
        if not cands:
            continue
        cands.sort(reverse=True)   # y 最大 = 最靠近价格
        # 专区归属（2026-10-12）：价格 y < 600 → 信物专区（y≈525）；
        # ≥ 600 → 武将牌专区（名称 y≈772、价格在卡底部）
        zone = "xinwu" if py < SHOP_ZONE_Y_BOUNDARY else "wupai"
        goods.append({"name": cands[0][1], "price": int(t),
                      "click": (px, py - 60), "zone": zone})

    goods.sort(key=lambda g: -g["price"])
    return goods


def pick_shop_purchase(items: Sequence,
                       coins: int,
                       wanted: Optional[Sequence[str]] = None,
                       reserve: Optional[int] = None,
                       ) -> Tuple[Optional[Dict], str]:
    """按规则选一个要买的商品（2026-10-12 分专区规则）。

    * 信物专区（xinwu）：按想要清单买，**不受保留线约束**——留下的
      150 太平百钱本来就是预备买信物的，买得起（coins ≥ 价格）就买。
    * 武将牌专区（wupai）：**全都要**（不限清单），但买后余额必须
      ≥ 保留线（GUI 可调，默认 150）。
    * 两区都没得买 → 退出商店。

    ``wanted``/``reserve`` 传 None 时用运行时值（GUI 应用后的）。

    Returns
    -------
    ``(商品dict 或 None, 理由)``；``None`` 表示不买、应退出商店。
    """
    if wanted is None:
        wanted = shop_wanted()
    if reserve is None:
        reserve = shop_reserve()

    goods = parse_shop(items)
    xinwu = [g for g in goods if g["zone"] == "xinwu"
             and _is_wanted(g["name"], wanted)]
    wupai = [g for g in goods if g["zone"] == "wupai"]

    # 信物专区：不受保留线约束
    affordable = [g for g in xinwu if coins >= g["price"]]
    if affordable:
        best = affordable[0]   # parse_shop 已按价格降序 → 买得起中价最高者
        return best, (f"信物专区「{best['name']}」价格 {best['price']}，"
                      f"太平百钱 {coins} 足够 → 购买（不受保留线约束）")

    # 武将牌专区：全都要，但保住保留线
    affordable_w = [g for g in wupai if coins - g["price"] >= reserve]
    if affordable_w:
        best = affordable_w[0]
        return best, (f"武将牌专区「{best['name']}」价格 {best['price']}，"
                      f"买后剩 {coins - best['price']} ≥ 保留线 {reserve} → 购买")

    # 都没得买：给理由
    if xinwu:
        names = "、".join(f"{g['name']}{g['price']}" for g in xinwu)
        return None, (f"太平百钱 {coins} 买不起信物专区的想要的商品"
                      f"（{names}），武将牌专区需保住保留线 {reserve} → 退出商店")
    if wupai:
        return None, (f"武将牌专区商品买后余额会跌破保留线 {reserve} → 退出商店")
    return None, "货架上没有想要清单里的商品，武将牌专区也无货 → 退出商店"

