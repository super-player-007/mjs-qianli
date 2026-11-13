# -*- coding: utf-8 -*-
"""无黑窗启动 GUI（2026-11-13）。

被 ``启动控制台.bat`` 用 pythonw 调用：本进程没有控制台窗口，
它只做两件事——
1. 确保无黑窗启动器 ``启动控制台.exe`` 存在（不存在就现场编译）；
2. 以**完全分离**的方式拉起该 exe，然后自己退出。

这样双击 .bat 时"黑窗只闪一下"（bat 本身必然有控制台），
而 GUI 由 WinExe 启动器用 pythonw 拉起，全程没有命令行窗口。
之后用户可直接双击 ``启动控制台.exe``，连那一闪都没有。
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXE = ROOT / "启动控制台.exe"


def _log(msg: str) -> None:
    """pythonw 下没有 stdout（sys.stdout is None），print 会抛异常。

    启动器是**无控制台**运行的，任何 print 都可能把进程直接搞崩，
    所以这里统一吞掉写入失败（2026-11-13 踩坑）。
    """
    for stream in (sys.stdout, sys.stderr):
        if stream is None:
            continue
        try:
            print(msg, file=stream)
            return
        except Exception:
            continue


def _detached_flags() -> int:
    """DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP（Windows）。"""
    flags = 0
    if sys.platform == "win32":
        flags = (getattr(subprocess, "DETACHED_PROCESS", 0x00000008)
                 | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200))
    return flags


def _dbg(msg: str) -> None:
    """启动器无控制台：调试信息写文件（runtime/launcher_debug.log）。"""
    try:
        p = ROOT / "runtime" / "launcher_debug.log"
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as fh:
            fh.write(msg + "\n")
    except Exception:
        pass


def main() -> int:
    if not EXE.is_file():
        sys.path.insert(0, str(ROOT / "tools"))
        try:
            import build_launcher
        except Exception as exc:  # noqa: BLE001
            _log("无法导入编译脚本: %r" % (exc,))
            return 1
        ok = build_launcher.build()
        if not ok:
            _dbg("launcher build failed")
            return 1
    try:
        subprocess.Popen([str(EXE)], cwd=str(ROOT),
                         creationflags=_detached_flags(),
                         stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL)
    except OSError as exc:
        _log("启动失败: %r" % (exc,))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
