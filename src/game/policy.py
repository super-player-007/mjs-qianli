"""决策策略：给每个可选项打「推荐分」，供人工参考或自动模式兜底。

重要说明
--------
用户要求「无法明确判断时必须询问，不得臆断」。因此本模块的打分**不直接
决定最终选择**，而是：
  * 在提问时把得分最高项标为「★推荐」，辅助你快速决策；
  * 仅当显式配置 ``decision.mode = auto`` 时才真正自动执行。

即：策略是"建议"，人是"决策者"。这样既避免臆断，又能在你忙时一键采纳。

打分来源
--------
1) ``config/coords.yaml`` 中每个选项可写的 ``weight``/``priority`` 字段
2) 关键词加权表（下方 DEFAULT_KEYWORD_WEIGHTS），命中词根累加权重
3) 负面词（减益）扣分
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

# ---------------------------------------------------------------------------
# 关键词权重表（公开攻略共识：优先叠「杀的伤害」，其次「摸牌数/手牌上限」，
# 血量吃紧时「回复体力」，「速度」在后期影响先手，减益项尽量规避）
# 关键词命中即累加；可被 config 覆盖。
# ---------------------------------------------------------------------------
DEFAULT_KEYWORD_WEIGHTS: Dict[str, float] = {
    # 输出核心
    "杀伤": 3.0, "伤害": 3.0, "杀": 1.0,
    # 资源/续航
    "摸牌": 2.2, "手牌上限": 1.8, "过牌": 1.8,
    "回复": 2.5, "体力": 1.2, "血量": 1.0, "治疗": 2.0,
    # 先手
    "速度": 1.5,
    # 通用正向
    "全属性": 2.0, "提升": 1.0, "增加": 0.8, "获得": 0.6,
}

# 减益/负面关键词（命中即扣分）
DEFAULT_NEGATIVE_WEIGHTS: Dict[str, float] = {
    "减少": -2.0, "降低": -2.0, "失去": -2.5, "弃牌": -1.5,
    "受到": -1.5, "扣": -1.5, "无法": -1.0, "减益": -3.0,
}


class DecisionPolicy:
    """基于关键词的选项打分器。"""

    def __init__(self,
                 keyword_weights: Optional[Dict[str, float]] = None,
                 negative_weights: Optional[Dict[str, float]] = None,
                 config: Optional[Dict[str, Any]] = None) -> None:
        self.positive = dict(DEFAULT_KEYWORD_WEIGHTS)
        self.negative = dict(DEFAULT_NEGATIVE_WEIGHTS)

        # 允许从 settings 覆盖
        if config:
            self.positive.update(config.get("keyword_weights") or {})
            self.negative.update(config.get("negative_weights") or {})

    # ------------------------------------------------------------------ 打分
    def score_text(self, text: str) -> float:
        """按关键词表给一段文字打分。"""
        if not text:
            return 0.0
        score = 0.0
        for kw, w in self.positive.items():
            if kw in text:
                score += w
        for kw, w in self.negative.items():
            if kw in text:
                score += w
        return score

    def score_option(self, label: str, desc: str = "",
                     explicit_weight: Optional[float] = None) -> float:
        """给单个选项打分：显式权重优先，其次关键词。"""
        if explicit_weight is not None:
            return float(explicit_weight)
        return self.score_text(f"{label}{desc}")

    def rank(self, options: Sequence[Dict[str, Any]],
             text_key: str = "desc") -> List[Dict[str, Any]]:
        """给一组字典选项附加 score 字段并返回（不改动原对象顺序）。"""
        out = []
        for opt in options:
            label = str(opt.get("label", ""))
            desc = str(opt.get(text_key, "") or "")
            out.append({
                "label": label,
                "desc": desc,
                "score": self.score_option(label, desc, opt.get("weight")),
            })
        return out

    # ------------------------------------------------------- 撤退/继续 判断
    def should_retreat(self, mileage: int, target_mileage: int,
                       hp_ratio: float, lost_hp_critical: bool = False) -> bool:
        """是否主动撤退（仅在用户配置了目标层数时给出建议）。

        说明：撤退属于高风险决策（hybrid 模式下会强制提问），此处仅提供
        **建议**，最终仍由用户确认。
        """
        if target_mileage and mileage >= target_mileage:
            return True
        if lost_hp_critical and hp_ratio < 0.25:
            return True
        return False
