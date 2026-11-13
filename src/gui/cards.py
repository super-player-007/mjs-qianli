# -*- coding: utf-8 -*-
"""卡片式控件（2026-11-13 页面设计改造）。

学习 OneDragon 的页面设计语言，**只在前端层实现，不动后端配置结构**：

* :class:`SettingRow` —— 一行一个配置，行高固定 50px（标题 + 灰说明 + 右侧控件）；
* :class:`NamesBlock` —— 逗号分隔名单编辑块（武将名单 / 商店名单）；
* :class:`PriorityBlock` —— 节点优先级列表（上移/下移）；
* :func:`section` —— 卡片分组（复用 theme.card）。

为什么"表驱动"：后端 `settings.yaml` 只是 34 个扁平键，没有类型元数据。
所以映射表放在 GUI 层（键 → 标题 → 控件类型），**不给后端造 adapter 框架**。

设计原则（与 docs/09 一致）：
1. 页面只描述内容，不描述坐标（行内自动布局）；
2. 一行一个配置、行高固定，加配置项不破坏布局；
3. 控件只负责取值/赋值，读写配置由 app.py 统一做。
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import List, Optional, Sequence, Tuple

from src.gui.theme import COLORS, FONTS, card


class SettingRow(tk.Frame):
    """一行一个配置：左标题+说明，右控件，固定 50px 高。"""

    HEIGHT = 52

    def __init__(self, master, key: str, title: str, hint: str = "",
                 kind: str = "text", values: Optional[Sequence[str]] = None,
                 labels: Optional[Sequence[str]] = None,
                 from_: Optional[float] = None, to: Optional[float] = None,
                 increment: Optional[float] = None, width: int = 16):
        super().__init__(master, bg=COLORS["card"])
        self.key = key
        self.kind = kind
        self._labels = list(labels) if labels is not None else None
        self._values = list(values) if values is not None else None

        left = tk.Frame(self, bg=COLORS["card"])
        left.pack(side="left", fill="x", expand=True)
        tk.Label(left, text=title, bg=COLORS["card"], fg=COLORS["text"],
                 font=FONTS["body"], anchor="w").pack(anchor="w")
        if hint:
            tk.Label(left, text=hint, bg=COLORS["card"], fg=COLORS["muted"],
                     font=FONTS["small"], anchor="w").pack(anchor="w")

        holder = tk.Frame(self, bg=COLORS["card"])
        holder.pack(side="right", fill="y", pady=6)
        self._holder = holder

        if kind == "text":
            self.entry = ttk.Entry(holder, width=width)
            self.entry.pack(side="right")
        elif kind == "number":
            self.spin = ttk.Spinbox(
                holder, width=8,
                from_=from_ if from_ is not None else 0,
                to=to if to is not None else 100,
                increment=increment if increment is not None else 1)
            self.spin.pack(side="right")
        elif kind == "scale":
            self.scale = ttk.Scale(holder, from_=from_ if from_ is not None else 0.4,
                                   to=to if to is not None else 1.5,
                                   orient="horizontal", length=120)
            self.scale.pack(side="left", padx=(0, 8))
            self.value_label = tk.Label(holder, text="-", bg=COLORS["card"],
                                        fg=COLORS["text"], font=FONTS["body"],
                                        width=5, anchor="e")
            self.value_label.pack(side="left")
            self.scale.bind("<Motion>", self._on_scale_move)
            self.scale.bind("<ButtonRelease-1>", self._on_scale_move)
        elif kind == "choice":
            self.combo = ttk.Combobox(
                holder, state="readonly", width=width, font=FONTS["body"],
                values=list(self._labels or self._values or []))
            self.combo.pack(side="right")
        else:  # readonly
            self.label = tk.Label(holder, text="-", bg=COLORS["card"],
                                  fg=COLORS["muted"], font=FONTS["small"])
            self.label.pack(side="right")

    # ------------------------------------------------------------ 取值/赋值
    def _on_scale_move(self, _evt=None) -> None:
        self.value_label.configure(text=f"{self.scale.get():.2f}")

    def get(self):
        if self.kind == "text":
            return self.entry.get().strip()
        if self.kind == "number":
            raw = self.spin.get().strip()
            try:
                return float(raw) if "." in raw else int(raw)
            except ValueError:
                return 0
        if self.kind == "scale":
            return round(float(self.scale.get()), 2)
        if self.kind == "choice":
            idx = self.combo.current()
            if self._values and 0 <= idx < len(self._values):
                return self._values[idx]
            return self.combo.get()
        return self.label.cget("text")

    def set(self, value) -> None:
        if self.kind == "text":
            self.entry.delete(0, "end")
            self.entry.insert(0, "" if value is None else str(value))
        elif self.kind == "number":
            self.spin.delete(0, "end")
            self.spin.insert(0, "" if value is None else str(value))
        elif self.kind == "scale":
            try:
                self.scale.set(float(value))
            except (TypeError, ValueError):
                self.scale.set(1.0)
            self._on_scale_move()
        elif self.kind == "choice":
            if self._values and value in self._values:
                self.combo.current(self._values.index(value))
            else:
                self.combo.set("" if value is None else str(value))
        else:
            self.label.configure(text="" if value is None else str(value))


class NamesBlock(tk.Frame):
    """逗号分隔名单编辑块（多行文本框 + 说明）。"""

    def __init__(self, master, title: str, hint: str = "", height: int = 2):
        super().__init__(master, bg=COLORS["card"])
        tk.Label(self, text=title, bg=COLORS["card"], fg=COLORS["muted"],
                 font=FONTS["small"], anchor="w").pack(anchor="w",
                                                       pady=(8, 2))
        box = tk.Frame(self, bg=COLORS["border"], padx=1, pady=1)
        box.pack(fill="x")
        self.text = tk.Text(box, height=height, width=1, wrap="char",
                            font=FONTS["body"], bg="#FBFCFE",
                            fg=COLORS["text"], relief="flat",
                            padx=8, pady=6, insertbackground=COLORS["text"])
        self.text.pack(fill="x")
        if hint:
            tk.Label(self, text=hint, bg=COLORS["card"], fg=COLORS["muted"],
                     font=FONTS["small"], anchor="w").pack(anchor="w",
                                                           pady=(2, 0))

    def get(self) -> str:
        return self.text.get("1.0", "end-1c").strip()

    def set(self, value) -> None:
        self.text.delete("1.0", "end")
        if value:
            self.text.insert("1.0", str(value))


class PriorityBlock(tk.Frame):
    """节点优先级列表（上移/下移/置顶）。"""

    def __init__(self, master, title: str, hint: str = "", height: int = 8):
        super().__init__(master, bg=COLORS["card"])
        tk.Label(self, text=title, bg=COLORS["card"], fg=COLORS["text"],
                 font=FONTS["body"], anchor="w").pack(anchor="w")
        if hint:
            tk.Label(self, text=hint, bg=COLORS["card"], fg=COLORS["muted"],
                     font=FONTS["small"], anchor="w").pack(anchor="w",
                                                           pady=(2, 6))
        wrap = tk.Frame(self, bg=COLORS["card"])
        wrap.pack(fill="both", expand=True)
        box = tk.Frame(wrap, bg=COLORS["border"], padx=1, pady=1)
        box.pack(side="left", fill="both", expand=True)
        self.lb = tk.Listbox(
            box, height=height, width=1, exportselection=False,
            font=FONTS["body"], bg="#FBFCFE", fg=COLORS["text"],
            selectbackground=COLORS["accent"], selectforeground="#FFFFFF",
            relief="flat", highlightthickness=0, activestyle="none",
            borderwidth=0)
        self.lb.pack(side="left", fill="both", expand=True)
        btns = tk.Frame(wrap, bg=COLORS["card"])
        btns.pack(side="left", fill="y", padx=(8, 0))
        ttk.Button(btns, text="▲ 上移",
                   command=lambda: self.move(-1)).pack(pady=(0, 4), fill="x")
        ttk.Button(btns, text="▼ 下移",
                   command=lambda: self.move(1)).pack(fill="x")

    def move(self, delta: int) -> None:
        sel = self.lb.curselection()
        if not sel:
            return
        i = int(sel[0])
        j = max(0, min(self.lb.size() - 1, i + delta))
        if i == j:
            return
        item = self.lb.get(i)
        self.lb.delete(i)
        self.lb.insert(j, item)
        self.lb.selection_set(j)
        self.lb.see(j)

    def get(self) -> List[str]:
        return [self.lb.get(i) for i in range(self.lb.size())]

    def set(self, items: Sequence[str]) -> None:
        self.lb.delete(0, "end")
        for it in items or []:
            self.lb.insert("end", it)


def section(parent, title: str, expand: bool = False) -> Tuple[tk.Frame, tk.Frame]:
    """创建一个卡片分组（复用 theme.card），返回 (外层, 内容区)。"""
    outer, body = card(parent, title)
    outer.pack(fill="both" if expand else "x", pady=(0, 10))
    return outer, body


def add_row(body, row: SettingRow) -> SettingRow:
    """把一行配置塞进卡片内容区（行间用 1px 分隔线，视觉整齐）。"""
    row.pack(fill="x")
    return row
