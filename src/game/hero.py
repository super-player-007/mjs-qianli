"""武将选择（通用，任意武将可换）。

核心流程
--------
1. 打开选将页（千里单骑入口页 → 点右侧卡片「战役属性」上方的武将立绘）
2. 切到「全部」页签
3. 在搜索框输入武将名 → 点「搜索」
4. 在结果网格里用 OCR 找到名字匹配的格子 → 点它的**头像**中心
5. 回读右侧大卡竖排武将名做校验
6. 点中间预览大图空白处退出（同时确认选择）

设计要点
--------
* **不写死任何武将名与格子位置**：目标名由参数传入，格子位置由 OCR 实时定位。
  换武将只需改参数，不用改代码。
* **用搜索而不是遍历网格**：武将数量随版本增长，网格会出现滚动；搜索是 O(1)
  且结果唯一，定位不依赖行列推算。
* **名字匹配留容错**：游戏内用字与用户输入可能不同（如「钟离眜」游戏内作
  「钟离昧」），因此除全名外还支持关键字/前两字匹配与字符重叠判定。
* **校验而非盲信**：右侧大卡是竖排文字，需旋转 90° 后 OCR（RapidOCR 自带方向
  分类器，顺/逆时针均可读）。

中文输入
--------
ADB 原生 ``input text`` 只支持 ASCII，中文会静默失败。本模块依赖 ADBKeyboard
（``tools/vendor/ADBKeyboard.apk``），由 ``ADBDevice.input_text`` 广播送入。
"""
from __future__ import annotations

import time
from typing import List, Optional, Tuple

import cv2

from ..common.utils import scale_box, scale_point
from ..vision.annotate import save
from .context import GameContext

SCREEN = "hero_select"          # 选将页在 coords.yaml 中的键
ENTRY_SCREEN = "qianli"         # 入口页（含「选择武将」卡片）


# ------------------------------------------------------------------ 配置取值
def _sec(ctx: GameContext, screen: str = SCREEN) -> dict:
    return (ctx.cfg.coords.get("screens") or {}).get(screen, {}) or {}


def _point(ctx: GameContext, screen: str, element: str) -> Optional[Tuple[int, int]]:
    """取某元素的点坐标（已缩放到实际分辨率）。"""
    el = _sec(ctx, screen).get(element) or {}
    xy = el.get("xy") or el.get("center")
    if not xy:
        return None
    return scale_point(xy, ctx.cfg.base_size, ctx.device.size)


def _region(ctx: GameContext, screen: str, element: str) -> Optional[List[int]]:
    """取某元素区域（已缩放到实际分辨率）。"""
    el = _sec(ctx, screen).get(element) or {}
    box = el.get("box")
    if not box:
        return None
    return scale_box(box, ctx.cfg.base_size, ctx.device.size)


def _rect_region(ctx: GameContext, box: List[int]) -> List[int]:
    return scale_box(box, ctx.cfg.base_size, ctx.device.size)


# ------------------------------------------------------------------ 文本匹配
def _norm(s: str) -> str:
    return "".join(ch for ch in str(s) if not ch.isspace())


def match_name(text: str, key: str) -> bool:
    """判断 OCR 文本是否可能是目标武将。

    三层放宽，依次尝试：
    1. 直接包含（最常见）
    2. 去掉「·」「空」等后仍包含
    3. 字符重叠数 >= len(key)-1（应对 OCR 误读异体字，如 眜/昧）
    """
    t, k = _norm(text), _norm(key)
    if not k or not t:
        return False
    if k in t:
        return True
    hit = sum(1 for ch in k if ch in t)
    return hit >= max(1, len(k) - 1)


# ------------------------------------------------------------------ 页面判定
def is_hero_select_page(ctx: GameContext, img) -> bool:
    """是否已在武将选择页（靠「武将选择」标题 + 搜索框双条件）。"""
    ts = [it.text for it in ctx.ocr.read(img)]
    has_title = any("武将选择" in _norm(t) for t in ts)
    has_search = any("搜索" in _norm(t) for t in ts)
    return has_title and has_search


def is_qianli_entry_page(ctx: GameContext, img) -> bool:
    """是否在千里单骑入口页。

    ⚠ 不能用「选择武将」做锚点：右侧卡片在**未选将**时显示「选择武将」，
    一旦选了将就换成武将名，该文字消失。改用始终存在的按钮/面板文字：
    「开始挑战」+ （「难度选择」或「挑战所需」或「无尽」）。
    """
    ts = [_norm(it.text) for it in ctx.ocr.read(img)]
    has_start = any("开始挑战" in t for t in ts)
    has_panel = any(kw in t for t in ts for kw in ("难度选择", "挑战所需", "无尽"))
    return has_start and has_panel


# ------------------------------------------------------------------ 分步动作
def open_hero_select(ctx: GameContext, wait: float = 1.8) -> bool:
    """确保处于选将页：不在则从入口页点开。"""
    img = ctx.device.screenshot()
    if is_hero_select_page(ctx, img):
        ctx.log.info("已在武将选择页")
        return True

    if not is_qianli_entry_page(ctx, img):
        ctx.log.error("当前不在千里单骑入口页，无法打开武将选择"
                      "（未同时识别到「开始挑战」与「难度选择/挑战所需/无尽」）")
        save(img, ctx.cfg.shot_dir / "hero_open_fail.png")
        return False

    # 入口页打开选将的方式：点右侧卡片「战役属性」上方的武将立绘（实测生效）
    pt = _point(ctx, ENTRY_SCREEN, "hero_card") or (1622, 501)
    ctx.log.info("点武将立绘打开武将选择 @%s", pt)
    ctx.tap_point(pt)
    time.sleep(wait)

    ok = is_hero_select_page(ctx, ctx.device.screenshot())
    if not ok:
        ctx.log.error("点击后仍未进入武将选择页")
    return ok


def click_tab(ctx: GameContext, name: str = "全部", wait: float = 1.0) -> bool:
    """点阶层筛选页签。"""
    g = _sec(ctx).get("tabs") or {}
    items = g.get("items") or []
    if name not in items:
        ctx.log.warning("未知页签: %s（可用: %s）", name, items)
        return False
    idx = items.index(name)
    x = float(g.get("x0", 213)) + float(g.get("step", 133.2)) * idx
    pt = scale_point((x, g.get("y", 724)), ctx.cfg.base_size, ctx.device.size)
    ctx.tap_point(pt)
    time.sleep(wait)
    return True


def search(ctx: GameContext, text: str, wait: float = 1.8):
    """在搜索框输入 ``text`` 并点搜索，返回结果截图。"""
    box = _point(ctx, SCREEN, "search_box")
    btn = _point(ctx, SCREEN, "search_btn")
    if not box or not btn:
        raise RuntimeError("坐标表缺少 hero_select.search_box / search_btn")

    ctx.tap_point(box)
    time.sleep(0.9)
    ctx.device.clear_input()        # 清掉上一次的关键词
    time.sleep(0.4)
    if not ctx.device.input_text(text):
        ctx.log.warning("文本「%s」可能未成功送入输入框", text)
    time.sleep(0.8)
    ctx.tap_point(btn)
    time.sleep(wait)
    return ctx.device.screenshot()


def locate_in_grid(ctx: GameContext, img, key: str) -> Optional[Tuple[int, int]]:
    """在结果网格里定位目标武将，返回其**头像中心**坐标。

    OCR 读到的是格子下方的名字，头像在名字上方 ``name_dy`` 像素处。
    """
    g = _sec(ctx).get("grid") or {}
    region = _rect_region(ctx, g.get("region") or [150, 780, 1810, 1035])
    name_dy = float(g.get("name_dy", 56))
    sy = ctx.device.size[1] / ctx.cfg.base_size[1]

    best = None
    for it in ctx.ocr.read(img, region):
        if not match_name(it.text, key):
            continue
        # 多命中时取最靠上、最靠左的格子（即搜索结果第一个）
        rank = (it.rect[1], it.rect[0])
        if best is None or rank < best[0]:
            best = (rank, it)

    if best is None:
        return None
    x1, y1, x2, y2 = best[1].rect
    cx = (x1 + x2) // 2
    cy = (y1 + y2) // 2 - int(round(name_dy * sy))
    return cx, cy


def read_selected_name(ctx: GameContext) -> str:
    """回读右侧大卡的竖排武将名（旋转后 OCR）。"""
    box = _region(ctx, SCREEN, "hero_card_name")
    if not box:
        return ""
    img = ctx.device.screenshot()
    x1, y1, x2, y2 = box
    h, w = img.shape[:2]
    if x1 < 0 or y1 < 0 or x2 > w or y2 > h:
        ctx.log.warning("hero_card_name 区域越界，跳过校验")
        return ""
    crop = img[y1:y2, x1:x2]
    # 竖排 -> 横排；RapidOCR 自带方向分类，顺/逆时针都能纠回
    rot = cv2.rotate(crop, cv2.ROTATE_90_COUNTERCLOCKWISE)
    big = cv2.resize(rot, None, fx=3.0, fy=3.0, interpolation=cv2.INTER_CUBIC)
    return "".join(it.text for it in ctx.ocr.read(big)).strip()


def exit_hero_select(ctx: GameContext, wait: float = 1.8) -> None:
    """点中间预览大图空白处退出（游戏把它当作「点击空白关闭」并确认选择）。"""
    pt = _point(ctx, SCREEN, "exit_point") or (880, 400)
    ctx.tap_point(pt)
    time.sleep(wait)


# ------------------------------------------------------------------ 主流程
def select_hero(ctx: GameContext,
                name: str,
                keyword: Optional[str] = None,
                verify: bool = True) -> bool:
    """选择武将 ``name``（通用，换武将只改参数）。

    Parameters
    ----------
    name : 武将名，如 ``"钟离眜"``
    keyword : 搜索关键词；默认取 ``name`` 前 2 字（对异体字/OCR 误读更宽容）
    verify : 是否回读右侧大卡校验选择结果
    """
    key = _norm(keyword or name[:2]) or _norm(name)
    ctx.log.info("=== 选择武将: %s（关键词=%s）===", name, key)

    if not ctx.device.ime_ensure():
        ctx.log.error("中文输入不可用（ADBKeyboard 未就绪），无法搜索武将")
        return False

    if not open_hero_select(ctx):
        return False

    click_tab(ctx, "全部")

    # 先用完整名搜；无结果则退到关键词重搜
    img = search(ctx, name)
    pos = locate_in_grid(ctx, img, key) or locate_in_grid(ctx, img, _norm(name))
    if pos is None and key != _norm(name):
        ctx.log.info("完整名无匹配，改用关键词「%s」重搜", key)
        img = search(ctx, key)
        pos = locate_in_grid(ctx, img, key)

    if pos is None:
        ctx.log.error("未找到武将「%s」：搜索结果中没有名字匹配的格子", name)
        save(img, ctx.cfg.shot_dir / f"hero_notfound_{key}.png")
        return False

    ctx.log.info("命中武将格子，点头像 @%s", pos)
    ctx.tap_point(pos)
    time.sleep(1.8)

    if verify:
        got = read_selected_name(ctx)
        ok = match_name(got, key)
        ctx.log.info("选择校验: 右侧大卡读到「%s」→ %s",
                     got or "(未识别)", "与目标一致 ✅" if ok else "与目标不一致 ⚠")
        if not ok:
            save(ctx.device.screenshot(), ctx.cfg.shot_dir / f"hero_verify_fail_{key}.png")
            ctx.log.warning("校验未通过，已存证截图；仍继续退出流程")

    exit_hero_select(ctx)
    ctx.mark("hero", name)
    ctx.log.info("武将选择完成: %s", name)
    return True
