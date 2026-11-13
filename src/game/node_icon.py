"""地图节点识别：定位节点圆 + 双窗口判定节点类型。

原理（实测结论）
----------------
1. **节点位置用霍夫圆**。节点是纵向单列的圆（圆形武将头像或图案），间距约 170 px。
   圆检测与「类型」无关，层数/数量变化时天然适用（找到几个就是几个）。
   实测参数：``dp=1.2, minDist=120, param1=120, param2=34, r∈[36,62]``。
   ⚠ param2=40 会**漏掉篝火（休息）节点**——它的圆边缘对比度比头像弱，
   2026-09-17 第 3 层实测必须降到 34；多出来的假圆由第 4/5 步两道闸兜住。
2. **模板直接裁真实节点**，不用图例栏的图标。
   ⚠ 走过的弯路：图例栏（顶部「战斗·商店·…」）的图标与节点图标**同形但不同底**
   （图例是深蓝灰木牌底，节点是米色卡底），拿图例图标去匹配节点，最高只有 0.358，
   完全不可用。正确做法是**从游戏截图的真实节点上直接裁**这块图当模板。
3. **双窗口分类**（2026-09-17 第 3 层确立）：节点有两种画法——
   - **头像节点**（战斗/商店/事件/武将/伙伴）：圆里是武将头像，
     类型图标在圆下方，中心 ≈ 圆心 + ``(5, +48)``，模板 35x30、窗口留 14 px 边距；
   - **本体节点**（休息=篝火）：圆里**就是**图案本身，圆下方没有图标，
     此时改比对**圆内窗口**（88x88，模板 64x64）。
   实测（第 3 层 商店/休息/商店）：图标窗 1.000/0.895，圆内窗 1.000，交叉干扰 ≤0.54。
4. **假圆过滤**：放宽搜索区后会命中云雾/建筑/飘浮物（如「云中君」精灵）等假圆。
   **头像节点**圆下方必有一块深色图标字形（灰度<70 占比 0.285~0.420），
   假圆多为 0.000；本体节点不走这条判据（圆下没有图标），靠第 3 步圆内匹配定型。
5. **只保留「当前层」那一列节点**（`:func:`keep_current_layer``）。
   地图是**向右延伸的路径图**：层数递增 → 当前层节点列整体右移
   （实测第 1 层 x≈667、第 2 层 x≈1082、第 3 层 x≈1100，而 y 基本恒为 ~397/567/736）。
   走过的节点不会被清掉，仍留在左侧原位（带红色「已通关」印章），
   **用户明确要求：已通关节点一律不认，只认当前层**。
   实测该列聚类规则同时干掉了这些干扰源：
   已通关节点（印章 OCR 读成「巨通关」、红色色彩特征也分不开）、
   飘浮精灵（深色头发能过假圆过滤）、云雾假圆。

新增类型的做法
--------------
- 头像节点（如事件/武将/伙伴）：从真实节点裁**圆下方图标** 35x30，
  存成 ``assets/templates/run_map/node_<key>.png``。
- 本体节点（如休息）：裁**圆内本体** 64x64，同样命名。
- **同类型多个事件**（2026-09-17 第 4 层确立）：武将节点的不同事件画面完全不同
  （十二阉人 vs 墨家巨子，互配仅 0.35），单一模板打不通 → 存成
  ``node_<类型>_<事件>.png``（如 ``node_hero_shier.png``），加载时按
  **第一个下划线前的前缀**归类到类型。
本模块自动加载，无需改代码。中文名在 ``NODE_LABELS`` 里补一行。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import cv2
import numpy as np

# ------------------------------------------------------------------ 常量
#: 节点圆心的搜索区域 (x1, y1, x2, y2) —— 整块地图区（不含左侧武将面板）。
#: ⚠ 不能用窄区域：**节点的 y 固定、x 随地图滚动变化**。
#: 实测第 1 层在 x=667，第 2 层在 x=1080，y 都是 397/567/736。
NODE_REGION: Tuple[int, int, int, int] = (330, 180, 1700, 1020)

#: 图标中心相对节点圆心的偏移（2026-09-16 实测三节点 (5,48)/(3,49)/(7,49)，取 (5,48)）
ICON_DX, ICON_DY = 5, 48

#: 图标模板的基准尺寸（宽, 高）
ICON_W, ICON_H = 35, 30

#: 比对窗口相对模板放宽的边距（容忍圆心定位误差）。
#: ⚠ 不能太小：边距不足会把模板在滑动窗口里裁掉一行，分数虚低
#: （实测 node3 由 0.857 掉到 0.659，导致贴着阈值误判）。
ICON_MARGIN = 14

#: 分类阈值（实测正确类型 0.86~1.00，非节点区域最高仅 0.48）
DEFAULT_THRESHOLD = 0.70

#: 霍夫圆参数。⚠ param2=40 会漏掉篝火（休息）节点（圆边缘对比度弱），
#: 实测必须 34（2026-09-17 第 3 层）；多出的假圆由深色图标判据 + 列聚类兜住。
HOUGH = dict(dp=1.2, minDist=120, param1=120, param2=34,
             minRadius=36, maxRadius=62)

#: 真假圆的判别阈值：**头像节点**圆下方必有一块深色类型图标。
#: 实测头像节点该区域（<70 灰度）占比 0.285~0.420，云雾/建筑假圆恒为 0.000。
#: ⚠ 只对头像节点有效——篝火（休息）这类「本体节点」圆下没有图标（占比≈0），
#: 不能用它一票否决，须先走圆内本体分类（见 :func:`analyze_nodes`）。
ICON_DARK_LEVEL = 70
ICON_DARK_RATIO = 0.10

#: 「本体节点」（休息=篝火等）的圆内比对窗口半边长。
#: 模板 ``node_rest.png`` 为圆内中央 64x64；窗口取 88x88 留滑动余量。
BODY_WIN_HALF = 44
#: 本体模板的裁剪尺寸（正方形边长）
BODY_TPL_SIZE = 64

#: 同一列节点的 x 容差。实测同列三个节点 x 差 ≤3 px，跨列差 ≥270 px，
#: 取 60 px 既能容忍圆心抖动，又不会把相邻两列并成一列。
COLUMN_X_TOLERANCE = 60

#: 类型 key → 中文标签
NODE_LABELS: Dict[str, str] = {
    "battle": "战斗",
    "shop": "商店",
    "event": "事件",
    "rest": "休息",
    "hero": "武将",
    "mate": "伙伴",
}

#: 节点选择优先级（用户口述 2026-09-17 两轮补全）：
#: 卧龙出山 > 偶遇朏朏 > 十二阉人事件 > 休息 > 商店 > 墨家巨子事件 >
#: 疯疯老道事件 > 小狗当道事件 > 事件节点。
#: 条目可以是**事件 key**（如 ``hero_shier``）或**类型 key**（如 ``rest``）：
#: 同类型不同事件收益不同（同为武将，卧龙 >> 疯疯老道），所以武将/伙伴必须按事件排。
#: 注意节点类型/事件**每层都会变**，"第 N 个是什么"不固定，只能按优先级选。
NODE_SELECTION_PRIORITY: Tuple[str, ...] = (
    "hero_wolong",   # 武将·卧龙出山
    "mate_feifei",   # 伙伴·偶遇朏朏
    "hero_shier",    # 武将·十二阉人事件
    "rest",          # 休息（篝火）
    "shop",          # 商店
    "hero_moja",     # 武将·墨家巨子事件
    "hero_fengfeng", # 武将·疯疯老道事件
    "mate_dog",      # 伙伴·小狗当道事件
    "event",         # 事件（钱袋）
)


def select_node(nodes: Sequence["NodeInfo"],
                priority: Sequence[str] = NODE_SELECTION_PRIORITY,
                ) -> Tuple[Optional["NodeInfo"], str]:
    """按用户优先级从当前层节点里选一个，返回 ``(节点, 理由)``。

    规则（用户 2026-09-16/17 口述）：
    1. 按 ``priority`` 从高到低找第一个命中者；条目先按**事件 key**（``node.event``）
       精确匹配，再按**类型 key**（``node.kind``）匹配；
    2. 都不在优先级里 → **选最后一个**（即"3 节点全战斗固定选第三个"的推广）。
    """
    if not nodes:
        return None, "没有候选节点"
    for want in priority:
        for n in nodes:
            if n.event == want:
                return n, f"优先级命中事件「{want}」"
        for n in nodes:
            if n.kind == want:
                return n, f"优先级命中类型「{n.label}」"
    last = nodes[-1]
    return last, f"优先级 {list(priority)} 未覆盖任何节点 → 沿用『全战斗选最后一个』→ #{last.index}"


# ------------------------------------------------------------------ 数据结构
@dataclass
class NodeInfo:
    """一个地图节点。"""

    cx: int
    cy: int
    r: int
    index: int = 0
    kind: str = "unknown"
    label: str = "未知"
    score: float = 0.0
    #: 命中的模板 key（事件级，如 ``hero_shier``；未命中为空串）
    event: str = ""
    scores: List[Tuple[str, float]] = field(default_factory=list)

    @property
    def tap(self) -> Tuple[int, int]:
        """点击点 —— 取圆心（点图标容易只点到图标本身）。"""
        return self.cx, self.cy

    def __str__(self) -> str:
        return (f"#{self.index} ({self.cx},{self.cy}) r={self.r} "
                f"{self.label}({self.kind}) {self.score:.3f}")


# ------------------------------------------------------------------ 检测
def icon_dark_ratio(img: np.ndarray, cx: int, cy: int) -> float:
    """节点圆下方图标区里「深色像素」的占比 —— 用来剔除假圆。"""
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    px, py = cx + ICON_DX, cy + ICON_DY
    x1, y1 = px - ICON_W // 2, py - ICON_H // 2
    x2, y2 = x1 + ICON_W, y1 + ICON_H
    if x1 < 0 or y1 < 0 or x2 > g.shape[1] or y2 > g.shape[0]:
        return 0.0
    return float((g[y1:y2, x1:x2] < ICON_DARK_LEVEL).mean())


def detect_node_centers(img: np.ndarray,
                        region: Sequence[int] = NODE_REGION,
                        verify: bool = False,
                        ) -> List[Tuple[int, int, int]]:
    """霍夫圆检测节点，返回按 y 升序的 ``[(cx, cy, r)]``。

    ``verify=True`` 时用 :func:`icon_dark_ratio` 预过滤**头像类**假圆；
    默认关闭——篝火（休息）这类本体节点圆下没有图标，会被误杀，
    假圆交由 :func:`analyze_nodes` 的分类闸与 :func:`keep_current_layer` 的列聚类兜底。
    """
    x1, y1, x2, y2 = region
    x1, y1 = max(0, x1), max(0, y1)
    x2, y2 = min(img.shape[1], x2), min(img.shape[0], y2)
    sub = img[y1:y2, x1:x2]
    if sub.size == 0:
        return []
    gray = cv2.medianBlur(cv2.cvtColor(sub, cv2.COLOR_BGR2GRAY), 5)
    circles = cv2.HoughCircles(gray, cv2.HOUGH_GRADIENT, **HOUGH)
    if circles is None:
        return []
    out = [(int(round(x)) + x1, int(round(y)) + y1, int(round(r)))
           for x, y, r in circles[0]]
    if verify:
        out = [c for c in out
               if icon_dark_ratio(img, c[0], c[1]) >= ICON_DARK_RATIO]
    return sorted(out, key=lambda t: t[1])


def column_clusters(centers: Sequence[Tuple[int, int, int]],
                    tol: int = COLUMN_X_TOLERANCE,
                    ) -> List[List[Tuple[int, int, int]]]:
    """把圆心按 x 聚成若干「列」。返回 ``[[(cx,cy,r), ...], ...]``，各列按 x 升序。"""
    cols: List[List[Tuple[int, int, int]]] = []
    for c in sorted(centers, key=lambda t: t[0]):
        for col in cols:
            if abs(c[0] - col[-1][0]) <= tol:
                col.append(c)
                break
        else:
            cols.append([c])
    return cols


def keep_current_layer(centers: Sequence[Tuple[int, int, int]],
                       tol: int = COLUMN_X_TOLERANCE,
                       ) -> Tuple[List[Tuple[int, int, int]], List[Tuple[int, int, int]]]:
    """只保留**当前层**那一列节点，返回 ``(保留, 剔除)``（均按 y 升序）。

    地图是向右延伸的路径图：层数越大，当前层节点列越靠右；
    已通关节点留在左侧原位不消失。故先按 x 聚列，再按下列优先级选列：

    1. **列内节点数最多** —— 当前层是玩家可选的若干节点，通常 ≥2；
       而已通关那条路上每列只剩 1 个（走过的那个），右侧偶尔出现的云雾/精灵
       也只是孤立 1 个。用「个数」优先可避免被右侧孤立假圆带偏。
    2. 个数相同时取 **x 更大（更靠右）** 的列 —— 层数递增方向。

    实测（2026-09-16 第 2 层）：三列 ``x≈398(1 个,精灵) / 668(1 个,已通关) / 1082(3 个,当前层)``
    → 正确保留 x≈1082 那一列。
    """
    cols = column_clusters(centers, tol)
    if not cols:
        return [], []
    best = max(cols, key=lambda col: (len(col), col[-1][0]))
    keep = sorted(best, key=lambda t: t[1])
    drop = sorted([c for col in cols if col is not best for c in col],
                  key=lambda t: t[1])
    return keep, drop


# ------------------------------------------------------------------ 模板
def icon_patch(img: np.ndarray, cx: int, cy: int,
               w: int = ICON_W, h: int = ICON_H,
               margin: int = ICON_MARGIN) -> Optional[np.ndarray]:
    """取节点下方图标的比对窗口（比模板略大，留出位移余量）。"""
    px, py = cx + ICON_DX, cy + ICON_DY
    x1, y1 = px - w // 2 - margin, py - h // 2 - margin
    x2, y2 = x1 + w + margin * 2, y1 + h + margin * 2
    if x1 < 0 or y1 < 0 or x2 > img.shape[1] or y2 > img.shape[0]:
        return None
    return img[y1:y2, x1:x2].copy()


def body_patch(img: np.ndarray, cx: int, cy: int,
               half: int = BODY_WIN_HALF) -> Optional[np.ndarray]:
    """取「本体节点」（篝火等）的圆内比对窗口（模板 64x64，窗口 88x88）。"""
    x1, y1 = cx - half, cy - half
    x2, y2 = cx + half, cy + half
    if x1 < 0 or y1 < 0 or x2 > img.shape[1] or y2 > img.shape[0]:
        return None
    return img[y1:y2, x1:x2].copy()


def load_node_templates(tpl_dir: Path,
                        ) -> Dict[str, np.ndarray]:
    """加载 ``node_*.png``（排除 ``*_clip.png`` 这类非真实节点素材）。

    命名两式：
    - ``node_<类型>.png``（如 ``node_battle.png``）
    - ``node_<类型>_<事件>.png``（如 ``node_hero_shier.png``）——
      同类型不同事件画面不同时用，:func:`template_kind` 按前缀归类。
    """
    out: Dict[str, np.ndarray] = {}
    for p in sorted(Path(tpl_dir).glob("node_*.png")):
        key = p.stem[len("node_"):]
        if key.endswith("_clip"):
            continue
        img = None
        try:  # 中文路径安全读取
            img = cv2.imdecode(np.fromfile(str(p), dtype=np.uint8),
                               cv2.IMREAD_COLOR)
        except Exception:  # noqa: BLE001
            img = None
        if img is None:
            continue
        out[key] = img
    return out


def template_kind(key: str) -> str:
    """模板 key → 节点类型：取第一个下划线前的前缀（``hero_shier`` → ``hero``）。"""
    return key.split("_", 1)[0]


def classify_patch(patch: np.ndarray,
                   templates: Dict[str, np.ndarray],
                   scales: Sequence[float] = (1.0, 0.9, 1.1),
                   ) -> List[Tuple[str, float]]:
    """返回按分数降序的 ``[(key, score)]``。

    ``TM_CCOEFF_NORMED`` 对线性亮度变化免疫，但**对尺度敏感**，
    故附一小圈尺度搜索（±10%）兜底非 1080p 分辨率。
    """
    if patch is None or not templates:
        return []
    pg = cv2.cvtColor(patch, cv2.COLOR_BGR2GRAY)
    res: List[Tuple[str, float]] = []
    for key, tpl in templates.items():
        best = -1.0
        for sc in scales:
            w = max(8, int(round(tpl.shape[1] * sc)))
            h = max(8, int(round(tpl.shape[0] * sc)))
            if w >= pg.shape[1] or h >= pg.shape[0]:
                continue
            t = cv2.resize(cv2.cvtColor(tpl, cv2.COLOR_BGR2GRAY), (w, h),
                           interpolation=cv2.INTER_AREA if sc < 1.0 else cv2.INTER_CUBIC)
            s = float(cv2.matchTemplate(pg, t, cv2.TM_CCOEFF_NORMED).max())
            if s > best:
                best = s
        res.append((key, best))
    return sorted(res, key=lambda p: -p[1])


def _to_kind_scores(scored: Sequence[Tuple[str, float]],
                    ) -> List[Tuple[str, float]]:
    """把 ``[(模板key, 分)]`` 按**类型前缀**聚合取最大，返回 ``[(类型, 分)]`` 降序。

    同类型多个事件模板（如 ``hero_shier`` / ``hero_moja``）只留该类型的最高分——
    节点判型只关心"是不是武将"，不关心是哪个事件。
    """
    agg: Dict[str, float] = {}
    for key, s in scored:
        k = template_kind(key)
        if s > agg.get(k, -1.0):
            agg[k] = s
    return sorted(agg.items(), key=lambda p: -p[1])


# ------------------------------------------------------------------ 总入口
def _classify_center(img: np.ndarray, cx: int, cy: int, r: int, index: int,
                     templates: Dict[str, np.ndarray],
                     threshold: float = DEFAULT_THRESHOLD,
                     ) -> NodeInfo:
    """对单个圆心做双窗口分类（analyze_nodes 与兜底找回共用的核心）。"""
    info = NodeInfo(cx=cx, cy=cy, r=r, index=index)

    # 双窗口分类：
    # ① 本体节点（篝火/事件事件等）——圆内即图案，圆下没有图标；
    # ② 头像节点——类型图标在圆下方，且该处必有深色字形（否则视为假圆证据）。
    inner_raw = classify_patch(body_patch(img, cx, cy), templates)
    icon_raw = classify_patch(icon_patch(img, cx, cy), templates)
    dark_ok = icon_dark_ratio(img, cx, cy) >= ICON_DARK_RATIO

    cand: List[Tuple[str, float]] = []
    if inner_raw:
        cand.append(inner_raw[0])
    if icon_raw and dark_ok:
        cand.append(icon_raw[0])
    best = max(cand, key=lambda t: t[1]) if cand else None
    # 展示用：按类型聚合（同类型多事件模板取最高分）
    scores = _to_kind_scores(cand)

    info.scores = scores
    if best and best[1] >= threshold:
        info.event = best[0]
        info.kind = template_kind(best[0])
        info.score = best[1]
        info.label = NODE_LABELS.get(info.kind, info.kind)
    else:
        info.event = ""
        info.kind = "unknown"
        info.score = best[1] if best else -1.0
        info.label = "未知"
    return info


def analyze_nodes(img: np.ndarray,
                  templates: Optional[Dict[str, np.ndarray]] = None,
                  tpl_dir: Optional[Path] = None,
                  threshold: float = DEFAULT_THRESHOLD,
                  region: Sequence[int] = NODE_REGION,
                  only_current_layer: bool = True,
                  dropped_out: Optional[List[Tuple[int, int, int]]] = None,
                  ) -> List[NodeInfo]:
    """定位节点并判定类型。

    ``only_current_layer=True``（默认）时只返回**当前层**那一列节点，
    已通关节点与飘浮精灵等干扰圆会被剔除（见 :func:`keep_current_layer`）；
    传入 ``dropped_out`` 可拿到被剔除的圆心列表（排错用）。
    """
    if templates is None:
        templates = load_node_templates(tpl_dir or Path("assets/templates/run_map"))
    centers = detect_node_centers(img, region)
    if only_current_layer:
        centers, dropped = keep_current_layer(centers)
        if dropped_out is not None:
            dropped_out.extend(dropped)
    return [_classify_center(img, cx, cy, r, i, templates, threshold)
            for i, (cx, cy, r) in enumerate(centers, 1)]


def recover_classified_node(img: np.ndarray,
                            templates: Dict[str, np.ndarray],
                            threshold: float = DEFAULT_THRESHOLD,
                            region: Sequence[int] = NODE_REGION,
                            ) -> Optional[NodeInfo]:
    """最后一层兜底（2026-09-20 无尽 35 层实测）。

    场景：当前层只剩 **1 个节点**时，列聚类"按个数优先"会被右侧
    两两成堆的装饰假圆（云纹 r≈50，相距 ≤60px 聚成一列 2 个）反超，
    导致真节点被剔、只剩装饰列全 unknown。

    做法：跳过列聚类，对**全部**霍夫圆做双窗口分类，保留有类型
    （≥threshold）者，取 **x 最靠右**的一个——地图向右延伸，当前层
    一定在已通关节点的右侧。全部无类型时返回 ``None``（维持原行为）。
    """
    found: List[NodeInfo] = []
    for cx, cy, r in detect_node_centers(img, region):
        info = _classify_center(img, cx, cy, r, 1, templates, threshold)
        if info.kind != "unknown":
            found.append(info)
    if not found:
        return None
    found.sort(key=lambda n: n.cx)
    return found[-1]


def draw_nodes(img: np.ndarray, nodes: List[NodeInfo]) -> np.ndarray:
    """把节点圆心、类型标签画到图上（标定与排错用）。

    文字用 ASCII 的 ``kind``：``cv2.putText`` 不支持中文，写中文会变问号。
    """
    vis = img.copy()
    for n in nodes:
        color = (0, 0, 255) if n.kind == "unknown" else (0, 200, 0)
        cv2.circle(vis, (n.cx, n.cy), n.r, color, 3)
        cv2.circle(vis, (n.cx, n.cy), 3, color, -1)
        text = f"#{n.index} {n.kind} {n.score:.2f}"
        cv2.putText(vis, text, (n.cx - n.r, n.cy - n.r - 8),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2, cv2.LINE_AA)
        px, py = n.cx + ICON_DX, n.cy + ICON_DY
        cv2.rectangle(vis, (px - ICON_W // 2, py - ICON_H // 2),
                      (px + ICON_W // 2, py + ICON_H // 2), (255, 0, 0), 2)
    return vis
