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
from src.gui.cards import (NamesBlock, PriorityBlock, SettingRow,
                            add_row, section)
from src.gui.theme import COLORS, FONTS, apply_theme, card, enable_dpi_awareness
from src.gui.widgets import (LOG_FILTERS, HeaderBar, LogView, ScrollableColumn,
                             filter_log_lines, join_names, parse_names,
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

        self._toast_after = None
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
        """卡片式设置（2026-11-13）：一行一个配置、行高固定。

        数据流完全不变——仍是 :meth:`_load_into_widgets` 读配置、
        :meth:`_collect_config` 收集；这里只负责"怎么摆"。
        """
        self.rows = {}

        # --- 游戏参数 ---
        _outer, body = section(parent, "游戏参数")
        self.rows["hero"] = SettingRow(
            body, "hero", "出战武将", "搜索式选将，支持任意武将名", "text")
        add_row(body, self.rows["hero"])

        # --- 武将名单 ---
        _outer, body = section(parent, "武将名单")
        self.cat_blocks = {}
        for cat in CATEGORY_ORDER:
            blk = NamesBlock(body, f"{cat}武将（逗号分隔）")
            blk.pack(fill="x")
            self.cat_blocks[cat] = blk

        # --- 商店 ---
        _outer, body = section(parent, "商店")
        self.shop_block = NamesBlock(body, "商店商品名单（逗号分隔）")
        self.shop_block.pack(fill="x")
        self.rows["shop_reserve"] = SettingRow(
            body, "shop_reserve", "太平百钱保留线", "武将牌专区余额下限",
            "number", from_=0, to=99999, increment=10)
        add_row(body, self.rows["shop_reserve"])

        # --- 节点优先级 ---
        _outer, body = section(parent, "节点优先级", expand=True)
        self.priority_block = PriorityBlock(
            body, "从高到低",
            "越靠上越优先；不在列表里的类型按规则选最后一个")
        self.priority_block.pack(fill="both", expand=True)

        # --- 脚本参数 ---
        _outer, body = section(parent, "脚本参数")
        self.rows["tap_scale"] = SettingRow(
            body, "tap_scale", "点击间隔缩放", "0.4 更快 / 1.5 更稳", "scale",
            from_=0.4, to=1.5)
        add_row(body, self.rows["tap_scale"])
        self.rows["runs"] = SettingRow(
            body, "runs", "执行轮次", "", "number",
            from_=1, to=50, increment=1)
        add_row(body, self.rows["runs"])
        self.rows["poll"] = SettingRow(
            body, "poll", "轮询间隔(秒)", "", "number",
            from_=0.5, to=20, increment=0.5)
        add_row(body, self.rows["poll"])
        self.rows["ocr_device"] = SettingRow(
            body, "ocr_device", "识别设备", "GPU 可显著降低 OCR 的 CPU 占用",
            "choice",
            values=[value for value, _ in DEVICE_CHOICES],
            labels=[label for _, label in DEVICE_CHOICES])
        add_row(body, self.rows["ocr_device"])

    # ---------------------------------------------------------- 右：状态/日志
    def _build_status_panel(self, parent):
        outer, body = card(parent, "运行状态")
        outer.pack(fill="x", pady=(0, 10))
        self.status = StatusPanel(body)
        self.status.pack(fill="x")

    def _build_log_panel(self, parent):
        outer, body = card(parent, "运行日志")
        outer.pack(fill="both", expand=True)

        # 工具条（2026-11-13）：级别过滤 / 自动滚动 / 清屏 / 导出
        bar = tk.Frame(body, bg=COLORS["card"])
        bar.pack(fill="x", pady=(0, 6))
        tk.Label(bar, text="级别", bg=COLORS["card"], fg=COLORS["muted"],
                 font=FONTS["small"]).pack(side="left")
        self.var_log_filter = tk.StringVar(value=LOG_FILTERS[0][0])
        ttk.Combobox(bar, state="readonly", width=10,
                     textvariable=self.var_log_filter,
                     values=[label for label, _ in LOG_FILTERS]).pack(
                         side="left", padx=(6, 14))
        self.var_autoscroll = tk.BooleanVar(value=True)
        # 用 tk.Checkbutton 而不是 ttk：clam 主题的指示器是"✖"字形，看着像报错
        tk.Checkbutton(bar, text="自动滚动", variable=self.var_autoscroll,
                       command=self._on_autoscroll, bg=COLORS["card"],
                       fg=COLORS["text"], activebackground=COLORS["card"],
                       activeforeground=COLORS["text"], selectcolor="#FFFFFF",
                       font=FONTS["small"], bd=0,
                       highlightthickness=0).pack(side="left")
        ttk.Button(bar, text="导出", style="CardGhost.TButton",
                   command=self.on_export_log).pack(side="right", pady=2)
        ttk.Button(bar, text="清屏", style="CardGhost.TButton",
                   command=self.on_clear_log).pack(side="right", padx=(0, 4),
                                                  pady=2)

        self.logview = LogView(body, max_lines=2000, height=18)
        self.logview.pack(fill="both", expand=True)

    def _on_autoscroll(self) -> None:
        self.logview.set_autoscroll(bool(self.var_autoscroll.get()))

    def on_clear_log(self) -> None:
        self.logview.clear()
        self.toast("日志已清空")

    def on_export_log(self) -> None:
        from tkinter import filedialog
        path = filedialog.asksaveasfilename(
            title="导出运行日志", defaultextension=".txt",
            initialfile="运行日志.txt", filetypes=[("文本文件", "*.txt")])
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(self.logview.export_text())
            self.toast(f"日志已导出：{path}")
        except OSError as exc:
            messagebox.showerror("导出失败", str(exc))

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
        # 轻提示（替代一条龙的 InfoBar）：3 秒淡出的状态条右侧文字
        self.var_toast = tk.StringVar(value="")
        tk.Label(bar, textvariable=self.var_toast, bg=COLORS["bg"],
                 fg=COLORS["accent"], font=FONTS["small"]).pack(
                     side="right", padx=(0, 14))

    def toast(self, msg: str, ms: int = 2600) -> None:
        """状态条右侧的轻提示（不打断操作，替代弹窗）。"""
        self.var_toast.set(msg)
        if self._toast_after is not None:
            try:
                self.root.after_cancel(self._toast_after)
            except tk.TclError:
                pass
        self._toast_after = self.root.after(
            ms, lambda: self.var_toast.set(""))

    # ------------------------------------------------------------ 配置
    def _load_into_widgets(self):
        cfg = self.cfg
        self.rows["hero"].set(cfg.get("hero", ""))
        for cat, blk in self.cat_blocks.items():
            blk.set(join_names(cfg["categories"].get(cat, [])))
        self.shop_block.set(join_names(cfg.get("shop_wanted", [])))
        self.rows["shop_reserve"].set(int(cfg.get("shop_reserve", 150)))
        self.priority_block.set(
            [f"{key}  ({CHOICE_LABEL.get(key, '?')})"
             for key in cfg.get("priority", [])])
        self.rows["tap_scale"].set(float(cfg.get("tap_scale", 0.7)))
        self.rows["runs"].set(int(cfg.get("runs", 1)))
        self.rows["poll"].set(float(cfg.get("poll", 0.5)))
        device = str(cfg.get("ocr_device", "auto") or "auto").lower()
        self.rows["ocr_device"].set(device)

    def _collect_config(self) -> dict:
        cfg = dict(self.cfg)
        cfg["hero"] = str(self.rows["hero"].get()).strip() or "钟离眜"
        cfg["categories"] = {cat: parse_names(blk.get())
                             for cat, blk in self.cat_blocks.items()}
        cfg["shop_wanted"] = parse_names(self.shop_block.get())
        try:
            cfg["shop_reserve"] = max(
                0, int(float(self.rows["shop_reserve"].get() or 150)))
        except (TypeError, ValueError):
            cfg["shop_reserve"] = 150
        cfg["priority"] = [str(item).split()[0]
                           for item in self.priority_block.get()]
        cfg["tap_scale"] = round(float(self.rows["tap_scale"].get()), 2)
        cfg["runs"] = max(1, int(float(self.rows["runs"].get() or 1)))
        cfg["poll"] = max(0.3, float(self.rows["poll"].get() or 0.5))
        device = str(self.rows["ocr_device"].get() or "auto").lower()
        cfg["ocr_device"] = device if device in DEVICE_LABELS else "auto"
        return cfg

    def on_save(self):
        cfg = self._collect_config()
        path = config_store.save_config(cfg)
        self._log(f"配置已保存：{path}")
        self.toast(f"已保存：{path}")

    def on_load(self):
        self.cfg = config_store.load_config()
        self._load_into_widgets()
        self._log("配置已加载")

    # ------------------------------------------------------------ 优先级
    def _move(self, delta: int):
        """旧接口保留：委托给卡片式优先级列表（按钮已内置）。"""
        self.priority_block.move(delta)

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
        if self.worker is not None and self.worker.is_alive():
            if not messagebox.askyesno(
                    "确认停止",
                    "停止后当前这一步完成即退出，确定停止吗？"):
                return
        self.stop_event.set()
        self.pause_event.clear()
        self._log("停止指令已发出（当前步完成后退出）")
        self.btn_stop.config(state="disabled")
        self.toast("已发出停止指令")

    # ------------------------------------------------------------ 轮询
    def _drain_logs(self) -> None:
        batch = []
        for _ in range(LOG_BATCH_MAX):
            try:
                batch.append(self.log_q.get_nowait())
            except queue.Empty:
                break
        if batch:
            min_level = dict(LOG_FILTERS).get(self.var_log_filter.get(), "info")
            shown = filter_log_lines(batch, min_level)
            if shown:
                self.logview.append_lines(shown)

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
