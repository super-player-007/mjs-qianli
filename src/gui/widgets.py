# -*- coding: utf-8 -*-
"""GUI 通用控件（2026-11-12 重构 + 视觉重做）。

设计原则和一条龙的「界面/逻辑分离」一致：控件只管**渲染**，不碰业务；
所有可测逻辑抽成纯函数（`plan_log_append` / `group_log_levels` /
`format_metrics`），因此能离线单测，不需要显示器。

控件清单
--------
* :class:`HeaderBar` —— 顶部标题条 + 状态胶囊
* :class:`StatusPanel` —— 四个指标卡 + 进度条 + 最近动作
* :class:`LogView` —— 深色日志区，按级别着色、批量写入、环形上限、智能吸底
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Iterable, List, Sequence, Tuple

from src.gui.theme import COLORS, FONTS

STATE_LABELS = {
    "idle": "空闲", "running": "运行中", "paused": "已暂停",
    "stopped": "已停止", "finished": "全部完成",
}
STATE_COLORS = {
    "idle": COLORS["muted"], "running": COLORS["success"],
    "paused": COLORS["warn"], "stopped": COLORS["danger"],
    "finished": COLORS["accent"],
}


# ===================================================================== 纯函数
def plan_log_append(current_lines: int,
                    incoming: Iterable[str],
                    max_lines: int = 2000) -> Tuple[int, str]:
    """计算一次批量追加：需要从头部删掉多少行、要插入什么文本块。

    Returns
    -------
    (delete_lines, block)
    """
    lines = [str(x) for x in incoming if x is not None]
    if not lines:
        return 0, ""
    block = "".join(line if line.endswith("\n") else line + "\n"
                    for line in lines)
    total = current_lines + len(lines)
    overflow = max(0, total - max(0, max_lines))
    return overflow, block


def line_level(line: str) -> str:
    """日志行 → 级别标签名（info / warn / error）。"""
    if "][ERROR]" in line or "[ERROR]" in line:
        return "error"
    if "][WARNING]" in line or "[WARNING]" in line or "警告" in line:
        return "warn"
    return "info"


def group_log_levels(lines: Sequence[str]) -> List[Tuple[str, str]]:
    """把连续的同类日志合成一块：[(level, text_block), ...]。

    这样一次批量最多 2-3 次 insert（带颜色），而不是逐行 insert。
    """
    groups: List[Tuple[str, str]] = []
    for line in lines:
        text = line if str(line).endswith("\n") else str(line) + "\n"
        lvl = line_level(str(line))
        if groups and groups[-1][0] == lvl:
            groups[-1] = (lvl, groups[-1][1] + text)
        else:
            groups.append((lvl, text))
    return groups


def format_metrics(stats: dict) -> List[Tuple[str, str, str]]:
    """统计快照 → 指标卡内容 [(标题, 数值, 颜色键), ...]。"""
    runs = max(1, int(stats.get("runs", 1) or 1))
    run_i = int(stats.get("run", 0) or 0)
    step_s = float(stats.get("step_s") or 0)
    return [
        ("局次", f"{run_i}/{runs}", "text"),
        ("层数", str(int(stats.get("layer", 0) or 0)), "text"),
        ("点击", str(int(stats.get("clicks", 0) or 0)), "text"),
        ("上步耗时", f"{step_s:.1f}s" if stats.get("steps") else "-",
         "accent" if step_s and step_s <= 3 else
         ("warn" if step_s else "muted")),
    ]


#: 日志过滤档位 → 允许通过的最低级别（顺序即严格程度）
LOG_FILTERS: Tuple[Tuple[str, str], ...] = (
    ("全部", "info"),
    ("警告及以上", "warn"),
    ("仅错误", "error"),
)
_LEVEL_RANK = {"info": 0, "warn": 1, "error": 2}


def filter_log_lines(lines: Iterable[str], min_level: str = "info") -> List[str]:
    """按级别过滤日志行（纯函数，UI 与测试共用）。

    ``min_level`` 取 ``info`` / ``warn`` / ``error``；未知值按 info 处理。
    """
    rank = _LEVEL_RANK.get(str(min_level), 0)
    return [str(line) for line in lines
            if _LEVEL_RANK.get(line_level(str(line)), 0) >= rank]


def parse_names(text: str) -> List[str]:
    """逗号分隔名单文本 → 名称列表（中英文逗号/顿号/换行/空白都算分隔）。

    与旧实现行为一致：忽略空项、去首尾空格、保持原顺序、不去重
    （去重由 `src.game.gift` 的裁决规则负责，GUI 不抢它的活）。
    """
    out: List[str] = []
    for chunk in str(text or "").replace("，", ",").replace("、", ",").split(","):
        name = chunk.strip()
        if name:
            out.append(name)
    return out


def join_names(names: Iterable[str]) -> str:
    """名称列表 → 单行文本（GUI 回显用，统一中文逗号）。"""
    return "，".join(str(n).strip() for n in names if str(n).strip())


# ===================================================================== 控件
class HeaderBar(tk.Frame):
    """顶部标题 + 状态胶囊。"""

    def __init__(self, master, title: str, subtitle: str = ""):
        super().__init__(master, bg=COLORS["bg"])
        left = tk.Frame(self, bg=COLORS["bg"])
        left.pack(side="left")
        ttk.Label(left, text=title, style="H1.TLabel").pack(anchor="w")
        if subtitle:
            ttk.Label(left, text=subtitle, style="Muted.TLabel").pack(
                anchor="w", pady=(2, 0))

        self.pill = tk.Frame(self, bg=COLORS["chip"], padx=10, pady=5)
        self.pill.pack(side="right", pady=6)
        self.dot = tk.Canvas(self.pill, width=10, height=10,
                             bg=COLORS["chip"], highlightthickness=0)
        self.dot.pack(side="left", padx=(0, 6))
        self._oval = self.dot.create_oval(1, 1, 9, 9,
                                          fill=COLORS["muted"], outline="")
        self.var_state = tk.StringVar(value="空闲")
        tk.Label(self.pill, textvariable=self.var_state, bg=COLORS["chip"],
                 fg=COLORS["text"], font=FONTS["small"]).pack(side="left")
        self._cached = ""

    def set_state(self, raw: str) -> None:
        label = STATE_LABELS.get(raw, str(raw))
        color = STATE_COLORS.get(raw, COLORS["muted"])
        if self._cached == raw:
            return
        self._cached = raw
        self.var_state.set(label)
        try:
            self.dot.itemconfigure(self._oval, fill=color)
        except tk.TclError:
            pass


class StatusPanel(tk.Frame):
    """状态卡片：四个指标 + 进度条 + 最近动作。"""

    def __init__(self, master):
        super().__init__(master, bg=COLORS["card"])
        # 指标行
        chips = tk.Frame(self, bg=COLORS["card"])
        chips.pack(fill="x")
        self.chip_values: List[tk.StringVar] = []
        self._chip_labels: List[tk.Label] = []
        for i in range(4):
            cell = tk.Frame(chips, bg=COLORS["chip"], padx=12, pady=8)
            cell.grid(row=0, column=i, sticky="nsew",
                      padx=(0 if i == 0 else 8, 0))
            chips.columnconfigure(i, weight=1)
            title = tk.Label(cell, text="-", bg=COLORS["chip"],
                             fg=COLORS["muted"], font=FONTS["small"])
            title.pack(anchor="w")
            var = tk.StringVar(value="-")
            val = tk.Label(cell, textvariable=var, bg=COLORS["chip"],
                           fg=COLORS["text"], font=FONTS["metric"])
            val.pack(anchor="w")
            self.chip_values.append(var)
            self._chip_labels.append(val)

        # 进度条
        bar = tk.Frame(self, bg=COLORS["card"])
        bar.pack(fill="x", pady=(12, 0))
        self.pb = ttk.Progressbar(bar, style="Modern.Horizontal.TProgressbar",
                                  maximum=100)
        self.pb.pack(fill="x")

        # 最近动作
        self.var_msg = tk.StringVar(value="最近动作：-")
        tk.Label(self, textvariable=self.var_msg, bg=COLORS["card"],
                 fg=COLORS["muted"], font=FONTS["small"],
                 anchor="w", justify="left", wraplength=520).pack(
                     fill="x", pady=(8, 0))

        self._cache: dict = {}

    def update_stats(self, s: dict) -> None:
        for (title, value, color_key), var, lab in zip(
                format_metrics(s), self.chip_values, self._chip_labels):
            if self._cache.get(("t", title)) != title:
                self._cache[("t", title)] = title
                lab.master.winfo_children()[0].configure(text=title)
            if self._cache.get(("v", title)) != value:
                self._cache[("v", title)] = value
                var.set(value)
                lab.configure(fg=COLORS.get(color_key, COLORS["text"]))

        msg = f"最近动作：{s.get('msg') or '-'}"
        if self._cache.get("msg") != msg:
            self._cache["msg"] = msg
            self.var_msg.set(msg)

        runs = max(1, int(s.get("runs", 1) or 1))
        pct = 100.0 * min(1.0, int(s.get("run", 0) or 0) / runs)
        if abs(float(self.pb["value"]) - pct) >= 1.0:
            self.pb.config(value=pct)


class ScrollableColumn(tk.Frame):
    """可滚动的内容列（左侧配置区用）。

    卡片堆叠高度超过窗口时，鼠标在列内滚轮即可滚动；宽度随容器自适应。
    """

    def __init__(self, master):
        super().__init__(master, bg=COLORS["bg"])
        self.canvas = tk.Canvas(self, bg=COLORS["bg"], highlightthickness=0,
                                bd=0)
        self.scroll = ttk.Scrollbar(self, orient="vertical",
                                    command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.scroll.set)
        self.scroll.pack(side="right", fill="y")     # 先占位，避免被 canvas 挤掉
        self.canvas.pack(side="left", fill="both", expand=True)

        self.body = tk.Frame(self.canvas, bg=COLORS["bg"])
        self._win = self.canvas.create_window((0, 0), window=self.body,
                                              anchor="nw")
        self.body.bind("<Configure>", self._sync_scrollregion)
        self.canvas.bind("<Configure>", self._sync_width)
        self.canvas.bind("<Enter>", lambda e: self._wheel(True))
        self.canvas.bind("<Leave>", lambda e: self._wheel(False))

    def _sync_scrollregion(self, _event=None):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _sync_width(self, event):
        self.canvas.itemconfigure(self._win, width=event.width)

    def _wheel(self, enable: bool):
        if enable:
            self.canvas.bind_all("<MouseWheel>", self._on_wheel)
        else:
            self.canvas.unbind_all("<MouseWheel>")

    def _on_wheel(self, event):
        try:
            self.canvas.yview_scroll(int(-event.delta / 120), "units")
        except tk.TclError:
            pass


class LogView(tk.Frame):
    """深色日志区：按级别着色 + 批量写入 + 环形上限 + 智能吸底。"""

    def __init__(self, master, max_lines: int = 2000, height: int = 18):
        super().__init__(master, bg=COLORS["log_bg"])
        self.max_lines = max(100, int(max_lines))
        self.text = tk.Text(self, height=height, state="disabled",
                            font=FONTS["mono"], wrap="char",
                            bg=COLORS["log_bg"], fg=COLORS["log_text"],
                            insertbackground=COLORS["log_text"],
                            relief="flat", borderwidth=0, padx=10, pady=8)
        self.scroll = ttk.Scrollbar(self, orient="vertical",
                                    command=self.text.yview)
        self.text.configure(yscrollcommand=self.scroll.set)
        self.scroll.pack(side="right", fill="y")
        self.text.pack(side="left", fill="both", expand=True)
        self.text.tag_configure("info", foreground=COLORS["log_info"])
        self.text.tag_configure("warn", foreground=COLORS["log_warn"])
        self.text.tag_configure("error", foreground=COLORS["log_error"])
        self.text.tag_configure("hint", foreground="#5B6B85")
        self.autoscroll: bool = True     # 自动滚动（可关，翻看历史时不被打断）
        self._placeholder = True
        self.text.configure(state="normal")
        self.text.insert("end",
                         "等待启动…（点击左下角「启动」后，这里实时显示运行日志）\n",
                         "hint")
        self.text.configure(state="disabled")

    # ------------------------------------------------------------------ 内部
    def _at_bottom(self) -> bool:
        try:
            return self.text.yview()[1] >= 0.999
        except tk.TclError:
            return True

    def _line_count(self) -> int:
        try:
            return int(self.text.index("end-1c").split(".")[0])
        except (tk.TclError, ValueError):
            return 0

    # ------------------------------------------------------------------ 接口
    def append_lines(self, lines: Iterable[str]) -> None:
        lines = [str(x) for x in lines]
        if not lines:
            return
        stick = self._at_bottom()
        if self._placeholder:          # 首条真实日志到来时清掉占位提示
            self._placeholder = False
            self.text.configure(state="normal")
            self.text.delete("1.0", "end")
            self.text.configure(state="disabled")
        overflow, _ = plan_log_append(self._line_count(), lines,
                                      self.max_lines)
        self.text.configure(state="normal")
        if overflow:
            self.text.delete("1.0", f"{overflow + 1}.0")
        for level, block in group_log_levels(lines):
            self.text.insert("end", block, level)
        self.text.configure(state="disabled")
        if stick and self.autoscroll:
            self.text.see("end")

    def append_line(self, line: str) -> None:
        self.append_lines([line])

    def set_autoscroll(self, on: bool) -> None:
        """关闭自动滚动后可安静翻看历史；重新打开时立即吸到底部。"""
        self.autoscroll = bool(on)
        if self.autoscroll:
            self.text.see("end")

    def export_text(self) -> str:
        """导出当前日志内容（纯文本，供"导出"按钮写文件）。"""
        try:
            return self.text.get("1.0", "end-1c")
        except tk.TclError:
            return ""

    def clear(self) -> None:
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        self.text.configure(state="disabled")
