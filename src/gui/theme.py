# -*- coding: utf-8 -*-
"""GUI 主题（2026-11-12）：配色、字体与 ttk 样式集中管理。

设计取向：**浅色卡片式控制台**——
* 窗口底色浅灰、内容用白色卡片承载，层级靠留白和细边框而不是阴影；
* 主操作用蓝色实心按钮，次要操作用描边/文字按钮，危险操作红色；
* 日志区用深色底 + 等宽字体，和上半部的浅色面板形成分区；
* 字号只保留三档（标题 11b / 正文 10 / 数值 16b），避免界面花。

所有颜色/字体都从这里取，改主题不用翻 app.py。
"""
from __future__ import annotations

import sys
import tkinter as tk
from tkinter import ttk

# ---------------------------------------------------------------- 调色板
COLORS = {
    "bg": "#F4F6F9",          # 窗口底色
    "card": "#FFFFFF",        # 卡片底
    "border": "#E4E8EF",      # 卡片描边
    "text": "#1F2430",        # 主文字
    "muted": "#6B7280",       # 次要文字
    "accent": "#2F6BFF",      # 主色（启动按钮/进度条）
    "accent_dark": "#1F4FD8",
    "success": "#16A34A",
    "warn": "#D97706",
    "danger": "#DC2626",
    "chip": "#F1F4F9",        # 指标卡底色
    "log_bg": "#0F172A",
    "log_text": "#D7DEEA",
    "log_info": "#B6C2D4",
    "log_warn": "#F59E0B",
    "log_error": "#F87171",
}

#: 字体：Windows 中文优先「微软雅黑 UI」，缺字体时回落到雅黑/黑体
if sys.platform == "win32":
    UI_FONT = "Microsoft YaHei UI"
    MONO_FONT = "Consolas"
else:
    UI_FONT = "PingFang SC"
    MONO_FONT = "Menlo"

FONTS = {
    "h1": (UI_FONT, 15, "bold"),
    "h2": (UI_FONT, 11, "bold"),
    "body": (UI_FONT, 10),
    "small": (UI_FONT, 9),
    "metric": (UI_FONT, 16, "bold"),
    "mono": (MONO_FONT, 9),
}


def enable_dpi_awareness() -> None:
    """让 1080p/150% 缩放下界面不糊（Windows 专用，失败静默）。"""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:  # noqa: BLE001 — 老系统没有 shcore
        pass


def apply_theme(root: tk.Tk) -> ttk.Style:
    """应用主题：clam 基底（Windows 原生主题不吃自定义颜色）。"""
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass

    root.configure(bg=COLORS["bg"])
    c = COLORS

    style.configure(".", font=FONTS["body"], background=c["bg"],
                    foreground=c["text"])
    style.configure("TFrame", background=c["bg"])
    style.configure("TLabel", background=c["bg"], foreground=c["text"])
    style.configure("Card.TFrame", background=c["card"],
                    relief="flat", borderwidth=0)
    style.configure("Card.TLabel", background=c["card"], foreground=c["text"])
    style.configure("CardMuted.TLabel", background=c["card"],
                    foreground=c["muted"], font=FONTS["small"])
    style.configure("CardTitle.TLabel", background=c["card"],
                    foreground=c["text"], font=FONTS["h2"])
    style.configure("H1.TLabel", background=c["bg"], foreground=c["text"],
                    font=FONTS["h1"])
    style.configure("Muted.TLabel", background=c["bg"],
                    foreground=c["muted"], font=FONTS["small"])
    # 指标卡
    style.configure("Chip.TFrame", background=c["chip"])
    style.configure("ChipTitle.TLabel", background=c["chip"],
                    foreground=c["muted"], font=FONTS["small"])
    style.configure("ChipValue.TLabel", background=c["chip"],
                    foreground=c["text"], font=FONTS["metric"])

    # 按钮：主操作（实心）/次要（描边）/文字
    style.configure("Accent.TButton", background=c["accent"],
                    foreground="#FFFFFF", borderwidth=0, focusthickness=0,
                    padding=(16, 8), font=(UI_FONT, 10, "bold"))
    style.map("Accent.TButton",
              background=[("active", c["accent_dark"]),
                          ("disabled", "#B8C4DA")],
              foreground=[("disabled", "#EEF2F9")])
    style.configure("TButton", background="#FFFFFF", foreground=c["text"],
                    bordercolor=c["border"], borderwidth=1,
                    padding=(12, 6), relief="flat")
    style.map("TButton",
              background=[("active", "#EEF2F9"), ("disabled", "#F5F6F8")],
              foreground=[("disabled", "#AAB2C0")])
    style.configure("Ghost.TButton", background=c["bg"], borderwidth=0,
                    foreground=c["muted"], padding=(10, 6))
    style.map("Ghost.TButton", background=[("active", "#E9EDF4")])

    # 进度条
    style.configure("Modern.Horizontal.TProgressbar",
                    troughcolor=c["chip"], bordercolor=c["chip"],
                    background=c["accent"], thickness=8)
    # 输入类
    style.configure("TEntry", fieldbackground="#FFFFFF",
                    bordercolor=c["border"], padding=4)
    style.configure("TSpinbox", fieldbackground="#FFFFFF",
                    bordercolor=c["border"], arrowsize=12, padding=3)
    style.configure("TScale", background=c["card"], troughcolor=c["chip"])
    style.configure("TLabelframe", background=c["bg"], borderwidth=0)
    style.configure("TLabelframe.Label", background=c["bg"],
                    foreground=c["muted"], font=FONTS["small"])
    style.configure("TSeparator", background=c["border"])
    style.configure("TNotebook", background=c["bg"], borderwidth=0)
    return style


def card(parent, title: str = "", padding: int = 12):
    """创建一个白色卡片，返回 (外层容器, 内容区 Frame)。

    外层负责描边与圆角观感（用 1px 边框模拟），内容区做真实布局。
    """
    outer = tk.Frame(parent, bg=COLORS["border"], bd=0, highlightthickness=0)
    inner = tk.Frame(outer, bg=COLORS["card"], bd=0)
    inner.pack(fill="both", expand=True, padx=1, pady=1)
    if title:
        head = ttk.Label(inner, text=title, style="CardTitle.TLabel")
        head.pack(anchor="w", padx=padding, pady=(padding, 2))
    body = tk.Frame(inner, bg=COLORS["card"])
    body.pack(fill="both", expand=True, padx=padding,
              pady=(0 if title else padding, padding))
    return outer, body
