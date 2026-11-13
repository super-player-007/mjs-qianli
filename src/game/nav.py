"""界面导航：主页 → 战役 → 千里单骑。**纯固定坐标，两次点击就到位。**

为什么这么简单
--------------
这三个页面的入口位置固定不变，实测反复点击都稳定命中
（模板分数 1.000），所以不需要模板锚点、不需要 OCR 兜底、
不需要每步验证落点——那套机制是为「位置会变」的界面准备的，
用在这里只是白白增加故障点和耗时。

实测：前进 3.5 秒（2 次点击）、回退 3.3 秒（2 次点击），
其中真正的点击只占几十毫秒，其余是等界面切换的固定等待（见 ``wait``）。

约定
----
* 前进：``home`` 点「战役」→ ``campaign`` 点「千里单骑」→ ``qianli``
* 回退：``qianli`` 点右上角返回 → ``campaign`` 点右上角返回 → ``home``
* Android 系统返回键（``keyevent 4``）在本游戏内**无效**，必须点游戏内图标，
  且该图标在**右上角**（不是常规的左上角）。

已知代价（有意为之）
--------------------
纯坐标方案必须知道「当前在哪一页」。调用方通过 ``frm`` 参数声明起点
（默认 ``home``）；若声明与实际不符，点击会落在空处。
排查方式：``run.py capture`` 抓一张图看一眼即可，不要再往这条链上加识别逻辑。

坐标、等待时间、步骤全部来自 ``config/coords.yaml > nav``；
只在「页面布局改版」时才需要重新标定。
"""
from __future__ import annotations

import time
from typing import Dict, List, Optional

from .context import GameContext

# 页面顺序（由浅到深），作为默认值与兜底
DEFAULT_CHAIN: List[str] = ["home", "campaign", "qianli"]

# 内置默认步骤表（coords.yaml 缺少 nav 段时使用）
DEFAULT_STEPS: Dict[str, Dict] = {
    "home": {"screen": "home", "element": "battle_entry", "wait": 1.6,
             "desc": "点「战役」卡片"},
    "campaign": {"screen": "campaign", "element": "qianli_card", "wait": 1.6,
                 "desc": "点「千里单骑」卡片"},
}
DEFAULT_BACK: Dict[str, Dict] = {
    "campaign": {"screen": "campaign", "element": "back", "wait": 1.5,
                 "desc": "点右上角返回键 → 回主界面"},
    "qianli": {"screen": "qianli", "element": "back", "wait": 1.5,
               "desc": "点右上角返回键 → 回战役页"},
}


# ===========================================================================
# 配置读取
# ===========================================================================
def _nav_cfg(ctx: Optional[GameContext] = None, cfg=None) -> Dict:
    """取 coords.yaml 的 nav 段（缺失则返回空 dict）。"""
    src = cfg if cfg is not None else getattr(ctx, "cfg", None)
    if src is None:
        return {}
    coords = getattr(src, "coords", None) or {}
    return coords.get("nav") or {}


def chain_of(cfg=None) -> List[str]:
    """页面顺序。"""
    nav = _nav_cfg(cfg=cfg)
    seq = list(nav.get("chain") or [])
    return seq or list(DEFAULT_CHAIN)


def steps_of(cfg=None) -> Dict[str, Dict]:
    """前进边：{页面: {screen, element, wait}}。"""
    nav = _nav_cfg(cfg=cfg)
    return dict(nav.get("steps") or DEFAULT_STEPS)


def backs_of(cfg=None) -> Dict[str, Dict]:
    """回退边：{页面: {screen, element, wait}}。"""
    nav = _nav_cfg(cfg=cfg)
    return dict(nav.get("back") or DEFAULT_BACK)


# ===========================================================================
# 单次点击
# ===========================================================================
def _tap(ctx: GameContext, step: Dict, tag: str) -> bool:
    """按坐标表点一次。返回是否成功发出点击。"""
    screen = step.get("screen", "")
    element = step.get("element", "")
    pt = ctx.cfg.point(screen, element)
    if not pt:
        ctx.log.error("坐标表缺少 %s.%s，无法点击", screen, element)
        return False
    x, y = int(pt[0]), int(pt[1])
    ctx.log.info("%s：点击 %s.%s @ (%d, %d)", tag, screen, element, x, y)
    ctx.device.tap(x, y)
    return True


def _wait(ctx: GameContext, step: Dict) -> None:
    time.sleep(float(step.get("wait", 1.6)))


# ===========================================================================
# 前进 / 回退
# ===========================================================================
def forward(ctx: GameContext, frm: str = "home",
            to: Optional[str] = None) -> bool:
    """从 ``frm`` 逐级前进到 ``to``（默认走到链尾）。"""
    seq = chain_of(ctx.cfg)
    if frm not in seq:
        ctx.log.error("未知起始页面: %s（可用: %s）", frm, seq)
        return False
    to = to or seq[-1]
    if to not in seq:
        ctx.log.error("未知目标页面: %s（可用: %s）", to, seq)
        return False

    steps = steps_of(ctx.cfg)
    for cur in seq[seq.index(frm):seq.index(to)]:
        step = steps.get(cur)
        if not step:
            ctx.log.error("页面「%s」没有配置前进边", cur)
            return False
        if not _tap(ctx, step, step.get("desc") or "前进"):
            return False
        _wait(ctx, step)
    ctx.log.info("已到达「%s」", to)
    return True


def back(ctx: GameContext, frm: str, to: Optional[str] = None) -> bool:
    """从 ``frm`` 用右上角返回键逐级退回 ``to``（默认退回链首的主页）。

    落点验证（2026-11-12）：局终后游戏会弹「战报翻页/本局战绩」，盲点返回
    会先落在这些页上——导航曾谎报成功（实际停在战报页）。现在每走完
    退链用一页 OCR 关键词验证目标页；不对就再按一次右上角返回（最多 2 次）。
    """
    seq = chain_of(ctx.cfg)
    if frm not in seq:
        ctx.log.error("未知起始页面: %s（可用: %s）", frm, seq)
        return False
    to = to or seq[0]

    backs = backs_of(ctx.cfg)
    # 要点击的页面：从 frm 起（含）逐层回到 to 的下一层（不含）
    for cur in reversed(seq[seq.index(to) + 1:seq.index(frm) + 1]):
        step = backs.get(cur)
        if not step:
            ctx.log.error("页面「%s」没有配置返回键", cur)
            return False
        if not _tap(ctx, step, step.get("desc") or "回退"):
            return False
        _wait(ctx, step)
    return _verify_landing(ctx, to) or _retry_back_to(ctx, to, backs)


#: 目标页地标词（OCR 验证用；局外页面不做模板锚点，关键词足够便宜）
LANDMARKS: Dict[str, tuple] = {
    "home": ("招募", "竞技", "煮酒", "山河雄师"),
    "campaign": ("千里单骑", "单人挑战玩法"),
    "qianli": ("开始挑战", "难度选择"),
}


def _landmark_hit(ctx: GameContext, page: str) -> bool:
    """整屏 OCR 一次，看目标页地标词是否出现（GPU ~0.25s）。"""
    kws = LANDMARKS.get(page)
    if not kws:
        return True                      # 没登记地标就不验证（保持旧行为）
    items = ctx.ocr.read(ctx.device.screenshot())
    texts = "".join("".join(str(it.text).split()) for it in items)
    hit = any(k in texts for k in kws)
    if not hit:
        ctx.log.warning("落点验证失败：页面未见 %s 的地标词 %s",
                        page, "/".join(kws))
    return hit


def _verify_landing(ctx: GameContext, page: str) -> bool:
    if _landmark_hit(ctx, page):
        ctx.log.info("落点验证通过（%s）", page)
        return True
    return False


def _retry_back_to(ctx: GameContext, page: str, backs: Dict) -> bool:
    """目标页没到：再按右上角返回（弹窗/战报遮挡场景），最多 2 次。"""
    step = backs.get(page) or backs.get("campaign") or {}
    for i in range(2):
        ctx.log.warning("第 %d 次补按返回键，重试回到「%s」", i + 1, page)
        if step and not _tap(ctx, step, "补按返回"):
            return False
        time.sleep(float(step.get("wait", 1.5)))
        if _landmark_hit(ctx, page):
            ctx.log.info("补按后落点验证通过（%s）", page)
            return True
    ctx.log.error("回退「%s」失败：补按返回后仍未见到目标页地标", page)
    return False


def navigate(ctx: GameContext, target: str = "qianli",
             frm: str = "home") -> bool:
    """从 ``frm`` 走到 ``target``（可前进、可回退，都是固定坐标）。"""
    seq = chain_of(ctx.cfg)
    if target not in seq or frm not in seq:
        ctx.log.error("未知页面: frm=%s target=%s（可用: %s）", frm, target, seq)
        return False

    fi, ti = seq.index(frm), seq.index(target)
    if fi == ti:
        ctx.log.info("已在目标页面「%s」，无需导航", target)
        return True
    if fi < ti:
        return forward(ctx, frm=frm, to=target)
    return back(ctx, frm=frm, to=target)
