"""暂停提问机制 —— 遇到无法明确判断的选择时必须询问用户，不得臆断。

设计目标（对应需求）
------------------
* 决策点（增益三选一 / 事件选项 / 路线分支 / 是否撤退）自动暂停并提问
* 提问时附带「当前屏幕截图」，用户可直观看到选项，无需肉眼找坐标
* 支持两种交互：终端问答(cli) / 图形弹窗(dialog)
* 每次提问都落盘截图 + 记录用户答复，便于事后把答复沉淀为自动策略
* 超时行为可配置：abort(终止) / default(用推荐项) / retry(重新提问)

对外接口
--------
    asker.ask(title, question, options, screenshot) -> int    # 返回选项下标
"""
from __future__ import annotations

import json
import logging
import queue
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Sequence

import numpy as np

from ..common.utils import now_stamp
from ..vision import annotate


@dataclass
class Choice:
    """一个可选决策项。"""
    label: str                                  # 展示给用户的文字
    desc: str = ""                              # 补充说明（如增益效果描述）
    xy: Optional[Sequence[int]] = None          # 选中后要点击的坐标（实际分辨率）
    kind: str = "generic"                       # 决策类别，用于 hybrid 分流
    score: float = 0.0                          # 内置策略给出的推荐分（越高越推荐）


class Asker:
    """统一的决策提问入口。"""

    def __init__(self,
                 mode: str = "ask",
                 ui: str = "cli",
                 timeout_sec: float = 300,
                 on_timeout: str = "abort",
                 high_risk_kinds: Optional[Sequence[str]] = None,
                 decision_dir: Optional[Path] = None,
                 logger: Optional[logging.Logger] = None) -> None:
        self.mode = mode
        self.ui = ui
        self.timeout_sec = timeout_sec
        self.on_timeout = on_timeout
        self.high_risk_kinds = set(high_risk_kinds or [])
        self.dir = Path(decision_dir) if decision_dir else None
        self.log = logger or logging.getLogger("mjs.ask")
        self._history: List[dict] = []

    # ------------------------------------------------------------------ 判定
    def should_ask(self, kind: str) -> bool:
        """当前模式 + 决策类别是否需要人工确认。"""
        if self.mode == "auto":
            return False
        if self.mode == "hybrid":
            return kind in self.high_risk_kinds
        return True

    # ------------------------------------------------------------------ 主入口
    def ask(self,
            title: str,
            question: str,
            options: Sequence[Choice],
            screenshot: Optional[np.ndarray] = None,
            kind: str = "generic",
            note: str = "") -> int:
        """向用户提问并返回所选下标。

        当 ``mode=auto`` 或类别不属于需人工确认的范围时，直接返回内置推荐项。
        """
        if not options:
            raise ValueError("ask() 至少需要一个选项")

        recommended = self._recommended_index(options)

        if not self.should_ask(kind):
            self.log.info("[自动决策] %s -> %s", title, options[recommended].label)
            self._record(title, question, options, recommended, by="auto", note=note)
            return recommended

        shot_path = self._save_shot(title, screenshot, options)

        self.log.info("=== 需要你确认：%s ===", title)
        self.log.info("%s", question)
        for i, opt in enumerate(options):
            mark = " ★推荐" if i == recommended else ""
            extra = f"  —— {opt.desc}" if opt.desc else ""
            self.log.info("  [%d] %s%s%s", i, opt.label, extra, mark)
        if shot_path:
            self.log.info("  截图: %s", shot_path)

        idx = self._ask_via_ui(title, question, options, shot_path, recommended)

        if idx is None:     # 超时
            if self.on_timeout == "retry":
                self.log.warning("等待超时，重新提问...")
                return self.ask(title, question, options, screenshot, kind, note)
            if self.on_timeout == "default":
                idx = recommended
                self.log.warning("等待超时，采用推荐项: %s", options[idx].label)
            else:
                self._record(title, question, options, None, by="timeout-abort", note=note)
                raise TimeoutError(f"决策超时且策略为 abort: {title}")

        self.log.info("你的选择: [%d] %s", idx, options[idx].label)
        self._record(title, question, options, idx, by="user", note=note)
        return idx

    # ------------------------------------------------------------------ 交互
    def _ask_via_ui(self, title: str, question: str,
                    options: Sequence[Choice],
                    shot_path: Optional[Path],
                    recommended: int) -> Optional[int]:
        if self.ui == "dialog":
            idx = self._ask_dialog(title, question, options, shot_path, recommended)
            if idx is not None:
                return idx
            self.log.warning("图形弹窗不可用，回退到终端问答")
        return self._ask_cli(options)

    def _ask_cli(self, options: Sequence[Choice]) -> Optional[int]:
        prompt = f"请输入选项编号 0-{len(options) - 1}（回车=取消等待，直接输入 q 放弃本次选择）> "
        ans = _input_with_timeout(prompt, self.timeout_sec)
        if ans is None:
            return None
        ans = ans.strip()
        if ans == "":
            return None
        try:
            idx = int(ans)
        except ValueError:
            self.log.warning("输入无法识别，按超时处理")
            return None
        if 0 <= idx < len(options):
            return idx
        self.log.warning("编号超范围: %s", ans)
        return None

    def _ask_dialog(self, title: str, question: str,
                    options: Sequence[Choice],
                    shot_path: Optional[Path],
                    recommended: int) -> Optional[int]:
        """tkinter 弹窗：显示截图 + 每个选项一个按钮。"""
        try:
            import tkinter as tk
            from PIL import Image, ImageTk
        except Exception as exc:  # noqa: BLE001
            self.log.debug("tkinter/PIL 不可用: %s", exc)
            return None

        result: dict = {"idx": None}
        try:
            root = tk.Tk()
            root.title(f"需要确认 - {title}")
            root.attributes("-topmost", True)

            tk.Label(root, text=question, font=("Microsoft YaHei", 12, "bold"),
                     wraplength=880, justify="left").pack(padx=12, pady=(12, 6))

            if shot_path and Path(shot_path).exists():
                pil = Image.open(shot_path)
                max_w = 880
                if pil.width > max_w:
                    ratio = max_w / pil.width
                    pil = pil.resize((int(pil.width * ratio),
                                      int(pil.height * ratio)))
                photo = ImageTk.PhotoImage(pil)
                lbl = tk.Label(root, image=photo)
                lbl.image = photo  # 防 GC
                lbl.pack(padx=12, pady=6)

            frame = tk.Frame(root)
            frame.pack(fill="x", padx=12, pady=12)

            def choose(i: int):
                result["idx"] = i
                root.destroy()

            for i, opt in enumerate(options):
                text = opt.label + (f"（推荐）" if i == recommended else "")
                b = tk.Button(frame, text=text, width=34, height=2,
                              font=("Microsoft YaHei", 11),
                              command=lambda i=i: choose(i))
                b.pack(side="left", padx=6, expand=True, fill="x")

            # 等待超时自动关闭
            root.after(int(self.timeout_sec * 1000), root.destroy)
            root.mainloop()
        except Exception as exc:  # noqa: BLE001
            self.log.warning("弹窗异常: %s", exc)
            return None
        return result["idx"]

    # ------------------------------------------------------------------ 辅助
    @staticmethod
    def _recommended_index(options: Sequence[Choice]) -> int:
        best, best_score = 0, float("-inf")
        for i, opt in enumerate(options):
            if opt.score > best_score:
                best, best_score = i, opt.score
        return best

    def _save_shot(self, title: str, screenshot: Optional[np.ndarray],
                   options: Sequence[Choice]) -> Optional[Path]:
        if screenshot is None or self.dir is None:
            return None
        img = screenshot
        # 把选项坐标标到图上，方便核对
        pts = [(o.xy, o.label) for o in options if o.xy]
        if pts:
            img = annotate.draw_points(img, pts)
        path = self.dir / f"{now_stamp()}_{_safe(title)}.png"
        try:
            return annotate.save(img, path)
        except Exception as exc:  # noqa: BLE001
            self.log.warning("决策截图保存失败: %s", exc)
            return None

    def _record(self, title: str, question: str, options: Sequence[Choice],
                chosen: Optional[int], by: str, note: str = "") -> None:
        rec = {
            "ts": now_stamp("%Y-%m-%d %H:%M:%S"),
            "title": title,
            "question": question,
            "kind": "n/a",
            "options": [{"label": o.label, "desc": o.desc, "kind": o.kind,
                         "score": o.score, "xy": list(o.xy) if o.xy else None}
                        for o in options],
            "chosen": chosen,
            "chosen_label": options[chosen].label if chosen is not None and 0 <= chosen < len(options) else None,
            "by": by,
            "note": note,
        }
        self._history.append(rec)
        if self.dir is None:
            return
        try:
            self.dir.mkdir(parents=True, exist_ok=True)
            with (self.dir / "decisions.jsonl").open("a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        except Exception as exc:  # noqa: BLE001
            self.log.debug("决策记录写入失败: %s", exc)


def _safe(text: str) -> str:
    """把标题转成安全文件名。"""
    keep = []
    for ch in text:
        if ch.isalnum() or ch in "_-" or "\u4e00" <= ch <= "\u9fff":
            keep.append(ch)
        else:
            keep.append("_")
    return ("".join(keep))[:40] or "decision"


def _input_with_timeout(prompt: str, timeout: float) -> Optional[str]:
    """带超时的 input()。超时返回 None（读取线程为守护线程，不会阻塞退出）。"""
    if timeout <= 0:
        try:
            return input(prompt)
        except EOFError:
            return None

    q: "queue.Queue[Optional[str]]" = queue.Queue()

    def _reader() -> None:
        try:
            q.put(input(prompt))
        except EOFError:
            q.put(None)
        except Exception:  # noqa: BLE001
            q.put(None)

    t = threading.Thread(target=_reader, daemon=True)
    t.start()
    try:
        return q.get(timeout=timeout)
    except queue.Empty:
        return None
