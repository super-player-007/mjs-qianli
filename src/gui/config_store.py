"""GUI 配置的存取与游戏侧应用（对应 GUI 的「保存配置/加载配置」）。"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List

__all__ = ["DEFAULT_CONFIG", "load_config", "save_config",
           "apply_gift_categories", "CONFIG_PATH"]

# gui.json 必须跟 exe/config 目录走（冻结感知），不能用 CWD 相对路径——
# 2026-11-13 事故：从任务栏图标等启动时 CWD ≠ exe 目录，gui.json 读不到
# → 静默回落 DEFAULT_CONFIG → 商店名单变 20 项默认清单（行囊丢失）。
from src.config import CONFIG_DIR  # noqa: E402
CONFIG_PATH = CONFIG_DIR / "gui.json"

#: 默认值 = 当前代码内的既定规则（GUI 加载后可改）
DEFAULT_CONFIG: Dict = {
    "hero": "吕布",
    "categories": {
        "信物": ["钟离眜", "吕布", "关羽", "马超", "陈平", "英布",
                "刘邦", "范增", "龙且", "王异"],
        "驰援": ["周勃", "刘禅", "曹丕", "樊哙", "虞姬", "孙坚",
                "鲁肃", "大乔"],
        "资助": ["袁术", "曹操", "曹植", "张春华", "步练师", "吕雉",
                "郭嘉", "夏侯惇", "徐晃", "张飞", "董卓"],
    },
    # 节点优先级（事件 key 或类型 key，从高到低）
    "priority": ["hero_wolong", "mate_feifei", "hero_shier", "rest",
                 "shop", "hero_moja", "hero_fengfeng", "mate_dog",
                 "event"],
    # 商店保留线：武将牌专区购物后余额不得低于它（GUI 可调）
    "shop_reserve": 150,
    # 商店想要商品清单（GUI 可改；空列表回落 shop.py 内建默认）
    "shop_wanted": ["衔枚", "玉珏", "将印", "刺字", "骨鲠", "象棋",
                    "白蛇皮", "九章律", "薄曲", "西园帐薄", "鸠杯",
                    "青囊书", "龟甲", "孟德新书", "大斧", "熏炉",
                    "纱锦囊", "蒲元传", "草鞋", "调兵符"],
    "tap_scale": 0.7,     # 点击等待缩放（1.0=原速）
    "runs": 1,            # 执行轮次
    "poll": 4.0,          # 托管轮询间隔（秒）
}


def load_config(path: Path = CONFIG_PATH) -> Dict:
    """加载配置；文件缺失/损坏时返回默认值（深拷贝）。"""
    base = json.loads(json.dumps(DEFAULT_CONFIG))   # deep copy
    p = Path(path)
    if not p.exists():
        return base
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return base
    # 逐键合并，缺的用默认补齐
    for key, val in data.items():
        base[key] = val
    for key in ("hero", "tap_scale", "runs", "poll"):
        base.setdefault(key, DEFAULT_CONFIG[key])
    base.setdefault("categories", dict(DEFAULT_CONFIG["categories"]))
    base.setdefault("priority", list(DEFAULT_CONFIG["priority"]))
    base.setdefault("shop_wanted", list(DEFAULT_CONFIG["shop_wanted"]))
    base.setdefault("shop_reserve", DEFAULT_CONFIG["shop_reserve"])
    return base


def save_config(cfg: Dict, path: Path = CONFIG_PATH) -> Path:
    """保存配置到 JSON（UTF-8），返回路径。"""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(cfg, ensure_ascii=False, indent=2),
                 encoding="utf-8")
    return p


#: 类别检查顺序：与赠礼类型优先级（信物>驰援>资助）一致。
#: 同名重复时**以先出现的类别为准**（确定性，不依赖字典遍历顺序）。
CATEGORY_CHECK_ORDER = ("信物", "驰援", "资助")


def find_duplicates(categories: Dict[str, List[str]]) -> Dict[str, List[str]]:
    """找出跨类别重复的武将名。

    Returns
    -------
    ``{武将名: [类别1, 类别2, ...]}``（类别按 信物>驰援>资助 排序）
    """
    seen: Dict[str, List[str]] = {}
    for label in CATEGORY_CHECK_ORDER:
        for n in categories.get(label, []):
            n = n.strip()
            if not n:
                continue
            seen.setdefault(n, [])
            if label not in seen[n]:
                seen[n].append(label)
    return {name: cats for name, cats in seen.items() if len(cats) > 1}


def apply_shop_reserve(value) -> int:
    """把 GUI「太平百钱保留线」应用到 shop 运行时值。"""
    from src.game import shop
    return shop.apply_shop_reserve(value)


def apply_shop_wanted(names) -> list:
    """把 GUI「商店商品名单」应用到 shop 运行时清单（整体重建）。

    空/全空白 → 回落 shop.py 内建默认。返回实际生效清单。
    """
    from src.game import shop
    return shop.apply_shop_wanted(names)


def apply_gift_categories(categories: Dict[str, List[str]]) -> List[str]:
    """把 GUI 里的三张名单应用到 gift.HERO_CATEGORIES（整体重建）。

    键必须恰为 信物/驰援/资助（二级界面选项词）。
    同名跨类别重复时**以先出现的类别为准**（信物>驰援>资助）。

    Returns
    -------
    实际生效的重复武将及裁决结果，形如 ``["钟离眜: 信物(忽略 驰援)"]``。
    """
    from src.game import gift
    mapping = {"信物": gift.CATEGORY_SIGNAL,
               "驰援": gift.CATEGORY_RELAY,
               "资助": gift.CATEGORY_FUND}
    resolved: List[str] = []
    gift.HERO_CATEGORIES.clear()
    for label in CATEGORY_CHECK_ORDER:          # 固定顺序 → first-wins 确定
        cat = mapping.get(label)
        if cat is None:
            continue
        for n in categories.get(label, []):
            n = n.strip()
            if not n:
                continue
            if n in gift.HERO_CATEGORIES:
                resolved.append(f"{n}: {gift.HERO_CATEGORIES[n]}"
                                f"(忽略重复的 {label})")
                continue
            gift.HERO_CATEGORIES[n] = cat
    # 钟离眜的三种写法统一（2026-09-20 补「昧」——OCR 三种都会读出，
    # 旧代码只补「眜/眛」，「昧」的注册在内建名单被 clear 后失联 → 赠礼漏检）。
    # 以名单里实际存在者的类别为准，三个写法 setdefault 齐平。
    base = None
    for sp in ("钟离眜", "钟离眛", "钟离昧"):
        if gift.HERO_CATEGORIES.get(sp):
            base = gift.HERO_CATEGORIES[sp]
            break
    if base:
        for sp in ("钟离眜", "钟离眛", "钟离昧"):
            gift.HERO_CATEGORIES.setdefault(sp, base)
    return resolved
