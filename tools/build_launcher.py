# -*- coding: utf-8 -*-
"""编译无黑窗启动器（2026-11-13）。

为什么用 Python 而不是纯 .bat：
    csc 的输出文件名如果含中文，在 cmd 的 GBK 代码页下会报
    ``CS2021 文件名太长或无效``（真实踩坑）。Python 源码是 UTF-8，
    路径全程按 Unicode 处理，最稳。

产物：项目根目录的 ``启动控制台.exe``（5KB WinExe，不入库）。
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "tools" / "launcher" / "启动控制台.cs"
TARGET = ROOT / "启动控制台.exe"


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


def _dbg(msg: str) -> None:
    """无控制台环境下把编译诊断写文件，便于排查（2026-11-13）。"""
    try:
        p = ROOT / "runtime" / "launcher_debug.log"
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as fh:
            fh.write(msg + "\n")
    except Exception:
        pass


def find_csc() -> str | None:
    """找 Windows 自带的 C# 编译器（.NET Framework 4.x）。"""
    win = Path(os.environ.get("WINDIR", r"C:\Windows"))
    for parts in (("Microsoft.NET", "Framework64", "v4.0.30319"),
                  ("Microsoft.NET", "Framework", "v4.0.30319")):
        path = win.joinpath(*parts, "csc.exe")
        if path.is_file():
            return str(path)
    return shutil.which("csc") or None


def build(force: bool = False) -> bool:
    """编译启动器；已存在且不强制时直接返回 True。"""
    if TARGET.is_file() and not force:
        return True
    csc = find_csc()
    if csc is None:
        _log("[ERROR] 找不到 csc.exe：需要 .NET Framework 4.x")
        return False
    if not SOURCE.is_file():
        _log(f"[ERROR] 缺少源码：{SOURCE}")
        return False

    # 先输出到 **ASCII 相对短路径**（避开 csc 的 GBK/中文路径问题 + 临时目录
    # 权限问题：曾出现 CS0016 未能写入输出文件（拒绝访问））
    build_dir = ROOT / "runtime" / "launcher_build"
    build_dir.mkdir(parents=True, exist_ok=True)
    out = build_dir / "launcher.exe"
    if out.exists():
        try:
            out.unlink()
        except OSError:
            pass
    cmd = [csc, "/nologo", "/target:winexe", "/optimize+",
           "/codepage:65001", "/r:System.Windows.Forms.dll",
           f"/out:{out}", str(SOURCE)]
    env = dict(os.environ, TMP=str(build_dir), TEMP=str(build_dir))
    proc = subprocess.run(cmd, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", env=env)
    if proc.returncode != 0 or not out.is_file():
        _dbg("csc cmd: %s" % " ".join(cmd))
        _dbg("csc rc=%s out=%r err=%r" % (proc.returncode,
                                          (proc.stdout or "")[-300:],
                                          (proc.stderr or "")[-300:]))
        _log("[ERROR] 编译失败")
        _log((proc.stdout or "")[-800:])
        _log((proc.stderr or "")[-800:])
        return False
    tmp_target = TARGET.with_name(TARGET.name + ".tmp")
    shutil.copyfile(out, tmp_target)
    os.replace(tmp_target, TARGET)
    _log(f"OK: {TARGET.name}")
    return True


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    return 0 if build(force="--force" in args) else 1


if __name__ == "__main__":
    raise SystemExit(main())
