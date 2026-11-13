"""界面状态定义与处理器。

设计目标：**数据驱动**
----------------------
每个界面的「怎么判定（detect）」由 ``config/coords.yaml`` 的模板名与
``config/ocr_rules.yaml`` 的关键词描述；「怎么操作（handle）」由本文件的
处理器函数描述。这样后续标定新界面时，多数情况只需改 YAML，不必改代码。

判定优先级
----------
列表顺序即优先级：越靠前越先判定。把"特征最明确、最不容易误判"的界面
放在前面（如结算弹窗），把"通用兜底"放在最后。
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Sequence

from ..common.utils import rand_delay
from ..core.asker import Choice
from ..vision.annotate import save
from .context import Frame, GameContext

# ---------------------------------------------------------------- 处理器返回值
A_CONTINUE = "continue"     # 已处理，继续下一轮
A_DONE = "done"             # 本局流程正常结束
A_ABORT = "abort"           # 需要终止脚本
A_WAIT = "wait"             # 本界面暂不处理，等待（如战斗动画中）
A_UNKNOWN = "unknown"       # 无法识别
A_HANDOFF = "handoff"       # 交还给用户（如到达尚未标定的流程段）


@dataclass
class ScreenSpec:
    name: str
    desc: str
    priority: int
    detect: Callable[[GameContext, Frame], Optional[str]]
    handle: Callable[[GameContext, Frame, str], str]


# ===========================================================================
# 判定辅助
# ===========================================================================
def _tpl_hit(ctx: GameContext, frame: Frame, name: str,
             threshold: Optional[float] = None):
    return ctx.matcher.match_best(frame.image, name, threshold)


def _ocr_items(ctx: GameContext, frame: Frame,
               region: Optional[Sequence[int]] = None):
    """按帧缓存 OCR 结果（实现已上移到 GameContext.ocr_items）。

    同一帧内多个界面判定函数会反复请求 OCR；若不缓存，每个界面各跑一次
    全屏 OCR（实测约 1.4s/次），一轮下来要十几秒。
    """
    return ctx.ocr_items(frame, region)


def _ocr_hit(ctx: GameContext, frame: Frame, keywords: Sequence[str],
             region: Optional[Sequence[int]] = None, mode: str = "any"):
    if not keywords:
        return None
    hits = ctx.ocr.find(_ocr_items(ctx, frame, region), keywords, mode)
    return hits[0] if hits else None


# ===========================================================================
# 界面声明表
# ---------------------------------------------------------------------------
# tpl       : 模板素材名（相对于 assets/templates，可省略 .png）
#             —— 任一命中即认为该界面出现
# ocr       : OCR 关键词（填充 config/ocr_rules.yaml 后可省略此处）
# ocr_region: OCR 识别区域 [x1,y1,x2,y2]（基准分辨率）
# tpl_region: 模板搜索区域（限制区域可显著提速并减少误判）
# handler   : 处理器名（映射到 HANDLERS）
# ---------------------------------------------------------------------------
# ⚠ 以下模板名/关键词为「待标定占位」。真实值需采集游戏界面后填入，
#   缺失的资源会被自动跳过（不会误判为命中）。
# ===========================================================================
SCREEN_DEFS: List[Dict] = [
    # ---------------- 入口页（由 nav.py 用固定坐标到达，此处做后续动作）----------------
    {
        "name": "qianli_entry", "desc": "千里单骑入口页（选择武将 / 难度 / 开始挑战）",
        "priority": 197, "handler": "qianli_entry",
        "tpl": ["qianli/title_anchor.png"],
        "ocr": ["开始挑战", "挑战所需"], "ocr_all": ["选择武将"],
    },
    # ---------------- 对局内界面（待标定） ----------------
    {
        "name": "run_settle", "desc": "本局结算（通关或阵亡后的里程奖励）",
        "priority": 100, "handler": "settle",
        "ocr": ["里程", "结算", "奖励", "义旗"], "tpl": [],
        "terminal": True,
    },
    {
        "name": "battle_result", "desc": "单场战斗结算/继续",
        "priority": 90, "handler": "confirm",
        "ocr": ["战斗胜利", "胜利", "继续"], "tpl": ["battle_result/continue.png"],
        "element": "primary",
    },
    {
        "name": "buff_choice", "desc": "增益三选一 ★决策点",
        "priority": 80, "handler": "choose",
        # ⚠ 未标定前不要用「选择」这类泛关键词：千里单骑入口页就有「选择武将」，
        #   会造成整页误判并触发不必要的提问。等见到真实界面再用其独有文案/模板。
        "ocr": [], "tpl": ["buff_choice/anchor.png"],
        "element": "options",
    },
    {
        "name": "event_choice", "desc": "事件节点选项 ★决策点",
        "priority": 78, "handler": "choose",
        # ⚠ 不能用「事件」当唯一关键词：**地图页顶部图例栏就有「事件·」**
        #   （实测 conf=0.79），会把整个地图页误判成事件界面（已踩坑）。
        #   用地图形特征词当否决词兜住；见到真实事件界面后再补其独有文案。
        "ocr": ["事件"], "tpl": ["event_choice/anchor.png"],
        "exclude": ["当前挑战", "结束挑战"],
        "element": "options",
    },
    {
        "name": "rest_node", "desc": "休息节点选择 ★决策点",
        "priority": 76, "handler": "choose",
        # ⚠ 同上：地图页图例栏有「休息·」（实测 conf=0.87）。
        "ocr": ["休息"], "tpl": ["rest_node/anchor.png"],
        "exclude": ["当前挑战", "结束挑战"],
        "element": "options",
    },
    {
        "name": "shop", "desc": "商店 ★决策点",
        "priority": 74, "handler": "choose",
        # ⚠ 不能用「商店」这种泛关键词：战役页上有「战役商店」，会导致整页误判。
        #   待进入对局见到真实商店界面后，改用其独有标题/购买按钮模板再填。
        "ocr": [], "tpl": ["shop/anchor.png"],
        "exclude": ["战役商店"],
        "element": "options",
    },
    {
        "name": "hero_select", "desc": "武将选择页",
        "priority": 60, "handler": "confirm",
        "ocr": ["选择武将", "出战武将", "上阵"], "tpl": ["hero_select/confirm.png"],
        "element": "primary",
    },
    {
        "name": "difficulty_select", "desc": "难度选择（壹~捌）",
        "priority": 58, "handler": "confirm",
        # ⚠ 同理：「难度」二字在千里单骑入口页也有，标定前留空避免误判。
        "ocr": [], "tpl": ["difficulty_select/confirm.png"],
        "element": "primary",
    },
    {
        "name": "battle_confirm", "desc": "战斗前置确认页（对手预览 + 开始对局/再想一想）",
        "priority": 55, "handler": "battle_confirm",
        # 用「开始对局」+「再想一想」两个按钮同现判定：这对文案只在该页出现，
        # 不会与地图页/入口页混淆，故比「战役属性」更适合作锚点
        # （「战役属性」是美术字，实测被 OCR 读成「战没属性」conf=0.88）。
        "ocr": [], "ocr_all": ["开始对局", "再想一想"],
        "element": "primary",
    },
    {
        "name": "battle_mulligan", "desc": "换初始手牌弹窗 ★决策点（兵法·军需，首次不消耗）",
        "priority": 52, "handler": "mulligan",
        # 标题原文「是否需要更换初始手牌？」，conf=0.99，独有且非美术字
        "ocr": ["是否需要更换初始手牌"],
        "element": "options",
    },
    {
        "name": "run_map", "desc": "局内地图 / 节点选择",
        "priority": 50, "handler": "map",
        # 用页面框架文案判定，不用节点（节点会变）。
        # ⚠ 顶部图例栏的「战斗·商店·事件·休息·」是**说明文字**，
        #   既不能当界面锚点，也不能当可选节点（已踩坑，见 docs/05 第 6 节）。
        "ocr": [], "ocr_all": ["当前挑战", "结束挑战"],
        "tpl": ["run_map/anchor.png"],
        "element": "node",
    },
    {
        "name": "battle", "desc": "战斗进行中（自动战斗，等待结算）",
        "priority": 40, "handler": "battle_wait",
        # 战斗页没有「自动战斗/托管」这类文字按钮，故不能用它们做锚点。
        # 改用左上角轮次区（box 见 coords.battle.round_label）：
        # 该区域内只有「第N轮」一段文本，故用「第」+「轮」限定区域判定。
        "ocr": ["自动战斗", "托管", "倍速"], "tpl": ["battle/auto_flag.png"],
        "ocr_all": ["第", "轮"], "ocr_region": [104, 87, 201, 122],
    },
    {
        "name": "popup_confirm", "desc": "通用确认弹窗（确定/知道了）",
        "priority": 30, "handler": "confirm",
        "ocr": ["确定", "知道了", "确认", "下一步"],
        "tpl": ["common/confirm.png"],
        "element": "primary",
    },
]


# ===========================================================================
# 处理器
# ===========================================================================
def handle_confirm(ctx: GameContext, frame: Frame, detail: str) -> str:
    """点击界面主按钮（继续/确定/下一步）。"""
    name = ctx.get_state("_cur_screen", "")
    if ctx.tap_element(name, "primary"):
        return A_CONTINUE
    # 退化：OCR 找按钮文字并点其中心
    for spec in SCREEN_DEFS:
        if spec["name"] == name:
            for kw in spec.get("ocr", []):
                hit = _ocr_hit(ctx, frame, [kw])
                if hit:
                    ctx.tap_point(hit.center)
                    return A_CONTINUE
    ctx.log.warning("[%s] 未找到可点击的主按钮，跳过", name)
    return A_WAIT


def handle_choose(ctx: GameContext, frame: Frame, detail: str) -> str:
    """★决策点：增益三选一 / 事件 / 休息 / 商店。

    流程：读取候选坐标 -> 用策略打分给出推荐 -> 暂停提问 -> 点击用户选择。
    """
    name = ctx.get_state("_cur_screen", "") or "choice"
    el = ctx.cfg.element(name, "options") or ctx.cfg.element(name, "options_container")
    points: List[Sequence[int]] = []
    if el:
        points = list(el.get("points") or [])

    if not points:
        # 尚未标定候选坐标 —— 请用户手动处理，而不是瞎点
        ctx.log.warning("[%s] 尚无候选坐标（未标定），请你手动完成后继续", name)
        choice = ctx.asker.ask(
            title=f"未标定界面：{name}",
            question="当前界面尚未标定可选坐标，我无法自动点击。请你在模拟器中手动处理，"
                     "或选择终止。",
            options=[Choice("我已手动处理，继续", kind="manual_done"),
                     Choice("终止脚本", kind="abort")],
            screenshot=frame.image, kind="uncalibrated")
        return A_CONTINUE if choice == 0 else A_ABORT

    choices: List[Choice] = []
    for i, pt in enumerate(points):
        choices.append(Choice(label=f"选项 {i + 1}", desc="", xy=list(pt), kind=name))

    choice = ctx.asker.ask(
        title=f"决策点：{ctx.get_state('_cur_screen_desc', name)}",
        question="请选择你要采取的一项（会点击对应位置）：",
        options=choices, screenshot=frame.image, kind=name)

    ctx.tap_point(choices[choice].xy)
    return A_CONTINUE


def handle_battle_wait(ctx: GameContext, frame: Frame, detail: str) -> str:
    """战斗中：若存在"跳过/自动"按钮可点，否则静默等待。"""
    for el in ("skip", "auto", "speed"):
        if ctx.cfg.element(ctx.get_state("_cur_screen", "battle"), el):
            ctx.tap_element(ctx.get_state("_cur_screen", "battle"), el)
            return A_CONTINUE
    return A_WAIT


def handle_mulligan(ctx: GameContext, frame: Frame, detail: str) -> str:
    """★决策点：换初始手牌。

    提示行含「首次不消耗，剩余N次」——换牌次数有限，换不换取决于牌组价值判断，
    属于需要游戏理解的策略决策，故一律提问，不擅自替用户决定。
    """
    hint = ""
    box = ctx.cfg.box("battle_mulligan", "hint")
    if box:
        hint = ctx.ocr.text_of(frame.image, box)

    choice = ctx.asker.ask(
        title="决策点：换初始手牌",
        question=(f"{hint}\n" if hint else "") + "是否更换当前初始手牌？",
        options=[Choice("更换（点「更换」）", kind="mulligan_yes"),
                 Choice("不换，保留当前手牌（点「取消」）", kind="mulligan_no")],
        screenshot=frame.image, kind="mulligan")

    el = "confirm" if choice == 0 else "cancel"
    if ctx.tap_element("battle_mulligan", el):
        rand_delay([0.8, 1.5])
        return A_CONTINUE
    ctx.log.warning("[换牌弹窗] 未找到 %s 按钮坐标", el)
    return A_WAIT


def handle_battle_confirm(ctx: GameContext, frame: Frame, detail: str) -> str:
    """战斗前置确认页：记录对手信息，然后点「开始对局」。

    「再想一想」可以退回地图重选节点 —— 但对本流程而言节点已由用户选定，
    故默认直接开打；对手信息（阵营/武将名/主题）写入日志，供复盘与后续策略。
    """
    cfg = ctx.cfg
    parts: List[str] = []
    for el, tag in (("enemy_faction", "阵营"), ("enemy_name", "对手"),
                    ("enemy_star", "星级"), ("theme", "主题")):
        box = cfg.box("battle_confirm", el)
        if not box:
            continue
        txt = ctx.ocr.text_of(frame.image, box)
        if txt:
            parts.append(f"{tag}={txt}")
    ctx.log.info("[战斗确认] %s", "  ".join(parts) or "(未读到对手信息)")

    pt = cfg.point("battle_confirm", "start_battle")
    if not pt:
        ctx.log.error("坐标表缺少 battle_confirm.start_battle")
        return A_ABORT
    ctx.log.info("点击「开始对局」@ (%d, %d)", pt[0], pt[1])
    ctx.tap_point(pt)
    rand_delay([1.5, 2.5])
    return A_CONTINUE


def handle_map(ctx: GameContext, frame: Frame, detail: str) -> str:
    """局内地图：选择下一个节点（★决策点）。"""
    return handle_choose(ctx, frame, detail)


def handle_settle(ctx: GameContext, frame: Frame, detail: str) -> str:
    """本局结算：领取奖励并结束本次流程。"""
    ctx.log.info("检测到本局结算界面，尝试领取奖励")
    handle_confirm(ctx, frame, detail)
    return A_DONE


def handle_qianli_entry(ctx: GameContext, frame: Frame, detail: str) -> str:
    """千里单骑入口页：★决策点 —— 是否开打、用哪个武将和难度。

    这里不再自动往下走，而是把控制权交给你：因为「选哪个武将」「打几难度」
    属于策略决策，且后续对局内流程尚未标定。
    """
    # 读取页面信息，作为提问的上下文
    cfg = ctx.cfg
    order_box = cfg.box("qianli", "order_count")
    cost_box = cfg.box("qianli", "cost_area")
    order_txt = ctx.ocr.text_of(frame.image, order_box) if order_box else ""
    cost_txt = ctx.ocr.text_of(frame.image, cost_box) if cost_box else ""
    ctx.log.info("[千里单骑入口页] 天命令: %s  挑战所需: %s", order_txt or "?", cost_txt or "?")

    choice = ctx.asker.ask(
        title="已到千里单骑入口页",
        question=f"已进入「千里单骑」入口页。\n"
                 f"天命令: {order_txt or '?'}   挑战所需: {cost_txt or '?'}\n"
                 f"请选择下一步（武将/难度请先在模拟器中确认）：",
        options=[
            Choice("开始挑战（用当前武将和难度）", kind="qianli_start"),
            Choice("我已手动选好武将/难度，现在开始挑战", kind="qianli_start"),
            Choice("先停在这里，我自己操作", kind="handoff"),
            Choice("终止脚本", kind="abort"),
        ],
        screenshot=frame.image, kind="qianli_entry")

    if choice in (0, 1):
        pt = cfg.point("qianli", "start_challenge")
        if not pt:
            ctx.log.error("坐标表缺少 qianli.start_challenge")
            return A_ABORT
        ctx.log.info("点击「开始挑战」@ (%d, %d)", pt[0], pt[1])
        ctx.tap_point(pt)
        rand_delay([1.5, 2.5])
        # 后续对局内流程尚未标定，交还用户
        ctx.log.warning("已点击开始挑战。对局内流程尚未标定，脚本在此交接。")
        return A_HANDOFF
    if choice == 2:
        ctx.log.info("用户选择停在入口页，脚本交接。")
        return A_HANDOFF
    return A_ABORT


def handle_unknown(ctx: GameContext, frame: Frame, detail: str) -> str:
    """未知界面：存档截图并询问用户怎么办（绝不瞎点）。"""
    path = None
    try:
        path = save(frame.image, ctx.cfg.shot_dir / f"unknown_{int(time.time())}.png")
    except Exception as exc:  # noqa: BLE001
        ctx.log.debug("未知界面截图保存失败: %s", exc)

    choice = ctx.asker.ask(
        title="未知界面",
        question=f"我无法识别当前界面（截图：{path}）。请问如何继续？",
        options=[
            Choice("我已经手动处理好，继续", kind="manual_done"),
            Choice("这是战斗中，继续等待", kind="wait"),
            Choice("重新截屏再识别一次", kind="retry"),
            Choice("终止脚本", kind="abort"),
        ],
        screenshot=frame.image, kind="unknown")

    return {0: A_CONTINUE, 1: A_WAIT, 2: A_CONTINUE, 3: A_ABORT}[choice]


HANDLERS: Dict[str, Callable[[GameContext, Frame, str], str]] = {
    "confirm": handle_confirm,
    "choose": handle_choose,
    "map": handle_map,
    "mulligan": handle_mulligan,
    "battle_confirm": handle_battle_confirm,
    "battle_wait": handle_battle_wait,
    "settle": handle_settle,
    "unknown": handle_unknown,
    "qianli_entry": handle_qianli_entry,
}

# 运行期按名字查界面声明
SCREEN_BY_NAME: Dict[str, Dict] = {s["name"]: s for s in SCREEN_DEFS}


# ===========================================================================
# 注册表构建
# ===========================================================================
def _make_detector(sdef: Dict) -> Callable[[GameContext, Frame], Optional[str]]:
    """依据界面声明生成判定函数：模板命中 或 OCR 关键词命中。

    支持 ``exclude`` 否决词：命中任一即**直接判否**，用于防止泛关键词误判。
    典型场景：战役页上有「战役商店」四个字，若只写关键词「商店」，
    整个战役页会被误判为商店界面——加上 ``exclude: ["战役商店"]`` 即可。
    """
    name = sdef["name"]
    tpls: Sequence[str] = sdef.get("tpl") or []
    ocr_kws: Sequence[str] = sdef.get("ocr") or []
    ocr_all: Sequence[str] = sdef.get("ocr_all") or []
    exclude: Sequence[str] = sdef.get("exclude") or []
    ocr_region = sdef.get("ocr_region")
    tpl_region = sdef.get("tpl_region")

    def detect(ctx: GameContext, frame: Frame) -> Optional[str]:
        # 0) 否决词：命中即判否，避免泛关键词误判
        if exclude:
            hit = _ocr_hit(ctx, frame, exclude, ocr_region)
            if hit:
                ctx.log.debug("[%s] 命中否决词「%s」，判否", name, hit.text)
                return None

        # 1) 模板优先（更精确）
        best = None
        for t in tpls:
            hit = _tpl_hit(ctx, frame, t)
            if hit and (best is None or hit.score > best.score):
                best = hit
        if best:
            return f"tpl:{best.name}@{best.score:.2f}"

        # 2) OCR 兜底
        if ocr_kws:
            hit = _ocr_hit(ctx, frame, ocr_kws, ocr_region)
            if hit:
                return f"ocr:{hit.text}"
        if ocr_all:
            hit = _ocr_hit(ctx, frame, ocr_all, ocr_region, mode="all")
            if hit:
                return f"ocr_all:{hit.text}"
        return None

    detect.__name__ = f"detect_{name}"
    return detect


def build_registry() -> List[ScreenSpec]:
    specs: List[ScreenSpec] = []
    for sdef in SCREEN_DEFS:
        handler = HANDLERS.get(sdef.get("handler", ""), handle_unknown)
        specs.append(ScreenSpec(
            name=sdef["name"],
            desc=sdef["desc"],
            priority=int(sdef.get("priority", 50)),
            detect=_make_detector(sdef),
            handle=handler,
        ))
    # 兜底
    specs.append(ScreenSpec(
        name="unknown", desc="无法识别的界面", priority=-1,
        detect=lambda ctx, frame: "fallback",
        handle=handle_unknown,
    ))
    specs.sort(key=lambda s: s.priority, reverse=True)
    return specs
