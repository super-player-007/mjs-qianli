"""千里单骑自动化控制台（tkinter GUI）。

界面结构（2026-11-12 视觉重做：浅色卡片式 + 深色日志区）
-------------------------------------------------------
```
┌ 顶部：标题 / 副标题                          ● 运行中 ┐
├ ──────────────────────────────────────────────────────┤
│ 左列（配置）                  右列（运行）              │
│  ┌ 游戏参数 ────────┐        ┌ 运行状态 ───────────┐  │
│  │ 出战武将 / 名单  │        │ 局次 层数 点击 耗时 │  │
│  └─────────────────┘        │ ▓▓▓▓▓░░░░ 进度      │  │
│  ┌ 节点优先级 ──────┐        └────────────────────┘  │
│  │ 列表 + 上移下移  │        ┌ 运行日志 ───────────┐  │
│  └─────────────────┘        │ （深色等宽，按级别   │  │
│  ┌ 脚本参数 ────────┐        │   着色，自动吸底）   │  │
│  │ 缩放/轮次/轮询   │        └────────────────────┘  │
│  └─────────────────┘                                 │
├ 底部：[▶ 启动] [⏸ 暂停] [⏹ 停止]      工作线程：…    │
└──────────────────────────────────────────────────────┘
```

分层（参考一条龙「GUI 与业务解耦」）：
``app.py`` 只做控制（配置/线程/队列），``widgets.py`` 做渲染，
``theme.py`` 管配色字体；业务层完全不知道 GUI 存在。
"""
from __future__ import annotations

import logging
import queue
import threading
import tkinter as tk
from tkinter import ttk, messagebox

from src.gui import config_store
from src.gui.theme import COLORS, FONTS, apply_theme, card, enable_dpi_awareness
from src.gui.widgets import (HeaderBar, LogView, ScrollableColumn,
                             StatusPanel)

#: 节点优先级可用的 key（事件 key 或类型 key）及其说明
PRIORITY_CHOICES = [
    ("hero_wolong", "武将·卧龙出山"), ("mate_feifei", "伙伴·偶遇朏朏"),
    ("hero_shier", "武将·十二阉人"), ("rest", "休息"),
    ("shop", "商店"), ("hero_moja", "武将·墨家巨子"),
    ("hero_fengfeng", "武将·疯疯老道"), ("mate_dog", "伙伴·小狗当道"),
    ("event", "事件（钱袋）"), ("battle", "战斗"), ("hero", "武将(类型)"),
    ("mate", "伙伴(类型)"),
]
CHOICE_LABEL = dict(PRIORITY_CHOICES)

CATEGORY_ORDER = ("信物", "驰援", "资助")

#: 识别设备：配置值 ↔ 下拉框文案
DEVICE_CHOICES = (
    ("auto", "自动（有 GPU 用 GPU）"),
    ("cpu", "仅 CPU"),
    ("dml", "GPU（DirectML）"),
)
DEVICE_LABELS = dict(DEVICE_CHOICES)
DEVICE_BY_LABEL = {label: value for value, label in DEVICE_CHOICES}

POLL_RUNNING_MS = 150      # 运行中轮询间隔
POLL_IDLE_MS = 600         # 空闲时放慢，省 CPU
LOG_BATCH_MAX = 400        # 单次最多刷新的日志行数


class ControlApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title("千里单骑自动化控制台")
        root.geometry("1240x800")
        root.minsize(980, 640)
        apply_theme(root)

        self.cfg = config_store.load_config()
        self.worker = None
        self.pause_event = threading.Event()
        self.stop_event = threading.Event()
        self.log_q: "queue.Queue[str]" = queue.Queue()
        self.stats = {"clicks": 0, "layer": 0, "run": 0, "runs": 1,
                      "state": "idle", "msg": "", "step_s": 0.0, "steps": 0}

        self._build_ui()
        self._load_into_widgets()
        self.root.after(POLL_IDLE_MS, self._poll)

    # ------------------------------------------------------------ 布局
    def _build_ui(self):
        # ⚠ pack 顺序：底部条先占位，否则前面的 expand 容器会把它挤出窗口
        self._build_footer()
        page = tk.Frame(self.root, bg=COLORS["bg"])
        page.pack(fill="both", expand=True, padx=16, pady=(14, 8))

        # 顶部标题条
        self.header = HeaderBar(
            page, "千里单骑自动化控制台",
            "名将杀 · 雷电模拟器 · 1920×1080 · 离线识别")
        self.header.pack(fill="x", pady=(0, 12))

        panes = ttk.PanedWindow(page, orient="horizontal")
        panes.pack(fill="both", expand=True)
        left = ScrollableColumn(panes)
        right = tk.Frame(panes, bg=COLORS["bg"])
        panes.add(left, weight=5)
        panes.add(right, weight=6)

        self._build_config_panel(left.body)
        self._build_status_panel(right)
        self._build_log_panel(right)

    # ---------------------------------------------------------- 左：配置区
    def _build_config_panel(self, parent):
        # --- 游戏参数 ---
        outer, body = card(parent, "游戏参数")
        outer.pack(fill="x", pady=(0, 10))

        row = tk.Frame(body, bg=COLORS["card"])
        row.pack(fill="x")
        tk.Label(row, text="出战武将", bg=COLORS["card"], fg=COLORS["muted"],
                 font=FONTS["small"]).pack(side="left")
        self.e_hero = ttk.Entry(row, width=16)
        self.e_hero.pack(side="left", padx=(8, 8))
        tk.Label(body, text="搜索式选将，支持任意武将名", bg=COLORS["card"],
                 fg=COLORS["muted"], font=FONTS["small"]).pack(
                     anchor="w", pady=(3, 0))

        self.cat_texts = {}
        for cat in CATEGORY_ORDER:
            tk.Label(body, text=f"{cat}武将名单（逗号分隔）", bg=COLORS["card"],
                     fg=COLORS["muted"], font=FONTS["small"]).pack(
                         anchor="w", pady=(8, 2))
            box = tk.Frame(body, bg=COLORS["border"], padx=1, pady=1)
            box.pack(fill="x")
            t = tk.Text(box, height=2, width=1, wrap="char", font=FONTS["body"],
                        bg="#FBFCFE", fg=COLORS["text"], relief="flat",
                        padx=8, pady=6, insertbackground=COLORS["text"])
            t.pack(fill="x")
            self.cat_texts[cat] = t

        tk.Label(body, text="商店商品名单（逗号分隔）", bg=COLORS["card"],
                 fg=COLORS["muted"], font=FONTS["small"]).pack(
                     anchor="w", pady=(8, 2))
        box = tk.Frame(body, bg=COLORS["border"], padx=1, pady=1)
        box.pack(fill="x")
        self.t_shop = tk.Text(box, height=2, width=1, wrap="char", font=FONTS["body"],
                              bg="#FBFCFE", fg=COLORS["text"], relief="flat",
                              padx=8, pady=6, insertbackground=COLORS["text"])
        self.t_shop.pack(fill="x")

        # --- 节点优先级 ---
        outer, body = card(parent, "节点优先级")
        outer.pack(fill="both", expand=True, pady=(0, 10))
        tk.Label(body, text="从上到下，越靠上越优先；不在列表里的类型按规则选最后一个",
                 bg=COLORS["card"], fg=COLORS["muted"],
                 font=FONTS["small"]).pack(anchor="w", pady=(0, 6))

        wrap = tk.Frame(body, bg=COLORS["card"])
        wrap.pack(fill="both", expand=True)
        listbox_box = tk.Frame(wrap, bg=COLORS["border"], padx=1, pady=1)
        listbox_box.pack(side="left", fill="both", expand=True)
        self.lb_priority = tk.Listbox(
            listbox_box, height=8, width=1, exportselection=False,
            font=FONTS["body"], bg="#FBFCFE", fg=COLORS["text"],
            selectbackground=COLORS["accent"], selectforeground="#FFFFFF",
            relief="flat", highlightthickness=0, activestyle="none",
            borderwidth=0)
        self.lb_priority.pack(side="left", fill="both", expand=True)

        btns = tk.Frame(wrap, bg=COLORS["card"])
        btns.pack(side="left", fill="y", padx=(8, 0))
        ttk.Button(btns, text="▲ 上移", command=lambda: self._move(-1)).pack(
            pady=(0, 4), fill="x")
        ttk.Button(btns, text="▼ 下移", command=lambda: self._move(1)).pack(
            fill="x")

        # --- 脚本参数 ---
        outer, body = card(parent, "脚本参数")
        outer.pack(fill="x")
        grid = tk.Frame(body, bg=COLORS["card"])
        grid.pack(fill="x")
        grid.columnconfigure(1, weight=1)

        tk.Label(grid, text="点击间隔缩放", bg=COLORS["card"],
                 fg=COLORS["muted"], font=FONTS["small"]).grid(
                     row=0, column=0, sticky="w")
        self.s_scale = ttk.Scale(grid, from_=0.4, to=1.5, orient="horizontal")
        self.s_scale.grid(row=0, column=1, sticky="we", padx=10)
        self.l_scale = tk.Label(grid, text="0.70", bg=COLORS["card"],
                                fg=COLORS["text"], font=FONTS["body"])
        self.l_scale.grid(row=0, column=2, sticky="e")
        self.s_scale.bind("<Motion>", lambda e: self.l_scale.config(
            text=f"{self.s_scale.get():.2f}"))

        tk.Label(grid, text="执行轮次", bg=COLORS["card"], fg=COLORS["muted"],
                 font=FONTS["small"]).grid(row=1, column=0, sticky="w", pady=(8, 0))
        self.sp_runs = ttk.Spinbox(grid, from_=1, to=50, width=8)
        self.sp_runs.grid(row=1, column=1, sticky="w", padx=10, pady=(8, 0))

        tk.Label(grid, text="轮询间隔(秒)", bg=COLORS["card"], fg=COLORS["muted"],
                 font=FONTS["small"]).grid(row=2, column=0, sticky="w", pady=(8, 0))
        self.sp_poll = ttk.Spinbox(grid, from_=0.5, to=20, increment=0.5, width=8)
        self.sp_poll.grid(row=2, column=1, sticky="w", padx=10, pady=(8, 0))

        tk.Label(grid, text="识别设备", bg=COLORS["card"], fg=COLORS["muted"],
                 font=FONTS["small"]).grid(row=5, column=0, sticky="w", pady=(8, 0))
        self.cb_device = ttk.Combobox(
            grid, state="readonly", width=20,
            values=[label for _, label in DEVICE_CHOICES])
        self.cb_device.grid(row=5, column=1, columnspan=2, sticky="w",
                            padx=10, pady=(8, 0))
        tk.Label(grid, text="GPU 可显著降低 OCR 的 CPU 占用", bg=COLORS["card"],
                 fg=COLORS["muted"], font=FONTS["small"]).grid(
                     row=6, column=0, columnspan=3, sticky="w", pady=(2, 0))

        tk.Label(grid, text="百钱保留线", bg=COLORS["card"], fg=COLORS["muted"],
                 font=FONTS["small"]).grid(row=3, column=0, sticky="w", pady=(8, 0))
        self.e_reserve = ttk.Entry(grid, width=10)
        self.e_reserve.grid(row=3, column=1, sticky="w", padx=10, pady=(8, 0))
        tk.Label(grid, text="武将牌专区余额下限", bg=COLORS["card"],
                 fg=COLORS["muted"], font=FONTS["small"]).grid(
                     row=4, column=0, columnspan=3, sticky="w", pady=(2, 0))

    # ---------------------------------------------------------- 右：状态/日志
    def _build_status_panel(self, parent):
        outer, body = card(parent, "运行状态")
        outer.pack(fill="x", pady=(0, 10))
        self.status = StatusPanel(body)
        self.status.pack(fill="x")

    def _build_log_panel(self, parent):
        outer, body = card(parent, "运行日志")
        outer.pack(fill="both", expand=True)
        self.logview = LogView(body, max_lines=2000, height=18)
        self.logview.pack(fill="both", expand=True)

    def _build_footer(self):
        bar = tk.Frame(self.root, bg=COLORS["bg"])
        bar.pack(side="bottom", fill="x", padx=16, pady=(0, 12))
        self.btn_start = ttk.Button(bar, text="▶  启动", style="Accent.TButton",
                                    command=self.on_start)
        self.btn_start.pack(side="left")
        self.btn_pause = ttk.Button(bar, text="⏸  暂停", command=self.on_pause,
                                    state="disabled")
        self.btn_pause.pack(side="left", padx=8)
        self.btn_stop = ttk.Button(bar, text="⏹  停止", command=self.on_stop,
                                   state="disabled")
        self.btn_stop.pack(side="left")
        ttk.Separator(bar, orient="vertical").pack(side="left", fill="y",
                                                   padx=14)
        ttk.Button(bar, text="保存配置", style="Ghost.TButton",
                   command=self.on_save).pack(side="left")
        ttk.Button(bar, text="加载配置", style="Ghost.TButton",
                   command=self.on_load).pack(side="left", padx=4)
        self.var_thread = tk.StringVar(value="工作线程：未启动")
        tk.Label(bar, textvariable=self.var_thread, bg=COLORS["bg"],
                 fg=COLORS["muted"], font=FONTS["small"]).pack(side="right")

    # ------------------------------------------------------------ 配置
    def _load_into_widgets(self):
        cfg = self.cfg
        self.e_hero.delete(0, "end")
        self.e_hero.insert(0, cfg.get("hero", ""))
        for cat, widget in self.cat_texts.items():
            widget.delete("1.0", "end")
            widget.insert("1.0", "，".join(cfg["categories"].get(cat, [])))
        self.t_shop.delete("1.0", "end")
        self.t_shop.insert("1.0", "，".join(cfg.get("shop_wanted", [])))
        self.lb_priority.delete(0, "end")
        for key in cfg.get("priority", []):
            self.lb_priority.insert("end", f"{key}  ({CHOICE_LABEL.get(key, '?')})")
        self.e_reserve.delete(0, "end")
        self.e_reserve.insert(0, str(cfg.get("shop_reserve", 150)))
        self.s_scale.set(float(cfg.get("tap_scale", 0.7)))
        self.l_scale.config(text=f"{self.s_scale.get():.2f}")
        self.sp_runs.delete(0, "end")
        self.sp_runs.insert(0, str(int(cfg.get("runs", 1))))
        self.sp_poll.delete(0, "end")
        self.sp_poll.insert(0, str(float(cfg.get("poll", 0.5))))
        device = str(cfg.get("ocr_device", "auto") or "auto").lower()
        self.cb_device.set(DEVICE_LABELS.get(device,
                                             DEVICE_LABELS["auto"]))

    def _collect_config(self) -> dict:
        cfg = dict(self.cfg)
        cfg["hero"] = self.e_hero.get().strip() or "钟离眜"
        cats = {}
        for cat, widget in self.cat_texts.items():
            raw = widget.get("1.0", "end")
            names = [x.strip() for chunk in raw.replace("，", ",").split(",")
                     for x in [chunk.strip()] if x.strip()]
            cats[cat] = names
        cfg["categories"] = cats
        raw_shop = self.t_shop.get("1.0", "end")
        cfg["shop_wanted"] = [x.strip()
                              for chunk in raw_shop.replace("，", ",").split(",")
                              for x in [chunk.strip()] if x.strip()]
        try:
            cfg["shop_reserve"] = max(0, int(self.e_reserve.get() or 150))
        except ValueError:
            cfg["shop_reserve"] = 150
        cfg["priority"] = [self.lb_priority.get(i).split()[0]
                           for i in range(self.lb_priority.size())]
        cfg["tap_scale"] = round(float(self.s_scale.get()), 2)
        cfg["runs"] = max(1, int(self.sp_runs.get() or 1))
        cfg["poll"] = max(0.3, float(self.sp_poll.get() or 0.5))
        # 识别设备：文案 → 配置值（auto/cpu/dml）
        cfg["ocr_device"] = DEVICE_BY_LABEL.get(self.cb_device.get(), "auto")
        return cfg

    def on_save(self):
        cfg = self._collect_config()
        path = config_store.save_config(cfg)
        self._log(f"配置已保存：{path}")
        messagebox.showinfo("保存配置", f"已保存到 {path}")

    def on_load(self):
        self.cfg = config_store.load_config()
        self._load_into_widgets()
        self._log("配置已加载")

    # ------------------------------------------------------------ 优先级
    def _move(self, delta: int):
        sel = self.lb_priority.curselection()
        if not sel:
            return
        i = sel[0]
        j = i + delta
        if not (0 <= j < self.lb_priority.size()):
            return
        text = self.lb_priority.get(i)
        self.lb_priority.delete(i)
        self.lb_priority.insert(j, text)
        self.lb_priority.selection_set(j)

    # ------------------------------------------------------------ 控制
    def _log(self, line: str):
        self.log_q.put(line)

    def on_start(self):
        if self.worker and self.worker.is_alive():
            messagebox.showwarning("已在运行", "脚本已在运行中")
            return
        # 挂起看门狗：每 3 分钟把所有线程堆栈 dump 到文件——
        # 真挂死时（如 onnx 推理 hang）无需用户操作即可拿到现场
        import faulthandler
        from pathlib import Path
        dump_path = Path("runtime/hang_dump.txt")
        dump_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            faulthandler.dump_traceback_later(180, repeat=True,
                                              file=open(dump_path, "a"))
        except Exception:  # noqa: BLE001
            pass
        cfg = self._collect_config()
        resolved = config_store.apply_gift_categories(cfg["categories"])
        for line in resolved:
            self._log(f"[名单重复] {line}")
        applied_shop = config_store.apply_shop_wanted(cfg.get("shop_wanted", []))
        reserve = config_store.apply_shop_reserve(cfg.get("shop_reserve", 150))
        self._log(f"[商店保留线] 太平百钱保留 {reserve}（武将牌专区受此约束）")
        self._log("[商店名单] 生效 %d 项：%s" % (len(applied_shop),
                                                "、".join(applied_shop)))
        self.pause_event.clear()
        self.stop_event.clear()
        self._log(f"=== 启动：武将 {cfg['hero']} · {cfg['runs']} 局 · "
                  f"点击缩放 {cfg['tap_scale']} ===")

        handler = _QueueHandler(self.log_q)
        logging.getLogger("mjs").addHandler(handler)

        def worker():
            try:
                # 每次启动都强制重载游戏模块（2026-09-25 事故沉淀）：
                # GUI 进程常驻，Python 只在首次 import 时读代码——之后改了
                # 代码、点「停止→启动」仍跑旧逻辑。reload 按依赖序执行。
                import importlib
                import src.game.node_icon as _m_node
                import src.game.gift as _m_gift
                import src.game.hero_event as _m_he
                import src.game.mate_event as _m_me
                import src.game.moja_event as _m_mo
                import src.game.event_node as _m_en
                import src.game.ambush as _m_am
                import src.game.rest as _m_rest
                import src.game.shop as _m_shop
                import src.game.runner as _m_runner
                for m in (_m_node, _m_gift, _m_he, _m_me, _m_mo, _m_en,
                          _m_am, _m_rest, _m_shop, _m_runner):
                    try:
                        importlib.reload(m)
                    except ImportError:
                        # 冻结环境（PyInstaller）不支持 reload，跳过
                        pass
                self._log("已重新加载游戏模块（当前为磁盘最新代码）")
                # ⚠ reload 会把 shop/gift 的模块级名单重置回内建默认
                #   （2026-11-13 行囊事故：on_start 先应用、reload 后全洗掉，
                #   商店名单变 20 项默认清单 → 行囊不买）。必须重载后重新应用。
                config_store.apply_gift_categories(cfg["categories"])
                config_store.apply_shop_wanted(cfg.get("shop_wanted", []))
                config_store.apply_shop_reserve(cfg.get("shop_reserve", 150))
                logging.getLogger("mjs").info(
                    "[商店名单] 重载后重新应用 %d 项（含行囊=%s）",
                    len(cfg["shop_wanted"]),
                    "行囊" in cfg["shop_wanted"])

                from src.game.runner import run_auto
                cfg_obj = _build_runtime(cfg, self._log)
                run_auto(ctx=cfg_obj["ctx"], log=cfg_obj["log"],
                         hero_name=cfg["hero"],
                         tap_scale=cfg["tap_scale"],
                         node_priority=cfg["priority"],
                         runs=cfg["runs"],
                         poll_sleep=cfg["poll"],
                         pause_event=self.pause_event,
                         stop_event=self.stop_event,
                         status_cb=lambda s: self.stats.update(s))
            except Exception as e:  # noqa: BLE001
                import traceback
                tb = traceback.format_exc()
                self._log(f"[异常] {e!r}")
                self._log(tb)
                logging.getLogger("mjs").error("工作线程异常:\n%s", tb)
                # 状态要明确变成"已停止"，别让用户以为还在跑（2026-11-12）
                self.stats.update({"state": "stopped",
                                   "msg": f"工作线程异常退出：{e!r}"})
            finally:
                logging.getLogger("mjs").removeHandler(handler)
                self._log("=== 工作线程退出 ===")

        self.worker = threading.Thread(target=worker, daemon=True)
        self.worker.start()
        self.var_thread.set("工作线程：运行中")
        self.btn_pause.config(text="⏸  暂停", state="normal")
        self.btn_stop.config(state="normal")
        self.btn_start.config(state="disabled")

    def on_pause(self):
        if self.pause_event.is_set():
            self.pause_event.clear()
            self.btn_pause.config(text="⏸  暂停")
            self._log("继续运行")
        else:
            self.pause_event.set()
            self.btn_pause.config(text="▶  继续")
            self._log("已暂停")

    def on_stop(self):
        self.stop_event.set()
        self.pause_event.clear()
        self._log("停止指令已发出（当前步完成后退出）")
        self.btn_stop.config(state="disabled")

    # ------------------------------------------------------------ 轮询
    def _drain_logs(self) -> None:
        batch = []
        for _ in range(LOG_BATCH_MAX):
            try:
                batch.append(self.log_q.get_nowait())
            except queue.Empty:
                break
        if batch:
            self.logview.append_lines(batch)

    def _poll(self):
        self._drain_logs()
        self.status.update_stats(self.stats)
        self.header.set_state(self.stats.get("state", "idle"))
        running = bool(self.worker and self.worker.is_alive())
        if self.worker and not running:
            self.var_thread.set("工作线程：已退出")
            self.btn_start.config(state="normal")
            self.btn_pause.config(state="disabled", text="⏸  暂停")
            self.btn_stop.config(state="disabled")
            self.worker = None
        self.root.after(POLL_RUNNING_MS if running else POLL_IDLE_MS, self._poll)


class _QueueHandler(logging.Handler):
    """把 logging 记录转发进 GUI 队列（工作线程 → 主线程）。"""

    def __init__(self, q: "queue.Queue[str]"):
        super().__init__(level=logging.INFO)
        self.q = q
        self._persistent = True     # setup_logger 重配置时保留本桥
        self.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s",
                                            datefmt="%H:%M:%S"))

    def emit(self, record):
        try:
            self.q.put(self.format(record))
        except Exception:  # noqa: BLE001
            pass


def _build_runtime(cfg, gui_log):
    """构建 GameContext（设备/OCR/配置），GUI 工作线程内调用。"""
    from run import Config, build_ctx, setup_logger, GAME_PACKAGE
    log = setup_logger("mjs", Config.load().log_dir)
    ctx = build_ctx(Config.load(), log,
                    ocr_device=cfg.get("ocr_device", "auto"))
    gui_log("[识别设备] 请求 %s → 实际 %s" % (
        cfg.get("ocr_device", "auto"),
        "GPU/DirectML" if ctx.ocr.device == "dml" else "CPU"))
    if not ctx.device.is_app_foreground(GAME_PACKAGE):
        gui_log(f"[警告] 当前前台不是名将杀（{ctx.device.current_package() or '未知'}）")
    return {"ctx": ctx, "log": log}


def main():
    enable_dpi_awareness()
    root = tk.Tk()
    ControlApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
