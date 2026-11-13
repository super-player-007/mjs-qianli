"""千里单骑自动串联执行器：从入口页一键跑完整局。

状态机（每步：截图 → OCR → classify → 执行动作）
--------------------------------------------------
    entry            选将（复用 hero.select_hero）→ 点「开始挑战」
    map              识别节点 → select_node 按优先级选 → 点击（本体节点点两次）
    battle_confirm   「开始对局」
    mulligan         换手牌弹窗 → 固定「取消」
    battle           托管两连击（含验证重试）→ 等待
    victory_blank    「点击空白区域到下一步」→ 点空白
    next_preview     对手预览「下一步」
    settle_confirm   本局战绩「确认」
    gift1/gift2      赠礼两级（gift.py 规则，OCR 实时坐标）
    rest             安营驻寨（rest.py 规则）
    shop             巴清小铺子（shop.py 规则：余额 ≥ 想要商品价 → 买，否则退出）
    purchase_confirm 购买确认「N购买」
    shop_exit        「是否结束购买?」→ 确认
    hero_event_confirm / hero_event_choice   武将事件两级（hero_event.py 规则）
    run_settle       领取奖励 → 恭喜获得浮层关闭（点「点击空白处关闭」文字位）
    unknown          存截图 → 停机（绝不瞎点）

⚠ 关键判定（用户 2026-09-17 澄清）：战斗结束界面无论胜负都显示「胜利」，
不能用它判胜负；战胜/战败的分流靠**后续流程**——出下一层预览=继续，直接结算页=局终。
"""
from __future__ import annotations

import re
import time
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

import cv2
import numpy as np

from src.devices.adb import DeviceError
from src.game import (ambush, anchor_table, event_node, gift, hero_event,
                      invite, rest, shop, settle_page, task_page)
from src.game.node_icon import (NODE_SELECTION_PRIORITY, analyze_nodes,
                                load_node_templates,
                                recover_classified_node, select_node)

STATE_OK = "ok"
STATE_DONE = "done"
STATE_STOP = "stop"

#: 点击后等待的全局缩放系数（用户 2026-09-17 要求整体加快一点）。
#: 所有 _tap 的 wait 都乘此系数；想再调快慢只改这一个数（1.0=原速）。
TAP_WAIT_SCALE = 0.7


#: 托管等待的**局部 OCR 检查区域**：右上角「取消托管」按钮区
#: （实测 x1797–1908 y262–297，多张截图一致；区域放宽留余量）。
#: 面积约为整屏的 1/10，OCR 耗时同比下降。
TRUSTEE_CHECK_REGION = (1400, 100, 1920, 500)

#: 底部流程锚点区域：完胜页/下一步/战绩页的关键词都在这里
#: （完胜页的「点击空白区域到下一步」y947–983）。⚠ 战斗胜利后右上角
#: 的「取消托管」HUD **会残留在完胜页上**（2026-09-25 事故）——只查右上
#: 会永远等不到按钮消失，必须加查底部锚点识别"其实已经打完了"。
BOTTOM_FLOW_REGION = (500, 840, 1500, 1010)
BOTTOM_FLOW_KEYWORDS = ("点击空白区域到下一步", "下一步", "本局战绩")

#: 任务奖励巡检间隔（秒，用户 2026-10-07 改：累计 5 分钟一次，原 600）
TASK_CHECK_INTERVAL = 300
#: 托管界面顶部「任务」图标（2026-09-25 战斗页 OCR 标定：OCR 将「任务」「设置」
#: 合并读为 x1585–1772 的盒子，任务图标=左半 → 中心 (1620,150)。
#: ⚠ 旧值 (1638,187) 偏下 37px（用户窗口截图换算误差），实测点不开任务页）
TASK_ICON_POS = (1620, 150)
#: 任务页右上角「返回」按钮（用户截图标定）
TASK_BACK_POS = (1879, 183)

#: 局内状态集合：见到任何一个即认定"本局真跑过"（entry/resume/reward_overlay 除外）
_RUN_STATES = frozenset({
    "map", "battle", "battle_confirm", "mulligan",
    "gift1", "gift2", "rest", "shop", "purchase_confirm", "shop_exit",
    "hero_event_confirm", "hero_event_choice", "divination",
    "tap_continue", "hero_info", "tip_screen", "refresh_confirm",
    "settle_confirm", "next_preview", "victory_blank", "run_settle",
})


def _norm(s: str) -> str:
    return "".join(s.split())


def _has(items: Sequence, *keywords: str) -> bool:
    for it in items:
        t = _norm(getattr(it, "text", ""))
        for k in keywords:
            if k and k in t:
                return True
    return False


class AutoRunner:
    """单局自动执行器（支持暂停/停止/统计，供 GUI 调用）。"""

    def __init__(self, ctx, log, hero_name: str = "钟离眜",
                 tpl_dir: Optional[Path] = None,
                 max_steps: int = 2000,
                 poll_sleep: float = 0.5,
                 tap_scale: float = TAP_WAIT_SCALE,
                 node_priority: Optional[Sequence[str]] = None):
        self.ctx = ctx
        self.log = log
        self.hero_name = hero_name
        self.max_steps = max_steps
        self.poll_sleep = poll_sleep
        #: 点击等待缩放（GUI「点击时间间隔」可调）
        self.tap_scale = tap_scale
        #: 节点优先级覆盖（GUI 可自定义排序；None/空=用默认表）
        # 2026-09-25 修复：None 直接透传会在 _act_map 崩溃（select_node 收到
        # None），GUI 路径总传列表所以没炸过；这里兜底到默认表。
        self.node_priority: Sequence[str] = (
            list(node_priority) if node_priority
            else list(NODE_SELECTION_PRIORITY))
        #: 暂停/停止（threading.Event，GUI 线程 set/clear）
        self.pause_event = None
        self.stop_event = None
        #: 实时统计（GUI 轮询读取）
        self.stats = {"clicks": 0, "layer": 0, "run": 0, "runs": 1,
                      "state": "idle", "msg": "", "step_s": 0.0,
                      "steps": 0}
        self._status_cb = None
        self.tpl_dir = Path(tpl_dir or "assets/templates/run_map")
        #: 任务页按钮模板（领取奖励/刷新，2026-10-07 模板匹配提速）
        self._task_templates = task_page.load_task_templates(
            self.tpl_dir.parent / "task")
        #: 结算链状态模板（下一步/确认/领取奖励/恭喜获得，2026-10-09 提速）
        self._settle_templates = settle_page.load_settle_templates(
            self.tpl_dir.parent / "settle")
        #: 邀请弹窗模板（忽略按钮，2026-10-11）
        self._invite_templates = invite.load_invite_templates(
            self.tpl_dir.parent / "invite")
        #: 锚点表（2026-11-11 阶段 1）：数据驱动的页面快速分类，
        # 固定区域小模板 AND 匹配，已知页面免整屏 OCR。
        # 刷新任务弹窗的锚点也在表内（refresh_confirm, needs_ocr=True）。
        self._anchor_entries = anchor_table.load_anchor_table(
            self.tpl_dir.parent.parent / "screen_info/anchors.yml",
            self.tpl_dir.parent / "anchors")
        #: 任务面板「领取」徽章变体（2026-10-23）：不进 task_page 全局池
        #（外观大众脸会挤占 NMS 槽位），仅 _claim_task_badges 以 0.9 独立用
        self._claim2_tpl = self._load_gray(
            self.tpl_dir.parent / "task/btn_claim2.png")
        #: 帧复用缓存（2026-11-11 操作序列架构）
        self._frame = None
        self._frame_ts = 0.0
        #: 最近一次就绪探测命中的帧（2026-11-12，供序列复用免重复截图）
        self._probe_frame = None
        #: 本步判页用的帧（2026-11-12，结算序列首个判页直接复用）
        self._classify_img = None
        #: 灰度图按帧缓存（2026-11-12 CPU 优化，见 _gray）
        self._gray_cache = None
        self.last_gift_hero: Optional[str] = None
        self.layer = 0
        self.steps = 0
        self.in_run = False   # 见 _RUN_STATES：本局是否真跑过（防假收官）
        #: 事件节点选完中间后，下一屏预期是结果确认页（防「确认」撞其他页面）
        self.expect_event_confirm = False
        #: 连续 unknown 帧计数（过渡/未知界面容忍，2026-09-24/25 事故演进）
        self._unknown_streak = 0
        #: 上次任务奖励巡检时间（累计 10 分钟触发一次，用户 2026-09-25 需求）
        self._last_task_check = time.time()
        self.shot_dir = getattr(getattr(ctx, "cfg", None), "shot_dir",
                                Path("runtime/shots"))

    # ------ GUI 集成 ------
    def set_control(self, pause_event, stop_event, status_cb=None) -> None:
        """注入 GUI 的暂停/停止事件与状态回调。"""
        self.pause_event = pause_event
        self.stop_event = stop_event
        self._status_cb = status_cb
        self.stats["runs"] = 1

    def _publish(self, state: str, msg: str = "") -> None:
        self.stats["state"] = state
        self.stats["msg"] = msg
        self.stats["layer"] = self.layer
        if self._status_cb:
            try:
                self._status_cb(dict(self.stats))
            except Exception:  # noqa: BLE001
                pass

    def _wait_if_paused(self) -> bool:
        """暂停时阻塞；返回 False 表示被要求停止。"""
        if self.pause_event is None:
            return True
        while self.pause_event.is_set():
            self._publish("paused")
            if self.stop_event is not None and self.stop_event.is_set():
                return False
            time.sleep(0.3)
        return not (self.stop_event is not None and self.stop_event.is_set())

    # ------------------------------------------------------------ 基础
    def _shot(self, fresh: bool = False):
        """截图（帧复用 2026-11-11）：0.35s 内的同一帧不重复截。

        ``fresh=True`` 强制重新截图——**探测循环必须用 fresh**
        （2026-11-11 事故：探测间隔 0.28s < 缓存 0.35s，探测永远看到
        同一张旧帧，每次白等满超时，序列反而更慢）。
        任何点击都会失效缓存（_tap），避免复用陈旧画面。
        """
        if not fresh:
            now = time.time()
            if self._frame is not None and now - self._frame_ts < 0.35:
                return self._frame
        img = self.ctx.device.screenshot()
        self._frame = img
        self._frame_ts = time.time()
        return img

    def _ocr(self, img, region=None):
        return self.ctx.ocr.read(img, region=region)

    @staticmethod
    def _load_gray(path: Path):
        """读灰度模板（中文路径安全），文件不存在返回 None。"""
        import cv2
        p = Path(path)
        if not p.exists():
            return None
        img = cv2.imdecode(np.fromfile(str(p), dtype=np.uint8),
                           cv2.IMREAD_COLOR)
        return None if img is None else cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    def _tap(self, x: int, y: int, wait: float = 2.0):
        self.ctx.tap_point((int(x), int(y)))
        self._frame = None              # 点击后画面必变，帧缓存失效
        self.stats["clicks"] += 1
        time.sleep(wait * self.tap_scale)

    def _wait_ready(self, probe, timeout: float, interval: float = 0.4) -> bool:
        """点击后就绪探测（2026-10-20 A 优化）：把「睡满固定秒数」变成
        「最长等 timeout 秒、通常提前走」。probe(img) 返回真值即就绪；
        超时返回 False 交回状态机兜底（行为不劣于原固定等待）。
        probe 必须自含廉价识别（模板/局部 OCR）——禁用整屏 OCR（1.9s/次，
        探测就失去意义）。
        """
        end = time.time() + timeout
        t0 = time.time()
        self._probe_frame = None               # 命中帧留给调用方复用
        while True:
            try:
                img = self._shot(fresh=True)   # 探测必须看新帧（见 _shot 注释）
                if probe(img):
                    cost = time.time() - t0
                    if cost > 0.8:
                        self.log.info("就绪探测：命中，用时 %.1fs", cost)
                    # 2026-11-12：把已确认的就绪帧交给调用方（结算序列判页
                    # 直接用它，不再多截一张 —— 实测每张 raw 帧 ~0.45s）
                    self._probe_frame = img
                    self._frame, self._frame_ts = img, time.time()
                    return True
            except Exception:  # noqa: BLE001 — 截图/探测失败按未就绪
                pass
            if time.time() >= end:
                self.log.info("就绪探测：超时 %.1fs（页面未在时限内出现）",
                              time.time() - t0)
                return False
            time.sleep(interval * self.tap_scale)

    def _probe_or_shot(self):
        """返回最近一次就绪探测命中的帧（不存在则新截一张）。

        2026-11-12：探测命中即已确认页面身份，紧邻的判页/二次判断直接复用
        该帧，省一张 raw 截图（~0.45s）。
        """
        if self._probe_frame is not None:
            return self._probe_frame
        return self._shot(fresh=True)

    def _gray(self, img):
        """按帧缓存的灰度图（2026-11-12 CPU 优化）。

        同一步里判页 / 锚点探针 / 选节点会对**同一帧**做 3-5 次灰度转换
        （每次约 1ms，纯浪费）。这里用对象身份缓存最近一帧的灰度。
        """
        if img is None:
            return None
        ndim = getattr(img, "ndim", 0)
        if ndim == 2:
            return img
        if ndim != 3:
            return None            # 非图像对象（测试桩/坏帧）→ 按未命中处理
        cached = self._gray_cache
        if cached is not None and cached[0] is img:
            return cached[1]
        g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        self._gray_cache = (img, g)
        return g

    def _anchor_state(self, img) -> Optional[str]:
        """锚点表判页 → 状态名（未命中 None）。"""
        try:
            if img is None or getattr(img, "ndim", 0) != 3:
                return None
            entry = anchor_table.match_entry(self._gray(img),
                                            self._anchor_entries,
                                            in_run=self.in_run)
            return entry.state if entry is not None else None
        except Exception:  # noqa: BLE001 — 判页失败按未命中
            return None

    def _anchor_entry(self, img):
        """锚点表判页 → AnchorEntry（None=未命中）。"""
        try:
            if img is None or getattr(img, "ndim", 0) != 3:
                return None
            return anchor_table.match_entry(self._gray(img),
                                            self._anchor_entries,
                                            in_run=self.in_run)
        except Exception:  # noqa: BLE001
            return None

    def _anchor_is(self, *states: str):
        """探针工厂：锚点表判页结果属于给定状态集才算就绪。"""
        def probe(img) -> bool:
            return self._anchor_state(img) in states
        return probe

    def _run_steps(self, steps, label: str) -> bool:
        """操作序列（OneDragon operation round 模式）：
        每步 = 点击 → 等待目标画面（模板/锚点探针）。
        任一步超时 → 立即返回 False，交回主循环兜底（行为不劣于旧逻辑）。
        steps: [{"tap": (x,y), "wait": 0.4, "probe": callable|None,
                 "timeout": 3.0, "label": str, "if": callable|None}]
        """
        for st in steps:
            cond = st.get("if")
            if cond is not None and not cond(self._shot()):
                continue                      # 条件步不满足 → 跳过
            self._tap(*st["tap"], wait=st.get("wait", 0.4))
            probe = st.get("probe")
            if probe is not None and not self._wait_ready(
                    probe, timeout=st.get("timeout", 3.0)):
                self.log.info("操作序列[%s] %s 等待超时 → 交回主循环",
                              label, st.get("label", "?"))
                return False
        return True

    def _settle_kind(self, img) -> Optional[str]:
        """结算页细分（2026-11-11）：blank=完胜空白（只有提示条）/
        preview=预览页（有下一步按钮）/confirm=战绩页。"""
        e = self._anchor_entry(img)
        if e is None:
            return None
        if e.state == "settle_confirm":
            return "confirm"
        if e.state == "next_preview":
            # 两条 next_preview 锚点：按钮变体区域 x>=800，提示条变体 x<800
            return "preview" if e.areas[0].rect[0] >= 800 else "blank"
        return None

    def _settle_sequence(self) -> Tuple[str, str]:
        """结算链操作轮（2026-11-11）：空白/下一步/确认 在一个动作内完成。

        每轮按锚点细分判页决定点哪里，点完等下一页就绪：
          blank（完胜空白）→ 点空白 → 等 preview/confirm
          preview（预览页） → 点下一步 → 等 confirm
          confirm（战绩页） → 点确认 → 收工
        """
        # 首帧优先复用「本步判页用的那一帧」（_classify_img，结论刚由它得出，
        # 不存在额外陈旧风险）；否则才新截。之后每轮复用上一轮就绪探测命中
        # 的那一帧。每省一张 raw 帧 ≈ 0.45s。
        first = (self._classify_img if self._classify_img is not None
                 else self._shot(fresh=True))
        self._classify_img = None          # 只复用一次，避免误用陈旧帧
        self._claim_task_badges(first)
        taps = []
        img = first
        for _ in range(3):
            t0 = time.time()
            kind = self._settle_kind(img)
            self.log.info("结算序列：判页=%s（%.0fms）", kind,
                          (time.time() - t0) * 1000)
            if kind == "blank":
                self._tap(958, 953, wait=0.3)
                taps.append("空白")
                self._wait_ready(self._anchor_is("next_preview",
                                                 "settle_confirm"),
                                 timeout=3.0)
            elif kind == "preview":
                self._tap(958, 953, wait=0.3)
                taps.append("下一步")
                self._wait_ready(self._anchor_is("settle_confirm"),
                                 timeout=3.0)
            elif kind == "confirm":
                self._tap(960, 953, wait=0.3)   # 2026-11-12：确定按钮下移到 y≈953
                taps.append("确认")
                break                         # 确认后离开结算链
            else:
                break
            # ⚠ 不能用 `or`：ndarray 的真值判断会抛 ValueError
            img = (self._probe_frame if self._probe_frame is not None
                   else self._shot(fresh=True))
        return STATE_OK, f"结算序列（{'→'.join(taps) or '已无结算页'}）"

    def _settle_probe(self, current: str):
        """结算链就绪探针：页面切换到**另一个**已识别结算态才算就绪。
        current 不在模板态集合里（如 victory_blank，OCR 态）时视为 "none"，
        探测「出现任意结算模板页」。"""
        states = {"next_preview", "settle_confirm", "run_settle",
                  "reward_overlay"}
        tag = current if current in states else "none"

        def probe(img) -> bool:
            st = settle_page.match_state(img, self._settle_templates,
                                         ocr_fn=self._ocr)
            return (st or "none") != tag and st is not None

        return probe

    def _state_items(self):
        """截图 + 整屏 OCR。"""
        img = self._shot()
        return img, self._ocr(img)

    def _save(self, img, tag: str):
        try:
            from src.vision.annotate import save
            save(img, Path(self.shot_dir) / f"auto_{tag}.png")
        except Exception:  # noqa: BLE001
            pass

    # ------------------------------------------------------------ 分类
    def classify(self, items) -> str:
        if _has(items, "是否需要更换初始手牌"):
            return "mulligan"
        if gift.detect_gift_options(items):
            return "gift2"
        if gift.detect_gift_heroes(items):
            return "gift1"
        if ambush.is_ambush_page(items):
            # 偷袭事件：底部「与XX、XX战斗」按钮（敌方名每局变），点按钮进战斗
            return "ambush"
        if _has(items, "安营驻寨"):
            return "rest"
        if event_node.is_event_node_page(items):
            # 事件节点（钱袋）内部：底部横排【】选项，固定选中间
            return "event_node_choice"
        if _has(items, "是否结束购买"):
            return "shop_exit"
        if re.search(r"\d+购买", _has_join(items)):
            return "purchase_confirm"
        if _has(items, "小铺子") or _has(items, "信物专区"):
            return "shop"
        if _has(items, "今日登录不再提示") or _has(items, "消耗军令状"):
            # 刷新任务确认弹窗（2026-10-18）：勾选「今日登录不再提示」→确定
            return "refresh_confirm"
        if _has(items, "温馨提示"):
            # 战斗加载过场（武将立绘+提示语+左下跳过箭头），点跳过后进战斗
            return "tip_screen"
        if _has(items, "请点击卡牌完成卜卦") or _has(items, "卜卦"):
            return "divination"
        if _has(items, "请点击继续"):
            return "tap_continue"
        if _has(items, "武将技能") and _has(items, "武将信息"):
            return "hero_info"
        if _has(items, "请选择一项", "请选择一种"):
            # 事件池选项页的两种已知开头（十二阉人/朏朏=一项，墨家巨子=一种）。
            # ⚠ 不能泛化成裸「请选择一」——战斗选人提示「请选择一名其他角色」
            # 会被误吞（2026-09-21 01:37 事故：战斗页被判成事件页 → 决策失败停机）。
            # 以后出新的「请选择一X」事件页时，把 X 显式加进这里。
            return "hero_event_choice"
        if _has(items, "再想一想") and _has(items, "选择事件", "选择式将", "选择武将"):
            # 武将类事件确认页：十二阉人=「选择事件」，疯疯老道=「选择式将」，
            # 卧龙出山 OCR 把「式将」读成「武将」→ 三个都认（2026-09-17）。
            # 必须同时有「再想一想」：入口页引导卡也有「选择武将」但没有它。
            return "hero_event_confirm"
        if _has(items, "领取奖励"):
            return "run_settle"
        if _has(items, "恭喜获得"):
            return "reward_overlay"
        if _has(items, "本局战绩") and _has(items, "确认", "确定"):
            return "settle_confirm"
        if _has(items, "下一步"):
            return "next_preview"
        if _has(items, "点击空白区域到下一步") or _has(items, "点击空白处关闭"):
            return "victory_blank"
        if _has(items, "开始对局"):
            return "battle_confirm"
        if _has(items, "结束挑战") and _has(items, "当前挑战"):
            return "map"
        if _has(items, "结束出牌", "打出一张牌", "取消托管", "离开中") or \
                _has_round(items):
            return "battle"
        if _has(items, "确认") and not _has(items, "再想一想", "取消", "购买",
                                             "本局战绩", "领取奖励", "下一步",
                                             "结束挑战", "开始对局"):
            # 孤立「确认」页（2026-09-18）：事件节点结果页（虎符在手+效果+确认）
            # 等只有单个确认按钮的界面。⚠ 必须放在所有特定锚点分支之后，
            # 且排除一切"确认+其他按钮"的组合页——否则会撞战绩页/结束购买页。
            # 之前靠 expect_event_confirm 标志位，但多局连跑时上一局遗留的
            # 确认页在新一轮开局标志位是 False → unknown 停机（实测踩坑）。
            return "confirm_only"
        if _has(items, "丹青阁") and _has(items, "招募"):
            # 游戏主页（顶部导航 OCR conf=1.00；卡片艺术字不可靠不用）
            return "home"
        if _has(items, "开始挑战") and _has(items, "战役属性", "选择武将", "难度选择"):
            return "entry"
        if _has(items, "继续挑战") and _has(items, "战役属性", "难度选择"):
            # 上局被中断（如执行器中途停机）：点「继续挑战」接上挂起流程
            return "resume"
        return "unknown"

    # ------------------------------------------------------------ 动作
    def step(self) -> Tuple[str, str]:
        """执行一步，返回 (状态结果, 说明)。"""
        self.steps += 1
        t_step = time.time()
        img = self._shot()
        #: 本步判页用的这一帧（2026-11-12）：结算序列直接复用，免再截一张
        self._classify_img = img
        # 邀请弹窗前置检查（2026-10-11 用户需求）：弹窗可能盖在**任何界面**
        # 之上，模板匹配「忽略」按钮（~40ms），命中即点掉再继续状态识别
        invite_btn = invite.find_ignore_button(img, self._invite_templates)
        if invite_btn is not None:
            self._tap(*invite_btn, wait=2.5)
            self.log.info("游戏邀请弹窗 → 忽略 %s", invite_btn)
            return STATE_OK, "忽略游戏邀请"
        state = None
        items = None
        # 第 1 层：锚点表（2026-11-11 阶段 1 试点）——固定区域小模板匹配
        # （~0.1-0.3s），已知页面免整屏 OCR。yml 见 assets/screen_info/。
        gray = self._gray(img) if img is not None else None
        entry = anchor_table.match_entry(gray, self._anchor_entries,
                                         in_run=self.in_run)
        if entry is not None:
            state = entry.state
            self.log.info("锚点表命中 state=%s (%s)", state,
                          entry.areas[0].rect)
            if entry.needs_ocr:
                # 决策页：优先只 OCR 内容区域（2026-11-11，整屏 1.9s -> 0.4s）
                items = (self._ocr(img, region=entry.ocr_region)
                         if entry.ocr_region else self._ocr(img))
        else:
            # 第 2 层：结算链快速路径（2026-10-09）4 状态模板 ~0.13s。
            state = settle_page.match_state(img, self._settle_templates,
                                            ocr_fn=self._ocr)
            if state is not None:
                # 快速路径审计抓拍（2026-10-21）：每个模板态首帧留档一次，
                # 用于发现模板互相污染（2026-10-21 完胜页 98 场 0 次
                # victory_blank 事故靠这个抓现行）。
                try:
                    fp = Path("runtime/shots") / f"fp_{state}.png"
                    if not fp.exists():
                        self._save(img, f"fp_{state}")
                except Exception:  # noqa: BLE001 — 留档失败不影响主流程
                    pass
            else:
                # 第 3 层：整屏 OCR 分类（只有真正未知的页面才走）
                items = self._ocr(img)
                state = self.classify(items)
        self.log.info("step=%d state=%s", self.steps, state)
        # 「真跑过本局」标记：见到任何局内状态就置位。
        # 用于区分"本局的结算"和"上一局遗留的奖励浮层"（多局连跑时后者
        # 会在下一局开局时出现，2026-09-17 第 4 局 7 秒假收官的教训）。
        if state in _RUN_STATES:
            self.in_run = True

        # unknown 容忍等待（2026-09-24/25 两次事故演进）：
        # 过渡帧有两种形态——①零文字模糊画面 ②带零星无关词（如左下「背包」
        # 按钮）。②曾漏网：只判"零文字"接不住。现放宽为**所有 unknown 一律
        # 先等待重看**（连续 12 帧 ≈ 30s+）；仍不认识才停机存图等人工。
        # 新界面采集只多花 30 秒，换过渡动画不再停机。
        if state == "unknown":
            self._unknown_streak += 1
            if self._unknown_streak <= 12:
                # 2026-11-12 盲睡改锚点主动探测：过渡动画实测 0.5~1.5s 就
                # 结束，原实现睡满 2.5s 再重看，选节点后每次白等 ~2s。
                # 现在每 0.5s 抓一帧只跑锚点表（48ms，不烧 OCR），命中即
                # 返回重看（下一步锚点先行 0ms 判页）；锚点不认识的过渡
                # （如休息页）仍睡满原时长兜底，行为不劣于改前。
                self._wait_transition_settled()
                return (STATE_OK,
                        f"过渡/未知帧 {self._unknown_streak}/12，等待重看")
            self._unknown_streak = 0
            self._save(img, "unknown_stuck")
            return STATE_STOP, "连续 12 帧未知界面，停机等人工（截图已存）"
        self._unknown_streak = 0

        if state == "resume":
            self._tap(1653, 933, wait=4.0)
            return STATE_OK, "继续挑战（恢复上局）"

        if state == "home":
            # 复用既有固定坐标导航（home→campaign→qianli，同 run.py enter）
            from src.game.nav import navigate
            ok = navigate(self.ctx, target="qianli", frm="home")
            return (STATE_OK if ok else STATE_STOP), "主页→千里单骑入口"

        if state == "entry":
            ok = self._select_hero_and_start()
            return (STATE_OK if ok else STATE_STOP), "选将并开始挑战"

        if state == "map":
            return self._act_map()

        if state == "battle_confirm":
            # 开战序列（2026-11-11）：开始对局 → 换牌弹窗（有则取消）→ 战斗页
            self._tap(708, 920, wait=0.4)
            self._wait_ready(self._anchor_is("mulligan", "battle", "tip_screen"),
                             timeout=5.0)
            if self._anchor_state(self._probe_or_shot()) == "mulligan":
                self._tap(1105, 622, wait=0.4)     # 取消换牌
                self._wait_ready(self._anchor_is("battle"), timeout=3.0)
            return STATE_OK, "开战序列（开始对局→换牌取消）"

        if state == "mulligan":
            # 2026-09-24/25 用户两次要求累计 +2s（2.0→4.0，实际 4.0×tap_scale）：
            # 弹窗收场动画需要时间，避免金盘点空
            self._tap(1105, 622, wait=4.0)
            return STATE_OK, "换手牌→取消"

        if state == "battle":
            return self._act_battle(items)

        if state == "victory_blank":
            return self._settle_sequence()

        if state == "next_preview":
            return self._settle_sequence()

        if state == "settle_confirm":
            return self._settle_sequence()

        if state == "gift1":
            return self._act_gift1(items)

        if state == "gift2":
            return self._act_gift2(items)

        if state == "event_node_choice":
            from src.game import event_node
            pt, why = event_node.pick_event_node_option(items)
            self.log.info("事件节点: %s", why)
            self._tap(*pt, wait=3.0)
            # 选完后还有一页结果确认（虎符在手+效果+「确认」按钮），点确认才回地图
            self.expect_event_confirm = True
            return STATE_OK, "事件节点选中间"

        if state == "confirm_only":
            # 点「确认」的 OCR 实时位置（各确认页按钮位置可能不同，禁止写死）
            pt = (964, 865)                     # 兜底：事件结果确认页实测位
            for it in items:
                t = _norm(getattr(it, "text", ""))
                if t == "确认":
                    x1, y1, x2, y2 = it.rect
                    pt = ((x1 + x2) // 2, (y1 + y2) // 2)
                    break
            self.expect_event_confirm = False
            self._tap(*pt, wait=3.0)
            return STATE_OK, f"孤立确认页 → 点确认 {pt}"

        if state == "ambush":
            pt, why = ambush.pick_ambush_button(items)
            if pt is None:
                return STATE_STOP, f"偷袭事件按钮识别失败：{why}"
            self.log.info("偷袭: %s", why)
            self._tap(*pt, wait=3.0)
            return STATE_OK, "偷袭 → 进战斗"

        if state == "rest":
            return self._act_rest(items)

        if state == "shop":
            return self._act_shop(items)

        if state == "purchase_confirm":
            self._tap(743, 745, wait=2.5)
            return STATE_OK, "确认购买"

        if state == "shop_exit":
            self._tap(823, 690, wait=2.5)
            return STATE_OK, "结束购买确认"

        if state == "refresh_confirm":
            return self._act_refresh_confirm(items)

        if state == "tip_screen":
            # 「温馨提示」两种形态：
            # ① 带「确定/取消」按钮的确认弹窗（2026-10-07 军令状刷新弹窗）
            #    → 用户 2026-10-07 定：点确认，花军令状继续刷任务
            # ② 过场提示（无按钮）→ 左下跳过箭头
            for it in items or []:
                if "确定" in str(getattr(it, "text", "")):
                    x1, y1, x2, y2 = it.rect
                    self._tap((x1 + x2) // 2, (y1 + y2) // 2, wait=2.5)
                    return STATE_OK, "温馨提示 → 确认（花军令状刷任务）"
            self._tap(185, 483, wait=2.5)   # 左下跳过箭头
            return STATE_OK, "过场提示跳过"

        if state == "divination":
            # 卧龙出山卜卦：点卡牌两次完成（2026-09-17 实测）
            self._tap(1385, 540, wait=2.0)
            self._tap(1385, 540, wait=3.0)
            return STATE_OK, "卜卦点卡两次"

        if state == "tap_continue":
            self._tap(928, 942, wait=2.5)
            return STATE_OK, "点击继续"

        if state == "hero_info":
            self._tap(1800, 250, wait=2.0)
            return STATE_OK, "关闭武将信息弹层"

        if state == "hero_event_confirm":
            self._tap(710, 917, wait=3.0)
            return STATE_OK, "选择事件"

        if state == "hero_event_choice":
            return self._act_hero_event(items)

        if state == "run_settle":
            # 胜利页任务面板的可领取徽章：先领再翻页（2026-10-23）
            if self._claim_task_badges(img):
                img = self._shot()
            self._tap(959, 942, wait=0.4)
            self._wait_ready(self._settle_probe("run_settle"), timeout=3.0)
            return STATE_OK, "领取奖励"

        if state == "reward_overlay":
            # 2026-11-12 游戏更新：「点击空白处关闭」上移到 y≈791
            self._tap(961, 791, wait=0.4)
            self._wait_ready(self._settle_probe("reward_overlay"), timeout=3.0)
            if self.in_run:
                return STATE_DONE, "奖励已领，本局结束"
            return STATE_OK, "关闭上一局遗留的奖励浮层（不算收官）"

        self._save(img, f"unknown_step{self.steps}")
        return STATE_STOP, f"未知界面（state=unknown），已存图，停机等人工"

    def _act_refresh_confirm(self, items) -> Tuple[str, str]:
        """刷新任务确认弹窗（2026-10-18 用户需求）：
        先勾选「今日登录不再提示」复选框，再点「确定」——
        当天后续刷新不再弹窗。坐标 OCR 实时定位；
        兜底固定值按弹窗居中标定（刷新任务标题 (882,334)-(1051,373)）。
        """
        box = confirm = None
        for it in items or []:
            t = _norm(getattr(it, "text", ""))
            r = getattr(it, "rect", None)
            if not r:
                continue
            if "今日登录不再提示" in t and box is None:
                box = (int(r[0]) - 45, (r[1] + r[3]) // 2)
            if "确定" in t and confirm is None:
                # 确定按钮含军令状图标（如 OCR 读作「人1确定」），
                # 点右侧确定文字区：x2-45 落在按钮内
                confirm = (int(r[2]) - 45, (r[1] + r[3]) // 2)
        if box is None:
            box = (832, 647)
        if confirm is None:
            confirm = (849, 711)
        self._tap(*box, wait=1.5)       # 勾选复选框
        self._tap(*confirm, wait=2.5)   # 确定
        return STATE_OK, "刷新任务弹窗：勾选不再提示 + 确定"

    # ------------------------------------------------------------ 各状态
    def _select_hero_and_start(self) -> bool:
        from src.game.hero import select_hero
        ok = select_hero(self.ctx, name=self.hero_name)
        if not ok:
            return False
        time.sleep(1.5)
        self._tap(1670, 921, wait=0.5)   # 开始挑战
        # 就绪探测：战斗确认页出现（局部 OCR ~0.3s/次）替代固定睡 5s
        self._wait_ready(
            lambda im: _has(self._ocr(im, region=(500, 650, 1500, 1080)),
                            "开始对局"),
            timeout=5.0, interval=0.5)
        self.layer = 0
        return True

    def _act_map(self) -> Tuple[str, str]:
        for attempt in range(3):
            img = self._shot()
            nodes = analyze_nodes(img, tpl_dir=self.tpl_dir)
            # 兜底（2026-09-20 无尽 35 层实测）：当前列全 unknown 时，
            # 多半是列聚类被装饰假圆反超、真节点（最后一层单节点）被剔——
            # 从全部霍夫圆里找回有类型的节点（取最右 = 当前层）。
            if nodes and all(n.kind == "unknown" for n in nodes):
                rec = recover_classified_node(
                    img, templates=load_node_templates(self.tpl_dir))
                if rec is not None:
                    self.log.warning("当前列全 unknown → 兜底找回节点 %s", rec)
                    nodes = [rec]
            # 每次都留档：遇到未采过的事件节点，事后直接从这张图裁模板
            self._save(img, f"map_L{self.layer + 1}")
            if nodes:
                hit, why = select_node(nodes, priority=self.node_priority)
                if hit is None:
                    self._save(img, "map_no_node")
                    return STATE_STOP, f"选节点失败：{why}"
                self.layer += 1
                self.log.info("第%d层 节点=%s（%s）", self.layer, hit, why)
                self._tap(*hit.tap, wait=0.5)
                # 头像节点（战斗）**一次点击即进入**（已确认规则：只有本体
                # 节点才需要两次），所以战斗节点不需要「节点消失」探测。
                # 2026-11-12 实测：原逻辑对所有节点都跑 3.0s 探测，战斗节点
                # 常因加载动画超时 → 再补一击 1.5s，每层白花约 4.5s。
                if hit.kind == "battle":
                    return STATE_OK, f"选节点 {hit.kind}"
                # 本体节点（休息/商店/武将/伙伴/事件）要点两次；就绪探测：
                # 轮询节点消失（已进入节点界面）→ 免第二次点击；
                # 超时仍可见 → 补第二次点击（原双击兜底）
                # ⚠ 探针必须用 analyze_nodes（节点消失），不能改用「地图锚点不命中」：
                # 休息/商店/事件页不在锚点表里（判页返回 None），且淡入淡出过渡帧
                # 也返回 None —— 会造成「已进入」误判 → 主循环回到地图页时
                # layer 二次自增（层数漂移）。
                entered = self._wait_ready(
                    lambda im: not analyze_nodes(im, tpl_dir=self.tpl_dir),
                    timeout=3.0, interval=0.3)
                if not entered:
                    self._tap(*hit.tap, wait=1.5)
                return STATE_OK, f"选节点 {hit.kind}"
            time.sleep(1.5)
        self._save(img, "map_no_nodes")
        return STATE_STOP, "地图页连续 3 次未识别到节点"

    def _wait_transition_settled(self, timeout: float = 2.5) -> None:
        """unknown 过渡帧的主动探测：锚点一命中就提前结束等待。

        只用锚点表（~50ms/次）不烧 OCR；任何异常按没命中处理，走满原
        等待时长兜底——新界面/非常规过渡的行为与改前完全一致。
        """
        deadline = time.time() + timeout
        while time.time() < deadline:
            time.sleep(0.5)
            try:
                if self._anchor_state(self._shot(fresh=True)) is not None:
                    return
            except Exception:  # noqa: BLE001 — 探测失败按兜底等待处理
                return

    def _poll_heartbeat(self, poll_i: int) -> None:
        """托管轮询心跳（2026-11-12）：进度日志 + 累计 10 分钟任务巡检。

        轮询周期已压到 ~1s（快路径），日志按每 10 轮 ≈ 10s 打一次，
        避免刷屏（原 4s 周期时是每 3 轮 ≈ 12s）。
        """
        if poll_i % 10 == 0:
            self.log.info("托管中，检查 %d（战斗未结束）", poll_i + 1)
            self._publish("running", f"托管中，检查 {poll_i + 1}")
        # 任务奖励巡检（2026-09-25 用户需求）：累计 10 分钟一次，
        # 进任务页领奖（可能多个）→ 刷新 → 返回托管界面
        if time.time() - self._last_task_check >= TASK_CHECK_INTERVAL:
            self._last_task_check = time.time()
            self._task_reward_flow()

    def _act_battle(self, items) -> Tuple[str, str]:
        # 锚点表命中时 items=None（未做整屏 OCR，2026-11-11）：
        # 只对右上角托管区做局部 OCR（~0.3s）补足状态判断。
        if items is None:
            items = self._ocr(self._shot(), region=TRUSTEE_CHECK_REGION)
        if _has(items, "取消托管", "离开中"):
            # 托管已在跑 → 进入**局部轮询**等待（2026-09-25 优化）：
            # 战斗期间只做「廉价信号」确认是否还在打，战斗结束立刻交回。
            empty_streak = 0
            for poll_i in range(600):            # 600 × ~1s ≈ 8 分钟上限
                time.sleep(self.poll_sleep)
                if not self._wait_if_paused():
                    return STATE_STOP, "用户停止"
                img = self._shot(fresh=True)
                # ---- 快路径（2026-11-12）：投降按钮在 = 战斗进行中。
                # 实测事故（00:42 那局）：右上角托管 HUD 在敌方回合会短暂
                # 隐藏，旧逻辑每轮只做一次 OCR 就判「结束」→ 交回主循环
                # 又被判成 battle → 同一场战斗被拆成 **11 个 step** 反复
                # 进出，每轮白睡 2s + 1.4s 开销（约 15s/场）。
                # 2026-11-12 游戏更新：完胜浮层弹出时金盘面板**仍开着**，
                # 「投降」按钮在浮层下持续可见——只看投降会永远判「还在打」，
                # 轮询卡死（用户实测：吕布局打完后卡了 10+ 分钟）。
                # 所以快路径一次锚点判定分两支：先查结算锚点（命中 = 战斗
                # 已结束，立刻交回主流程走结算链），再看投降（还在打）。
                _state = self._anchor_state(img)
                if _state in ("next_preview", "settle_confirm",
                              "run_settle", "reward_overlay"):
                    return (STATE_OK,
                            f"战斗已结束（结算锚点 {_state} 命中），交回主流程")
                if _state == "battle":
                    empty_streak = 0
                    self._poll_heartbeat(poll_i)
                    continue
                region_ocr = self._ocr(img, region=TRUSTEE_CHECK_REGION)
                # ⚠ 完胜页会**残留**取消托管 HUD——按钮在 ≠ 还在打。
                # 加查底部流程锚点：出现即战斗已结束，立刻交回。
                bottom_ocr = self._ocr(img, region=BOTTOM_FLOW_REGION)
                if _has(bottom_ocr, *BOTTOM_FLOW_KEYWORDS):
                    return (STATE_OK,
                            "战斗已结束（底部流程锚点命中），交回主流程")
                if _has(region_ocr, "取消托管", "离开中"):
                    empty_streak = 0
                else:
                    # HUD 不见了但也没看到结算信号：可能是弹窗/动画遮挡，
                    # 也可能真的离开战斗页。先看结算锚点，再容忍几轮。
                    if self._settle_kind(img) is not None:
                        return (STATE_OK,
                                "战斗已结束（结算页锚点命中），交回主流程")
                    empty_streak += 1
                    if empty_streak >= 6:
                        return (STATE_OK,
                                f"托管等待结束（连续 {empty_streak} 轮无托管 HUD），"
                                "交回主流程识别新状态")
                # 邀请弹窗即时关掉（不打断托管等待）
                invite_btn = invite.find_ignore_button(
                    img, self._invite_templates)
                if invite_btn is not None:
                    self._tap(*invite_btn, wait=2.5)
                    self.log.info("托管等待中忽略游戏邀请弹窗 %s", invite_btn)
                self._poll_heartbeat(poll_i)
                continue
        # 托管两连击 + 验证重试（最多 8 次）。
        # ⚠ 2026-09-25 02:50 事故：战斗开局游戏会**自动连播每个敌方武将的
        # 详情面板**（本局 5 敌将 = 最多连弹 5 次，关 1 个弹 1 个），3 次预算
        # 不够用。8 次 = 5 面板 + 托管验证余量。
        for i in range(8):
            # 金盘 → 托管 两连击。2026-11-12：首轮用短等待 + 局部 OCR 快路径
            # （原 1.8+2.5 秒 + 整屏 OCR ≈ 7.3s/场，实测占战斗回合近 1/4）；
            # 失败后回落到原等待与整屏 OCR 诊断，行为不劣于改前。
            fast = (i == 0)
            self._tap(1843, 130, wait=0.8 if fast else 1.8)
            self._tap(1846, 279, wait=1.2 if fast else 2.5)
            if fast:
                quick = self._ocr(self._shot(fresh=True),
                                  region=TRUSTEE_CHECK_REGION)
                if _has(quick, "取消托管", "离开中"):
                    return STATE_OK, "托管已生效"
            img = self._shot(fresh=True)
            ocr = self._ocr(img)
            if _has(ocr, "取消托管", "离开中"):
                return STATE_OK, "托管已生效"
            # 2026-09-20/21/25 事故链：战斗开局自动弹出敌方武将详情面板
            # （武将技能+武将信息，盖住右上角托管按钮）。
            # 关闭点（2026-09-24/25 两轮 adb 受控实验）：
            #   ✅ (300,100) 左上角空白——两种面板布局下都有效
            #   ❌ (400,300) 落在「蜀汉」横幅/武将卡上，等于保持详情打开
            #   ❌ (1800,250) 落在面板「武将信息」文字区，无效
            if _has(ocr, "武将技能") and _has(ocr, "武将信息"):
                self.log.warning("托管被武将详情面板遮挡，点左上空白关闭")
                self._tap(300, 100, wait=2.0)
                continue
            # 2026-09-21 事故：多局连跑时上局结算过渡帧会被误判 battle，
            # 托管点在动画上；等画面落定后已变成 next_preview 等其他状态。
            # 每轮重分类：不再是 battle 就交还主循环重新路由，不死磕托管。
            now = self.classify(ocr)
            if now != "battle":
                return STATE_OK, f"战斗画面已结束（现为 {now}），交回主流程"
            self.log.warning("托管第 %d 次未生效，重试", i + 1)
        self._save(img, "trustee_fail")
        return STATE_STOP, "连续 8 次托管失败"

    # ---------------------------------------------------- 任务奖励巡检
    #: 任务页右上角军令状数量区域（2026-10-11 用户截图+实机双重标定）
    TASK_TOKEN_REGION = (1620, 100, 1780, 170)

    def _task_tokens_zero(self) -> bool:
        """任务页右上角军令状数量是否为 0。

        读不到数字时按非 0 处理（宁多巡检一次，不因 OCR 抖动漏领奖励）。
        """
        img = self._shot()
        for it in self._ocr(img, region=self.TASK_TOKEN_REGION):
            t = "".join(str(getattr(it, "text", "")).split())
            if t.isdigit():
                return int(t) == 0
        return False

    def _task_reward_flow(self) -> None:
        """任务奖励巡检（用户 2026-09-25 需求，托管等待期每 10 分钟一次）：

        点「任务」图标 → **前置判断：右上角军令状数量为 0 → 直接返回**
        （2026-10-11 用户需求：0 个时刷新必弹「物品数量不足」，不点任何按钮）
        → **单循环：模板匹配「领取奖励」/「刷新」按钮，出现任一就点
        （有几个点几个，点完重扫；没点中自动补点）** → 直到两种按钮
        全部消失（= 新任务无完成状态）→ 点右上角「返回」→ 回托管界面。
        2026-10-07 性能优化：按钮是外观固定的美术横幅，模板匹配 ~40ms
        替代整屏 OCR ~2s。返回后由主循环重新分类，战斗打没打完都能接上。
        本方法不改变状态机，异常一律吞掉（巡检失败不影响主流程）。
        """
        try:
            self.log.info("任务巡检：累计 %d 分钟到点，打开任务页",
                          TASK_CHECK_INTERVAL // 60)
            self._tap(*TASK_ICON_POS, wait=2.5)
            if self._task_tokens_zero():
                self.log.info("任务巡检：军令状数量为 0 → 直接返回")
                self._tap(*TASK_BACK_POS, wait=2.5)
                self._publish("running", "任务巡检跳过（军令状 0）")
                return
            clicked = 0
            for _ in range(16):                  # 上限：6 槽位 + 补点余量
                img = self._shot()
                btns = task_page.find_buttons(
                    img, templates=self._task_templates)
                if not btns:
                    break                        # 按钮全部消失 = 无完成
                btn = btns[0]
                clicked += 1
                self.log.info("任务巡检：点击第 %d 个可点按钮 %s %s (%.2f)",
                              clicked, btn.kind, btn.pos, btn.score)
                self._tap(*btn.pos, wait=2.5)
            # 返回托管界面
            self.log.info("任务巡检：返回托管界面（共点击 %d 次）", clicked)
            self._tap(*TASK_BACK_POS, wait=2.5)
            self._publish("running", f"任务巡检完成（点击 {clicked} 次）")
        except Exception as exc:  # noqa: BLE001
            # 巡检失败不影响主流程；尝试返回托管界面兜底
            self.log.warning("任务巡检异常（忽略）: %r", exc)
            try:
                self._tap(*TASK_BACK_POS, wait=2.5)
            except Exception:  # noqa: BLE001
                pass

    def _claim_task_badges(self, img) -> int:
        """完胜页/任务面板上的「领取」徽章：出现即点（2026-10-23）。

        胜利页右侧常驻任务面板，可领取奖励的徽章外观与任务页按钮不同
        （btn_claim2）。不点的话面板会一直挡着，主循环 unknown 停机
        （实测 3 次 session 停机都停在这）。返回点击数；异常吞掉返回 0。
        """
        try:
            t = self._claim2_tpl
            if t is None:
                return 0
            import cv2
            g = self._gray(img)
            if g.shape[0] <= t.shape[0] or g.shape[1] <= t.shape[1]:
                return 0
            res = cv2.matchTemplate(g, t, cv2.TM_CCOEFF_NORMED)
            ys, xs = np.where(res >= 0.9)
            pts = sorted(zip(xs.tolist(), ys.tolist(), res[ys, xs].tolist()),
                         key=lambda p_: -p_[2])
            clicked = 0
            taken = []
            for x, y, s_ in pts:
                cx, cy = x + t.shape[1] // 2, y + t.shape[0] // 2
                if any(abs(cx - ox) < 80 and abs(cy - oy) < 80
                       for ox, oy in taken):
                    continue                      # NMS 去重
                taken.append((cx, cy))
                self.log.info("任务面板领取徽章 → 点击 (%d,%d) %.2f", cx, cy, s_)
                self._tap(cx, cy, wait=1.5)
                clicked += 1
            return clicked
        except Exception:  # noqa: BLE001 — 领取失败不影响主流程
            return 0

    def _act_gift1(self, items) -> Tuple[str, str]:
        hits = gift.detect_gift_heroes(items)
        if not hits:
            self._save(items and self._shot(), "gift1_no_hero")
            return STATE_STOP, "赠礼一级未识别到武将"
        # 留证 + 全量日志：选人依据可回溯（2026-09-20 龙且漏检事故）
        self._save(self._shot(), "gift1")
        heroes = [h for h, _ in hits]
        cats = [gift.classify_hero(h) for h in heroes]
        self.log.info("赠礼一级候选: %s",
                      "、".join(f"{h}({c or '无类别'})" for h, c in zip(heroes, cats)))
        if len(heroes) == 3 and sum(1 for c in cats if c) <= 1:
            self.log.warning("疑似 OCR 漏检：3 位武将仅 %d 位有类别，"
                             "请核对 runtime/shots/auto_gift1.png",
                             sum(1 for c in cats if c))
        idx, why = gift.pick_gift_hero(heroes)
        if idx is None:
            return STATE_STOP, f"赠礼一级决策失败：{why}"
        name, (x, y) = hits[idx]
        self.last_gift_hero = name
        self.log.info("赠礼一级: %s（%s）", name, why)
        self._tap(x, y, wait=3.0)
        return STATE_OK, f"赠礼选武将 {name}"

    def _act_gift2(self, items) -> Tuple[str, str]:
        hits = gift.detect_gift_options(items)
        if not hits:
            return STATE_STOP, "赠礼二级未识别到选项"
        opts = [o for o, _ in hits]
        idx, why = gift.pick_gift_options(opts, self.last_gift_hero)
        if idx is None:
            return STATE_STOP, f"赠礼二级决策失败：{why}"
        _, (x, y) = hits[idx]
        self.log.info("赠礼二级: %s（%s）", opts[idx], why)
        self._tap(x, y, wait=3.0)
        return STATE_OK, f"赠礼选 {opts[idx]}"

    def _act_rest(self, items) -> Tuple[str, str]:
        opts = rest.detect_rest_options(items)
        if not opts:
            self._save(self._shot(), "rest_no_opts")
            return STATE_STOP, "休息节点未识别到选项"
        idx, why = rest.pick_rest_option([o for o, _ in opts])
        if idx is None:
            return STATE_STOP, f"休息决策失败：{why}"
        name, (x, y) = opts[idx]
        self.log.info("休息: %s（%s）", name, why)
        self._tap(x, y, wait=3.0)
        return STATE_OK, f"休息选择 {name}"

    #: 武将牌专区价格带（局部补扫区域，2026-10-18 姜维 14 事故标定）
    WUPAI_PRICE_BAND = (900, 850, 1920, 970)

    def _shop_price_band_rescan(self, img, items) -> list:
        """全屏没读到武将牌专区商品时，对价格带做局部补扫。

        RapidOCR 全屏偶发漏读小号数字（姜维 14 漏、18/16 不漏，纯随机）。
        局部聚焦通常能读出来；补扫条目坐标平移回全屏坐标系后并入，
        供 parse_shop 重新做「名字在上、价格在下」的列内配对。
        """
        x0, y0, x1, y1 = self.WUPAI_PRICE_BAND
        crop = img[y0:y1, x0:x1]
        extra = []
        for it in self._ocr(crop):
            rx1, ry1, rx2, ry2 = it.rect
            extra.append(_ShiftOCRItem(str(getattr(it, "text", "")),
                                       (rx1 + x0, ry1 + y0,
                                        rx2 + x0, ry2 + y0)))
        return items + extra

    def _act_shop(self, items) -> Tuple[str, str]:
        img = self._shot()
        if items is None:
            # 2026-11-12 商店锚点入表后，主循环锚点命中不再整屏 OCR；
            # 货架解析是购买决策的输入，这里用同一帧补一次（帧缓存复用）
            items = self._ocr(img)
        # 2026-11-12 商店锚点副作用修复：「是否结束购买?」弹窗弹出时左上角
        # 吕不韦标题仍可见 → 锚点把弹窗页误判成 shop → 又点金盘 → 弹窗
        # 开关死循环（用户实测 step5-10 循环 6 次）。决策前先看 items：
        # 弹窗已开就直接点「确定」退出，不再点金盘。
        if _has(items, "是否结束购买"):
            self._tap(823, 690, wait=2.5)
            return STATE_OK, "结束购买确认（弹窗已开，直接确认退出）"
        # 决策留证（2026-11-13，对齐赠礼 auto_gift1 模式）：
        # 解析出的货架 + 当次生效的想要清单 + 截图，"该买没买"一查便知
        parsed = shop.parse_shop(items)
        self._save(img, "auto_shop")
        self.log.info("商店货架解析: %s | 想要清单 %d 项",
                      [(g["name"], g["price"], g["zone"]) for g in parsed]
                      or "空",
                      len(shop.shop_wanted()))
        bal_items = self._ocr(img, region=shop.SHOP_BALANCE_REGION)
        coins = 0
        for it in bal_items:
            t = _norm(it.text)
            m = re.search(r"\d{1,5}", t)
            if m:
                coins = int(m.group())
                break
        goods, why = shop.pick_shop_purchase(items, coins=coins)
        if goods is None:
            # 补扫：全屏没读到武将牌专区商品 → 价格带局部 OCR 再试一次
            if not any(g["zone"] == "wupai" for g in shop.parse_shop(items)):
                items2 = self._shop_price_band_rescan(img, items)
                goods2, why2 = shop.pick_shop_purchase(items2, coins=coins)
                if goods2 is not None:
                    goods, why = goods2, why2 + "（价格带补扫）"
        if goods is None:
            self.log.info("商店: %s", why)
            self._tap(1845, 127, wait=2.0)     # 金盘 → 触发结束购买
            return STATE_OK, "商店不买，退出"
        self.log.info("商店: %s（%s）", goods["name"], why)
        self._tap(*goods["click"], wait=2.5)
        return STATE_OK, f"购买 {goods['name']}（{why}）"

    def _act_hero_event(self, items) -> Tuple[str, str]:
        from src.game import mate_event, moja_event
        # 事件池回退链：武将六蛊惑 → 伙伴朏朏 → 墨家巨子（固定第一个）
        pt, why = hero_event.pick_hero_event(items)
        if pt is None:
            pt, why = mate_event.pick_mate_event(items)
        if pt is None:
            pt, why = moja_event.pick_moja_event(items)
        if pt is None:
            self._save(self._shot(), "hero_event_unknown")
            return STATE_STOP, f"事件决策失败：{why}"
        self.log.info("事件选择: %s", why)
        self._tap(*pt, wait=3.0)
        return STATE_OK, "事件选择完成"


class _ShiftOCRItem:
    """局部 OCR 条目 + 坐标平移回全屏系的轻量包装。"""

    def __init__(self, text: str, rect) -> None:
        self.text = text
        self.rect = rect


def _has_join(items) -> str:
    return "".join(_norm(getattr(it, "text", "")) for it in items)


def _has_round(items) -> bool:
    return re.search(r"第\d+轮", _has_join(items)) is not None


def _wait_device_back(ctx, log, timeout: float = 600.0) -> bool:
    """截图连续失败后等设备恢复（自动重启 adb），最多 timeout 秒。

    2026-11-12 事故：连跑两小时后模拟器/adb 卡死，异常直接打断整批连跑。
    这里把它变成"可等待的暂停"：用户重启模拟器后会自动接上，不用重开脚本。
    """
    end = time.time() + max(1.0, timeout)
    log.warning("设备无响应，进入等待恢复（最多 %.0f 分钟，期间会自动重启 adb）…",
                timeout / 60)
    last_note = 0.0
    while time.time() < end:
        try:
            if hasattr(ctx.device, "recover") and ctx.device.recover(timeout=15.0):
                return True
        except Exception:  # noqa: BLE001 — 自愈失败继续等
            pass
        if time.time() - last_note >= 30:
            last_note = time.time()
            log.warning("仍在等待设备恢复：请检查模拟器是否卡死/已关闭")
        # 睡眠不超过剩余等待时间（短超时场景能立刻结束）
        time.sleep(min(3.0, max(0.2, end - time.time())))
    return False


def run_auto(ctx, log, hero_name: str = "钟离眜",
             max_steps: int = 2000, poll_sleep: float = 0.5,
             tap_scale: float = TAP_WAIT_SCALE,
             node_priority: Optional[Sequence[str]] = None,
             runs: int = 1,
             pause_event=None, stop_event=None,
             status_cb=None) -> int:
    """主入口：跑到本局结束（结算领奖）或停机。返回退出码。

    runs > 1 时连跑多局（每局结束回到入口页自动开下一局）；
    pause_event / stop_event 由 GUI 注入，status_cb 每步推送统计。
    返回码：0=全部完成（单局超步数只跳过该局） 2=未知界面停机 4=用户停止
    """
    runner = AutoRunner(ctx, log, hero_name=hero_name,
                        max_steps=max_steps, poll_sleep=poll_sleep,
                        tap_scale=tap_scale, node_priority=node_priority)
    runner.set_control(pause_event, stop_event, status_cb)
    runner.stats["runs"] = runs
    rc_by_run = []
    t0 = time.time()
    for run_i in range(1, runs + 1):
        runner.stats["run"] = run_i
        runner.layer = 0
        runner.in_run = False
        runner.steps = 0
        runner.last_gift_hero = None
        log.info("===== 第 %d/%d 局开始 =====", run_i, runs)
        while runner.steps < runner.max_steps:
            if not runner._wait_if_paused():
                log.info("=== 用户停止（第 %d 局中途）===", run_i)
                runner._publish("stopped", "用户停止")
                return 4
            t_start = time.time()
            try:
                status, msg = runner.step()
            except DeviceError as exc:
                # 设备/模拟器层面失联：不打断整批连跑，先等它回来
                log.error("设备异常：%s", exc)
                runner._publish("paused", "设备无响应，等待恢复…")
                if _wait_device_back(ctx, log, timeout=600.0):
                    log.info("设备已恢复，继续本局（从当前界面重新识别）")
                    continue
                log.error("=== 设备长时间无响应，停止本批运行 ===")
                runner._publish("stopped", "设备无响应（模拟器可能已卡死）")
                return 2
            runner.stats["msg"] = msg
            step_s = time.time() - t_start
            # 性能指标推给 GUI（2026-11-12）：上步耗时 + 累计步数
            runner.stats["step_s"] = round(step_s, 1)
            runner.stats["steps"] = runner.steps
            # 每步耗时留档（2026-11-12）：定位「慢」到底慢在游戏还是脚本
            log.info("[%d] %s: %s（耗时 %.1fs）", runner.steps, status, msg,
                     step_s)
            if status == STATE_DONE:
                log.info("=== 第 %d 局完成，耗时 %.0f 秒 ===",
                         run_i, time.time() - t0)
                rc_by_run.append(0)
                break
            if status == STATE_STOP:
                log.error("=== 停机：%s（耗时 %.0f 秒）===",
                          msg, time.time() - t0)
                rc_by_run.append(2)
                runner._publish("stopped", msg)
                return 2
            if not runner._wait_if_paused():
                log.info("=== 用户停止（第 %d 局中途）===", run_i)
                runner._publish("stopped", "用户停止")
                return 4
        else:
            # 2026-09-20：无尽深层单局步数很大（33 层实测 >500），
            # 超预算只**跳过本局**继续下一局，不再连坐废掉整个批次。
            # 预算默认已提到 2000；正常一局 ≤1000 步，仍超说明卡死了。
            log.error("=== 第 %d 局超过最大步数 %d，跳过本局继续 ===",
                      run_i, max_steps)
            rc_by_run.append(3)
            continue
    log.info("=== 全部 %d 局完成，总耗时 %.0f 秒 ===",
             runs, time.time() - t0)
    runner._publish("finished", "全部轮次完成")
    return 0
