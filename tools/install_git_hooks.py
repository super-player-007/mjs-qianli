#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""安装/卸载 git 钩子：推送前脱敏扫描 + 只允许推送 main。

用法：
  .venv/Scripts/python.exe tools/install_git_hooks.py            # 安装 pre-push
  .venv/Scripts/python.exe tools/install_git_hooks.py --uninstall
"""
from __future__ import annotations

import argparse
import os
import stat
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

PRE_PUSH = r"""#!/bin/sh
# 推送前脱敏扫描（由 tools/install_git_hooks.py 生成，勿手改；约束见 AGENTS.md 第八节）
# 1) 只允许推送 refs/heads/main：禁止 --tags / --all / 其它分支
# 2) 推送前扫描 tracked 文件是否含凭据、本机路径、个人信息、禁止入库的产物
root=$(git rev-parse --show-toplevel) || exit 1
refused=""
while read -r local_ref local_sha remote_ref remote_sha; do
  case "$remote_ref" in
    refs/heads/main) ;;
    *) refused="$refused $remote_ref" ;;
  esac
done
if [ -n "$refused" ]; then
  echo "[privacy] 拒绝推送：$refused" >&2
  echo "[privacy] 只允许推送 refs/heads/main（禁止 --tags / --all，见 AGENTS.md 第八节）" >&2
  exit 1
fi
py="$root/.venv/Scripts/python.exe"
if [ ! -x "$py" ]; then
  if command -v python >/dev/null 2>&1; then
    py="python"
  elif command -v python3 >/dev/null 2>&1; then
    py="python3"
  else
    echo "[privacy] 找不到 Python，跳过脱敏扫描（请手动运行 tools/scan_sensitive.py）" >&2
    exit 0
  fi
fi
exec "$py" "$root/tools/scan_sensitive.py"
"""


def hooks_dir() -> Path:
    p = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "--git-path", "hooks"],
                       capture_output=True, text=True)
    if p.returncode != 0:
        raise SystemExit("[hooks] 当前目录不是 git 仓库")
    hp = Path(p.stdout.strip())
    if not hp.is_absolute():
        hp = ROOT / hp
    return hp


def install() -> int:
    hp = hooks_dir()
    hp.mkdir(parents=True, exist_ok=True)
    target = hp / "pre-push"
    target.write_text(PRE_PUSH, encoding="utf-8", newline="\n")
    target.chmod(target.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    print(f"[hooks] 已安装 {target}")
    print("[hooks] 生效后：push 前自动脱敏扫描；只允许推送 main")
    return 0


def uninstall() -> int:
    target = hooks_dir() / "pre-push"
    if target.exists():
        target.unlink()
        print(f"[hooks] 已删除 {target}")
    else:
        print("[hooks] 未安装，无需删除")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="安装/卸载 git 脱敏钩子")
    ap.add_argument("--uninstall", action="store_true", help="卸载 pre-push 钩子")
    args = ap.parse_args()
    return uninstall() if args.uninstall else install()


if __name__ == "__main__":
    sys.exit(main())
