"""ADB 设备控制层。

职责
----
* 定位雷电自带 ``adb.exe``，管理设备连接（自检 / 自动重连）
* 截图（``exec-out screencap -p``，二进制安全，无 CRLF 损坏问题）
* 点击 / 滑动 / 长按 / 按键 等输入模拟
* 所有坐标以「实际分辨率」传入；本层不做缩放（缩放由 vision/config 负责）

设计要点
--------
* 每条命令带超时，失败抛出可重试异常，配合 core.retry 使用
* 点击坐标加 ±2px 抖动、点击后随机延时，模拟人工手感
* Windows 下隐藏子进程控制台窗口，避免闪黑框
"""
from __future__ import annotations

import logging
import os
import random
from pathlib import Path
from pathlib import Path
import subprocess
import time
from typing import List, Optional, Sequence, Tuple

import cv2
import numpy as np

_IS_WIN = os.name == "nt"
_NO_WINDOW = subprocess.CREATE_NO_WINDOW if _IS_WIN else 0


class DeviceError(RuntimeError):
    """adb 交互失败。"""


class ADBDevice:
    """一个 ADB 目标设备（此处即雷电模拟器实例）。"""

    def __init__(self,
                 adb_path: str,
                 serial: str = "",
                 auto_connect: bool = True,
                 connect_host: str = "127.0.0.1:5555",
                 cmd_timeout: float = 20.0,
                 logger: Optional[logging.Logger] = None) -> None:
        self.adb_path = adb_path
        self.serial = serial
        self.auto_connect = auto_connect
        self.connect_host = connect_host
        self.cmd_timeout = cmd_timeout
        self.log = logger or logging.getLogger("mjs.adb")
        self._size: Optional[Tuple[int, int]] = None

    # =============================================================== 底层命令
    def _base(self, serial: Optional[str] = None) -> List[str]:
        cmd = [self.adb_path]
        target = serial if serial is not None else self.serial
        if target:
            cmd += ["-s", target]
        return cmd

    def _run(self,
             args: Sequence[str],
             timeout: Optional[float] = None,
             binary: bool = False,
             check: bool = True) -> subprocess.CompletedProcess:
        cmd = self._base() + list(args)
        try:
            proc = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=timeout or self.cmd_timeout,
                creationflags=_NO_WINDOW,
            )
        except subprocess.TimeoutExpired as exc:
            raise DeviceError(f"adb 命令超时: {' '.join(cmd)}") from exc
        except FileNotFoundError as exc:
            raise DeviceError(f"找不到 adb 可执行文件: {self.adb_path}") from exc

        if check and proc.returncode != 0:
            err = (proc.stderr or b"").decode("utf-8", "ignore").strip()
            raise DeviceError(f"adb 返回码 {proc.returncode}: {err or ' '.join(cmd)}")

        if not binary:
            # 包一层便于调用方直接拿到文本
            proc.stdout = proc.stdout.decode("utf-8", "ignore")  # type: ignore[assignment]
            proc.stderr = proc.stderr.decode("utf-8", "ignore")  # type: ignore[assignment]
        return proc

    def shell(self, cmd: str, timeout: Optional[float] = None) -> str:
        return self._run(["shell", cmd], timeout=timeout).stdout  # type: ignore[return-value]

    # ================================================================ 连接管理
    def list_devices(self) -> List[str]:
        out = self._run(["devices"], check=False).stdout  # type: ignore[assignment]
        serials: List[str] = []
        for line in str(out).splitlines():
            line = line.strip()
            if not line or line.startswith("List of devices"):
                continue
            parts = line.split()
            if len(parts) >= 2 and parts[1] == "device":
                serials.append(parts[0])
        return serials

    def ensure_connected(self) -> str:
        """确保有可用设备并返回其序列号；必要时尝试主动 connect。"""
        serials = self.list_devices()
        if serials:
            if not self.serial or self.serial not in serials:
                if self.serial:
                    self.log.warning("目标设备 %s 不在线，改用 %s", self.serial, serials[0])
                self.serial = serials[0]
            self.log.info("设备已连接: %s", self.serial)
            return self.serial

        if self.auto_connect:
            self.log.warning("未发现设备，尝试 connect %s", self.connect_host)
            try:
                self._run(["connect", self.connect_host], check=False, timeout=8)
            except DeviceError:
                pass
            time.sleep(1.0)
            serials = self.list_devices()
            if serials:
                self.serial = serials[0]
                self.log.info("重连成功: %s", self.serial)
                return self.serial

        raise DeviceError(
            "未发现可用 ADB 设备。请确认雷电模拟器已启动，"
            f"或用 `{self.adb_path} connect {self.connect_host}` 手动连接。")

    def wait_ready(self, timeout: float = 30.0) -> None:
        """等待系统启动完成（sys.boot_completed=1）。"""
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                val = self.shell("getprop sys.boot_completed").strip()
                if val == "1":
                    return
            except DeviceError:
                pass
            time.sleep(1.0)
        self.log.warning("等待设备就绪超时，继续尝试执行")

    # ================================================================== 基础信息
    @property
    def size(self) -> Tuple[int, int]:
        """实际屏幕分辨率 (w, h)。"""
        if self._size is None:
            out = self.shell("wm size")
            w = h = 0
            for token in str(out).replace(":", " ").split():
                if "x" in token and token.replace("x", "").isdigit():
                    w, h = (int(v) for v in token.split("x"))
            self._size = (w, h) if w and h else (1920, 1080)
        return self._size

    def foreground_activity(self) -> str:
        """返回当前前台 Activity（用于判断游戏是否在最前）。"""
        out = self.shell("dumpsys window")
        for line in str(out).splitlines():
            if "mCurrentFocus" in line:
                return line.strip()
        return ""

    # ==================================================================== 截图
    #: 截图协议：raw（默认，实测快 2.5 倍）/ png（兜底）
    SCREENSHOT_MODE = "raw"
    #: 截图首次失败时是否自动重启 adb 自愈。
    #: 默认关（2026-11-12）：单测里一旦失败就会真的 kill-server，
    #: 每个用例白等 10-20s，整个套件像卡死；运行期由 build_ctx 打开。
    AUTO_RECOVER = False

    def recover(self, timeout: float = 60.0) -> bool:
        """设备失联自愈：重启 adb 服务 → 等设备回来 → **验证真能出图**。

        2026-11-12 事故：连跑两小时后 `screencap` 开始超时（连续 4 次 ×15s），
        异常一路抛到工作线程，把整个 20 局连跑打断。自愈分两步：
        1) 重启 adb 服务（最常见是 adb 连接半死）；
        2) 用一次真实截图验证——`adb devices` 通但模拟器冻死很常见，
           只看设备列表会误判"已恢复"。

        不自动重启模拟器（由用户决定），失败时日志明确提示。
        """
        self.log.warning("设备无响应，尝试重启 adb 服务…")
        for args in (["kill-server"], ["start-server"]):
            try:
                self._run(args, check=False, timeout=10)
            except Exception:  # noqa: BLE001 — 自愈步骤失败不抛出
                pass
            time.sleep(1.0)
        end = time.time() + max(5.0, timeout)
        while time.time() < end:
            try:
                serials = self.list_devices()
                if serials:
                    if not self.serial or self.serial not in serials:
                        self.serial = serials[0]
                    proc = self._run(["exec-out", "screencap"],
                                     binary=True, timeout=8)
                    if proc.stdout and len(proc.stdout) > 1000:
                        self.log.info("设备已恢复: %s", self.serial)
                        return True
            except Exception:  # noqa: BLE001
                pass
            time.sleep(2.0)
        self.log.error("adb 已重启但截不到图——模拟器可能已卡死或已退出，请检查/重启雷电模拟器")
        return False

    @staticmethod
    def parse_raw_screencap(buf: bytes) -> np.ndarray:
        """解析 ``screencap`` 原始输出（RGBA_8888 + 头）为 BGR ndarray。

        头结构：width/height/format 各 uint32（小端），Android 8+ 再追加
        colorspace 4 字节 → 16 字节头；更早版本 12 字节。用「剩余长度 ==
        w*h*4」判定，不猜系统版本。

        2026-11-12 实测（雷电 1920×1080）：raw 抓取 374ms + 解析 28ms，
        PNG 抓取 984ms + 解码 46ms —— 每帧省 ~0.6s，而一局有 150+ 次
        截图，是全局最大的单点提速。

        通道顺序：raw 内存为 RGBA，必须 ``COLOR_RGBA2BGR``（用 BGRA2BGR
        或直接丢 alpha 会红蓝互换，实测像素差 16.3）。
        """
        import struct

        if len(buf) < 12:
            raise DeviceError("raw 截图数据过短")
        w, h, _fmt = struct.unpack_from("<III", buf, 0)
        if w <= 0 or h <= 0 or w > 8192 or h > 8192:
            raise DeviceError(f"raw 截图头异常: {w}x{h}")
        need = w * h * 4
        if len(buf) == 12 + need:
            offset = 12
        elif len(buf) == 16 + need:
            offset = 16
        else:
            raise DeviceError(f"raw 截图长度不符: len={len(buf)} "
                              f"期望 {12 + need} 或 {16 + need}")
        arr = np.frombuffer(buf, dtype=np.uint8, count=need,
                            offset=offset).reshape(h, w, 4)
        return cv2.cvtColor(arr, cv2.COLOR_RGBA2BGR)

    def screenshot(self, retries: int = 2) -> np.ndarray:
        """抓取屏幕，返回 BGR ndarray。

        默认 raw 模式（~0.4s/帧），解析失败自动回退 PNG（~1.0s，兼容性
        最好）；两者像素一致（实测 mean diff 0.07）。
        """
        last: Optional[Exception] = None
        recovered = False
        for attempt in range(retries + 1):
            # 首轮 raw+png；若刚自愈成功也优先 raw（恢复后设备是好的，
            # raw 快 2.5 倍）；否则后续轮次用兼容性最好的 png
            modes = ("raw", "png") if (attempt == 0 or recovered) else ("png",)
            for mode in modes:
                try:
                    if mode == "raw":
                        proc = self._run(["exec-out", "screencap"],
                                         binary=True, timeout=15)
                        img = self.parse_raw_screencap(proc.stdout)  # type: ignore[arg-type]
                    else:
                        proc = self._run(["exec-out", "screencap", "-p"],
                                         binary=True, timeout=15)
                        buf = np.frombuffer(proc.stdout, dtype=np.uint8)  # type: ignore[arg-type]
                        img = cv2.imdecode(buf, cv2.IMREAD_COLOR)
                        if img is None or img.size == 0:
                            raise DeviceError("截图解码失败（数据为空或非 PNG）")
                    self._size = (img.shape[1], img.shape[0])
                    return img
                except Exception as exc:  # noqa: BLE001
                    last = exc
                    self.log.warning("截图失败(%d/%d, %s): %s", attempt + 1,
                                     retries + 1, mode, exc)
            # 首轮两种协议都失败 → 大概率 adb 连接半死，先自愈再重试
            if attempt == 0 and self.AUTO_RECOVER and not recovered:
                recovered = self.recover(timeout=20.0)
            time.sleep(0.5)
        raise DeviceError(f"截图连续失败: {last}")

    # ==================================================================== 输入
    def tap(self, x: int, y: int, jitter_px: int = 2) -> None:
        """点击屏幕坐标（实际分辨率）。"""
        if jitter_px:
            x += random.randint(-jitter_px, jitter_px)
            y += random.randint(-jitter_px, jitter_px)
        self.shell(f"input tap {int(x)} {int(y)}")

    def swipe(self, x1: int, y1: int, x2: int, y2: int,
              duration_ms: int = 350) -> None:
        self.shell(f"input swipe {int(x1)} {int(y1)} {int(x2)} {int(y2)} {int(duration_ms)}")

    def long_press(self, x: int, y: int, duration_ms: int = 900) -> None:
        # input swipe 起点=终点 即为长按
        self.shell(f"input swipe {int(x)} {int(y)} {int(x)} {int(y)} {int(duration_ms)}")

    def keyevent(self, code: int) -> None:
        """发送按键，如 3(HOME) / 4(BACK) / 26(POWER)。"""
        self.shell(f"input keyevent {int(code)}")

    def back(self) -> None:
        self.keyevent(4)

    def home(self) -> None:
        self.keyevent(3)

    def wake(self) -> None:
        """点亮并尝试解锁屏幕。"""
        self.shell("input keyevent 224")   # WAKEUP
        time.sleep(0.4)
        self.swipe(*self.size[0] // 2, int(self.size[1] * 0.8),
                   self.size[0] // 2, int(self.size[1] * 0.3), 200)

    # =============================================================== 进程/应用
    def current_package(self) -> str:
        out = self.foreground_activity()
        # 形如: mCurrentFocus=Window{... u0 com.ztgame.mjs/com....Activity}
        for token in out.replace("}", " ").split():
            if "/" in token and "." in token:
                return token.split("/")[0]
        return ""

    def is_app_foreground(self, package: str = "com.ztgame.mjs") -> bool:
        return self.current_package() == package

    def launch_app(self, package: str = "com.ztgame.mjs") -> None:
        """通过 monkey 拉起应用（不需要知道入口 Activity）。"""
        self.shell(f"monkey -p {package} -c android.intent.category.LAUNCHER 1")

    # ============================================================== 中文文本输入
    # ADB 原生 `input text` 只支持 ASCII，输入中文会静默失败（不报错也不上屏）。
    # 方案：安装 ADBKeyboard（一个「无声」输入法，不弹键盘），
    #       切为默认输入法后通过广播把文本送进去。
    #   APK   : tools/vendor/ADBKeyboard.apk（随项目携带）
    #   IME id: com.android.adbkeyboard/.AdbIME
    #   广播  : action=ADB_INPUT_TEXT, extra=msg
    ADB_IME_ID = "com.android.adbkeyboard/.AdbIME"
    ADB_IME_PKG = "com.android.adbkeyboard"

    def ime_list(self) -> str:
        return self.shell("ime list -s")

    def ime_installed(self) -> bool:
        out = self.shell("pm list packages")
        return self.ADB_IME_PKG in str(out)

    #: 随包携带的 ADBKeyboard.apk 候选路径（依次查找，2026-10-10 绿色版自动安装）
    ADB_IME_APK_CANDIDATES = ("bin/ADBKeyboard.apk",
                              "tools/vendor/ADBKeyboard.apk")

    def _ime_apk_path(self) -> Optional[str]:
        """找到随包携带的 ADBKeyboard.apk；没有则 None。"""
        for cand in self.ADB_IME_APK_CANDIDATES:
            if Path(cand).exists():
                return cand
        return None

    def ime_install(self) -> bool:
        """安装随包携带的 ADBKeyboard.apk（绿色版分发用，2026-10-10）。

        Returns
        -------
        安装成功（或本就无需安装）返回 True；找不到 APK 或安装失败返回 False。
        """
        if self.ime_installed():
            return True
        apk = self._ime_apk_path()
        if apk is None:
            self.log.error("未安装 ADBKeyboard 且未找到随包 APK（查找过 %s）",
                           "、".join(self.ADB_IME_APK_CANDIDATES))
            return False
        self.log.info("正在安装 ADBKeyboard（%s）…", apk)
        out = str(self._run(["install", "-r", apk]))
        ok = self.ime_installed()
        self.log.info("ADBKeyboard 安装%s", "成功" if ok else "失败：" + out[-120:])
        return ok

    def ime_ensure(self) -> bool:
        """确保 ADBKeyboard 已启用且为当前默认输入法。幂等，可反复调用。

        未安装时尝试自动安装随包 APK（2026-10-10：绿色版分发到其他电脑
        首次选将零手工——原实现只报错让手动 adb install）。
        """
        if not self.ime_installed() and not self.ime_install():
            return False
        self.shell(f"ime enable {self.ADB_IME_ID}")
        self.shell(f"settings put secure default_input_method {self.ADB_IME_ID}")
        cur = str(self.shell("settings get secure default_input_method")).strip()
        ok = cur == self.ADB_IME_ID
        if not ok:
            self.log.warning("默认输入法切换失败，当前=%s", cur or "(空)")
        return ok

    def input_text(self, text: str, timeout: float = 20.0) -> bool:
        """输入文本（支持中文）。

        用 ``subprocess`` 以参数列表方式调用，绕开 shell 转义；
        ``_run`` 未启用 ``shell=True``，中文会以 UTF-8 原样传给设备。
        """
        if not text:
            return True
        proc = self._run(["shell", "am", "broadcast",
                          "-a", "ADB_INPUT_TEXT",
                          "--es", "msg", text],
                         timeout=timeout, check=False)
        out = str(proc.stdout or "")
        if "Broadcast completed" not in out:
            self.log.warning("文本输入可能未生效: %.60s", out.strip())
            return False
        return True

    def clear_input(self, count: int = 24) -> None:
        """清空输入框：光标移到末尾后连按删除键。"""
        self.keyevent(123)                      # KEYCODE_MOVE_END
        self.shell("input keyevent " + " ".join(["67"] * int(count)))
