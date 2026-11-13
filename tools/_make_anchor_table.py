# -*- coding: utf-8 -*-
"""锚点表生成器（2026-11-11）：裁锚点 → 生成 anchors.yml → 全夹具交叉验证。

表序 = 匹配优先级（具体页在前、通用页在后，类似 OneDragon 的精准早停）：
  覆盖层 → 战斗子页 → 页面骨架 → 结算链 → 提示条兜底 → 战斗（最泛）
"""
import sys
from pathlib import Path

import cv2
import numpy as np
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from src.vision.annotate import read_image  # noqa: E402

TPL_DIR = ROOT / "assets/templates/anchors"
YML_OUT = ROOT / "assets/screen_info/anchors.yml"
TH = 0.9

# (state, fixture|None, crop_rect|None, search_rect, threshold, needs_ocr, scope)
SPEC = [
    # 覆盖层最高优先（任何阶段都可能出现）
    ("refresh_confirm", None, None, (600, 250, 1350, 450), 0.9, True, "global"),
    # 武将信息弹层（地图叠层，必须先于 map）
    ("hero_info", "hero_info.png", (1576, 192, 1743, 238),
     (1500, 150, 1850, 300), 0.9, False, "in_run"),
    # 地图（双锚点 AND：结束挑战 + 当前挑战标题）
    ("map", "map_new_skin.png", (1553, 850, 1712, 889),
     (1450, 780, 1800, 980), 0.9, False, "in_run"),
    ("map", "map_new_skin.png", (196, 269, 315, 315),
     (150, 240, 560, 340), 0.9, False, "in_run"),
    ("battle_confirm", "battle_confirm.png", (619, 897, 797, 944),
     (500, 820, 950, 1010), 0.9, False, "in_run"),
    ("mulligan", "mulligan.png", (804, 502, 1123, 539),
     (700, 450, 1250, 600), 0.9, False, "in_run"),
    ("tip_screen", "tip_screen.png", (496, 910, 706, 945),
     (400, 860, 1550, 1000), 0.9, False, "in_run"),
    # ---- 决策页：锚点判页 + 区域 OCR（2026-11-11，整屏 1.9s -> 0.4s）----
    ("gift1", "gift1.png", (747, 911, 1156, 954), (700, 880, 1200, 980),
     0.9, True, "in_run", (300, 700, 1650, 1000)),
    # ---- 结算链（区域限定真按钮，替代 0.994 互配消歧）----
    ("settle_confirm", "settle_settle_confirm.png", (908, 926, 1013, 980),
     (850, 880, 1100, 1010), 0.9, False, "in_run"),
    ("reward_overlay", "settle_reward_overlay.png", (812, 273, 1105, 361),
     (700, 240, 1200, 420), 0.9, False, "in_run"),
    # 2026-11-12 游戏更新：领取奖励移到底部中央 (876,924)-(1044,960)
    ("run_settle", "run_settle_new.png", (870, 918, 1050, 966),
     (700, 860, 1250, 1010), 0.9, False, "in_run"),
    # 提示条页兜底（完胜空白/普通预览/胜利页）：动作=点底部空白
    ("next_preview", "settle_next_preview.png", (826, 918, 1096, 960),
     (700, 900, 1250, 1010), 0.9, False, "in_run"),
    # 完胜预览页（下一步按钮变体，动作同 next_preview）
    ("next_preview", "next_preview_wansheng.png", (892, 938, 1029, 986),
     (820, 890, 1090, 1010), 0.9, False, "in_run"),
    # ---- 商店（2026-11-12 增补）：判页从整屏 OCR 降为锚点 50ms ----
    # ⚠ 购买弹窗必须排在 shop 之前：弹窗页左上角的吕不韦小铺子标题仍可见，
    #   两锚点都会命中，表格顺序决定判页结果
    ("purchase_confirm", "purchase_confirm_new.png", (908, 260, 1010, 310),
     (760, 220, 1200, 360), 0.9, False, "in_run"),
    ("shop", "shop_main_new.png", (278, 94, 694, 164),
     (150, 60, 850, 220), 0.9, False, "in_run"),
    # 战斗（最泛：投降按钮；必须在所有结算/子页之后）
    ("battle", "battle_live.png", (1806, 368, 1888, 411),
     (1700, 300, 1920, 480), 0.9, False, "in_run"),
]

EXPECT = {
    "map_new_skin.png": "map", "map_layer2_new.png": "map",
    "map_layer1.png": "map", "map_layer2.png": "map",
    "map_layer3.png": "map", "map_layer4.png": "map",
    "map_layer5.png": "map", "map_layer6.png": "map",
    "map_last_layer.png": "map",
    "battle_confirm.png": "battle_confirm",
    "battle_live.png": "battle",
    "battle_target_select.png": "battle",   # 选目标页无独立状态，归 battle 处理
    "hero_info.png": "hero_info",
    "mulligan.png": "mulligan", "tip_screen.png": "tip_screen",
    "refresh_popup.png": "refresh_confirm",
    "settle_settle_confirm.png": "settle_confirm",
    "settle_reward_overlay.png": "reward_overlay",
    "settle_run_settle.png": "refresh_confirm",   # 旧皮肤夹具内嵌弹窗，属正确
    "run_settle_new.png": "run_settle",
    "run_settle.png": "run_settle",
    # 2026-11-12 商店两锚点的新皮肤夹具
    "shop_main_new.png": "shop",
    "purchase_confirm_new.png": "purchase_confirm",
    "shop_confirm.png": "purchase_confirm",   # 旧弹窗夹具（牙门旗），同款皮肤
    "settle_next_preview.png": "next_preview",
    "next_preview_wansheng.png": "next_preview",
    "battle_end_preview.png": "next_preview",
    "gift1.png": "gift1",   # gift2 与伙伴事件页同构，不入表（走 OCR 分类）
    # 2026-11-12 游戏更新后的新皮肤夹具
    "map_layer2_new.png": "map",
    "battle_confirm_new.png": "battle_confirm",
    "task_page_claim.png": None,
    "task_page_refresh.png": None,
    "task_page_new.png": None,   # 2026-11-13 新版任务页（按钮模板重裁自它）
}


#: 2026-11-12 游戏更新前的旧皮肤夹具：只作为节点/OCR 逻辑测试素材，
#: 不再参与锚点交叉验证（按钮皮肤已变，必然对不上）
LEGACY_SKIP = {
    "settle_run_settle.png",
    "map_layer1.png", "map_layer2.png", "map_layer3.png", "map_layer4.png",
    "map_layer5.png", "map_layer6.png", "map_last_layer.png",
    "battle_end_preview.png",
}


def gray_of(p: Path):
    img = read_image(p)
    return None if img is None else cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)


def main() -> int:
    entries = []
    TPL_DIR.mkdir(parents=True, exist_ok=True)
    counters = {}
    for state, fixture, crop_rect, rect, th, needs_ocr, scope, *rest in SPEC:
        ocr_region = rest[0] if rest else None
        if fixture is None:
            src = ROOT / "assets/templates/popup/refresh_confirm.png"
            a = cv2.imdecode(np.fromfile(str(src), dtype=np.uint8),
                             cv2.IMREAD_COLOR)
            anchor = cv2.cvtColor(a, cv2.COLOR_BGR2GRAY)
            name = f"{state}.png"
        else:
            g = gray_of(ROOT / "tests/fixtures" / fixture)
            x1, y1, x2, y2 = crop_rect
            anchor = g[y1:y2, x1:x2]
        # 同名状态多条目自动编号：state.png / state_1.png
        idx = counters.get(state, 0)
        counters[state] = idx + 1
        name = f"{state}.png" if idx == 0 else f"{state}_{idx}.png"
        out = TPL_DIR / name
        cv2.imencode(".png", anchor)[1].tofile(str(out))
        entry = {"state": state, "scope": scope, "needs_ocr": needs_ocr,
                 "areas": [{"anchor": name, "rect": list(rect),
                            "threshold": th}]}
        if ocr_region:
            entry["ocr_region"] = list(ocr_region)
        entries.append(entry)
        print(f"锚点 {state}/{name}: {anchor.shape[1]}x{anchor.shape[0]}")

    # map 的双锚点需要合并进同一 entry（AND），rebuild 一下
    merged = []
    for e in entries:
        if e["state"] == "map" and merged and merged[-1]["state"] == "map":
            merged[-1]["areas"].extend(e["areas"])
        else:
            merged.append(e)

    YML_OUT.parent.mkdir(parents=True, exist_ok=True)
    YML_OUT.write_text(yaml.dump(merged, allow_unicode=True, sort_keys=False),
                       encoding="utf-8")
    print(f"yml → {YML_OUT}（{len(merged)} 条目）")

    # ---- 交叉验证 ----
    from src.game.anchor_table import load_anchor_table, match_entry
    table = load_anchor_table(YML_OUT)
    fails = []
    fixtures = sorted((ROOT / "tests/fixtures").glob("*.png"))
    for f in fixtures:
        if f.name in LEGACY_SKIP:
            continue
        g = gray_of(f)
        if g is None:
            continue
        hit = match_entry(g, table, in_run=True)
        hit_state = hit.state if hit else None
        want = EXPECT.get(f.name, None)
        if f.name not in EXPECT:
            if hit_state is not None:
                fails.append(f"{f.name}: 未登记却命中 {hit_state}")
            continue
        if want is None and hit_state is not None:
            fails.append(f"{f.name}: 不应命中但命中 {hit_state}")
        elif want and hit_state != want:
            fails.append(f"{f.name}: 期望 {want} 实际 {hit_state}")
    if fails:
        print("✗ 交叉验证未通过:")
        for f_ in fails:
            print("   ", f_)
        return 1
    print(f"✓ 交叉验证通过（{len(fixtures)} 张夹具 × {len(table)} 条目）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
