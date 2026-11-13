"""主引擎：识别 -> 决策 -> 执行 的循环。

关键能力
--------
* 每轮：抓屏 -> 判定界面 -> 调用处理器 -> 按节奏休眠
* 卡死检测：连续 N 轮画面无变化则告警并询问用户
* 逐帧容错：单轮异常不会中断整体流程（可配置最大连续异常数）
* dry-run（只观察不点击）：标定/调试阶段的默认安全模式
* 全流程日志 + 异常截图归档
"""
from __future__ import annotations

import hashlib
import logging
import time
from typing import List, Optional

import cv2

from ..common.utils import rand_delay
from ..vision.annotate import save
from ..game.context import Frame, GameContext
from ..game.screen import (A_ABORT, A_CONTINUE, A_DONE, A_HANDOFF, A_UNKNOWN,
                           A_WAIT, ScreenSpec, build_registry)
from .asker import Choice


class Engine:
    """单局自动化引擎。"""

    def __init__(self,
                 ctx: GameContext,
                 dry_run: bool = False,
                 max_rounds: int = 400,
                 stall_limit: int = 30,
                 max_errors: int = 5) -> None:
        self.ctx = ctx
        self.dry_run = dry_run
        self.max_rounds = max_rounds
        self.stall_limit = stall_limit
        self.max_errors = max_errors
        self.registry: List[ScreenSpec] = build_registry()
        self.log = ctx.log
        self._prev_sig: Optional[str] = None
        self._idle = 0
        self._errors = 0
        self.stats = {"rounds": 0, "actions": 0, "screens": {}}

    # ------------------------------------------------------------------ 抓屏
    def capture(self, index: int, save_shot: bool = False) -> Frame:
        img = self.ctx.device.screenshot()
        path = None
        if save_shot:
            try:
                path = save(img, self.ctx.cfg.shot_dir / f"frame_{index:05d}.png")
            except Exception as exc:  # noqa: BLE001
                self.log.debug("帧截图保存失败: %s", exc)
        return Frame(image=img, index=index, ts=time.time(), path=path)

    # ------------------------------------------------------------------ 判定
    def detect(self, frame: Frame) -> ScreenSpec:
        for spec in self.registry:
            try:
                detail = spec.detect(self.ctx, frame)
            except Exception as exc:  # noqa: BLE001
                self.log.debug("判定 %s 异常: %s", spec.name, exc)
                continue
            if detail:
                frame.__dict__["_detail"] = detail
                return spec
        return self.registry[-1]   # unknown

    @staticmethod
    def _signature(frame: Frame) -> str:
        """画面指纹：缩略图哈希，用于卡死检测。"""
        small = cv2.resize(frame.image, (64, 36))
        return hashlib.md5(small.tobytes()).hexdigest()

    # ------------------------------------------------------------------ 主循环
    def run(self) -> str:
        ctx = self.ctx
        ctx.mark("t_start", time.time())
        self.log.info("引擎启动：dry_run=%s max_rounds=%d stall_limit=%d",
                      self.dry_run, self.max_rounds, self.stall_limit)

        for i in range(1, self.max_rounds + 1):
            self.stats["rounds"] = i
            try:
                frame = self.capture(i)
                spec = self.detect(frame)
                detail = frame.__dict__.get("_detail", "")
                prev = ctx.get_state("_cur_screen")
                ctx.mark("_cur_screen", spec.name)
                ctx.mark("_cur_screen_desc", spec.desc)

                if spec.name != prev:
                    self.log.info("→ 界面: %s (%s) %s", spec.name, spec.desc, detail)
                else:
                    self.log.debug("  界面: %s %s", spec.name, detail)
                self.stats["screens"][spec.name] = self.stats["screens"].get(spec.name, 0) + 1

                # 卡死检测
                sig = self._signature(frame)
                if sig == self._prev_sig:
                    self._idle += 1
                else:
                    self._idle = 0
                    self._prev_sig = sig

                if self._idle >= self.stall_limit:
                    if not self._on_stall(frame, spec):
                        return "aborted"
                    self._idle = 0

                # dry-run：只报告不操作
                if self.dry_run:
                    self.log.info("   [dry-run] 识别为 %s，本轮不执行任何点击", spec.name)
                    poll = float(ctx.cfg.get("timing.poll_interval", 0.35))
                    rand_delay([poll, poll * 1.6])
                    continue

                action = spec.handle(ctx, frame, detail)
                if action in (A_CONTINUE, A_WAIT):
                    self._errors = 0
                    if action == A_CONTINUE:
                        self.stats["actions"] += 1
                    delay = ctx.cfg.get("timing.action_interval", [0.35, 0.85])
                    rand_delay(delay)
                    continue
                if action == A_DONE:
                    self.log.info("本局流程结束（正常），统计: %s", self.stats)
                    return "done"
                if action == A_ABORT:
                    self.log.warning("用户/策略要求终止，统计: %s", self.stats)
                    return "aborted"
                if action == A_HANDOFF:
                    self.log.info("流程交还给用户（后续段尚未标定），统计: %s", self.stats)
                    return "handoff"
                if action == A_UNKNOWN:
                    continue

            except Exception as exc:  # noqa: BLE001
                self._errors += 1
                self.log.exception("第 %d 轮出错(%d/%d): %s", i, self._errors, self.max_errors, exc)
                self._archive_error(i, exc)
                if self._errors >= self.max_errors:
                    self.log.error("连续异常达到上限，终止运行")
                    return "error"
                time.sleep(1.0)

        self.log.warning("达到最大轮次 %d，退出", self.max_rounds)
        return "max_rounds"

    # -------------------------------------------------------------- 异常处理
    def _archive_error(self, index: int, exc: Exception) -> None:
        if not self.ctx.cfg.get("runtime.save_shot_on_error", True):
            return
        try:
            img = self.ctx.device.screenshot()
            path = save(img, self.ctx.cfg.shot_dir / f"error_{index:05d}.png")
            self.log.info("异常截图已存档: %s", path)
        except Exception:  # noqa: BLE001
            self.log.debug("异常截图失败", exc_info=True)

    def _on_stall(self, frame: Frame, spec: ScreenSpec) -> bool:
        """画面长时间无变化时的处理：询问用户。返回 False 表示终止。"""
        self.log.warning("画面连续 %d 轮无变化（当前界面: %s）", self._idle, spec.name)
        choice = self.ctx.asker.ask(
            title="疑似卡住",
            question=f"连续 {self._idle} 轮画面没有变化，当前识别为「{spec.desc}」。"
                     "脚本可能卡住了，请指示：",
            options=[
                Choice("继续等待（可能在加载/战斗中）", kind="wait"),
                Choice("我已手动处理，继续", kind="manual_done"),
                Choice("重新抓屏再识别一次", kind="retry"),
                Choice("终止脚本", kind="abort"),
            ],
            screenshot=frame.image, kind="stall")
        return choice != 3
