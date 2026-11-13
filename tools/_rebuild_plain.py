# -*- coding: utf-8 -*-
"""重建未加密版（当前源码：含刷新弹窗自动处理等全部修复）。"""
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

os.environ.pop("PYTHONPATH", None)
ROOT = Path.cwd().resolve()


def _tasklist_has(name: str) -> bool:
    """进程名是否在运行。tasklist 输出是 GBK——必须显式按 GBK 解码。

    2026-11-12 事故：PYTHONUTF8=1 下 text=True 按 UTF-8 解码 GBK 输出
    得到乱码，"千里单骑助手.exe" 永远匹配不上，自动关闭守卫形同虚设
    （构建撞上被锁日志 WinError 32）。改抓 bytes 后按 GBK 解码，
    并用不含中文的 /FO CSV 兜底匹配 exe 名。
    """
    r = subprocess.run(["tasklist", "/FO", "CSV", "/NH"],
                       capture_output=True)
    out = (r.stdout or b"").decode("gbk", errors="replace")
    return name in out or name.encode("utf-8") in (r.stdout or b"")


def _tasklist_any(name_bytes: bytes) -> bool:
    r = subprocess.run(["tasklist", "/FO", "CSV", "/NH"], capture_output=True)
    return name_bytes in (r.stdout or b"")


def _tasklist_any(name_bytes: bytes) -> bool:
    r = subprocess.run(["tasklist", "/FO", "CSV", "/NH"], capture_output=True)
    return name_bytes in (r.stdout or b"")


def _close_app_if_running() -> None:
    """目标 exe 正在运行 → 先自动关闭再构建（2026-11-12 用户要求）。

    装配阶段会整目录删除旧产物；exe 锁着 runtime 日志时删一半才失败，
    产物残缺。所以开跑前先 taskkill，等进程真正退出再动手。
    """
    if not _tasklist_has("千里单骑助手.exe"):
        return
    print("检测到「千里单骑助手.exe」正在运行，自动关闭后继续构建…")
    subprocess.run(["taskkill", "/F", "/IM", "千里单骑助手.exe"],
                   capture_output=True)
    for _ in range(20):                       # 最多等 10 秒进程退出
        time.sleep(0.5)
        if not _tasklist_has("千里单骑助手.exe"):
            # 进程没了 ≠ 句柄已释放：立即删目录会撞 WinError 5（实测 ffi.dll）
            time.sleep(2.0)
            print("程序已关闭（句柄释放等待 2s），继续构建。")
            return
    print("✗ 程序未能关闭（可能有残留子进程），为避免产物残缺，终止构建。")
    raise SystemExit(1)


def _close_adb_server() -> None:
    """adb 服务进程锁着 bin/adb.exe → PyInstaller 清产物必撞 WinError 5。

    2026-11-13 事故（同日第二次产物残缺）。构建不需要 adb；杀掉服务后
    运行时 ensure_connected 会自动重启重连，模拟器本体不受影响。
    """
    if not _tasklist_any(b"adb.exe"):
        return
    print("检测到 adb 服务进程（锁 bin/adb.exe），关闭后继续构建…")
    subprocess.run(["taskkill", "/F", "/IM", "adb.exe"], capture_output=True)
    time.sleep(2)
    print("adb 服务已关闭，继续构建。")


def _close_adb_server() -> None:
    """adb 服务进程锁着 bin/adb.exe → PyInstaller 清产物必撞 WinError 5。

    2026-11-13 事故（同日第二次产物残缺）。构建不需要 adb；杀掉服务后
    运行时 ensure_connected 会自动重启重连，模拟器本体不受影响。
    """
    if not _tasklist_any(b"adb.exe"):
        return
    print("检测到 adb 服务进程（锁 bin/adb.exe），关闭后继续构建…")
    subprocess.run(["taskkill", "/F", "/IM", "adb.exe"], capture_output=True)
    time.sleep(2)
    print("adb 服务已关闭，继续构建。")
DIST = ROOT / "未加密版"
APP = DIST / "千里单骑助手"
WORK = ROOT / "build_work_plain"

# ⓪ 程序在跑就先自动关闭（2026-11-12：锁文件会让 ①删一半 ②PyInstaller
#    rmtree 双双失败，产物残缺。本脚本是模块级流程，守卫必须在此显式调用）
_close_app_if_running()
_close_adb_server()

# ① 旧产物腾位
if (APP).exists():
    shutil.rmtree(APP, ignore_errors=True)

# ② PyInstaller（明文分析，mjs_gui.py 直入）
r = subprocess.run(
    [sys.executable, "-m", "PyInstaller", "--noconfirm", "--onedir",
     "--windowed", "--name", "千里单骑助手", "--distpath", str(DIST),
     "--workpath", str(WORK), "--collect-all", "rapidocr_onnxruntime",
     "mjs_gui.py"],
    capture_output=True, text=True, encoding="utf-8", errors="replace")
out = (r.stdout or "") + (r.stderr or "")
assert "Build complete" in out, out[-1200:]
print("① Build complete ✓")

# ③ 装配（未加密版：模板明文直拷）
shutil.rmtree(APP / "assets", ignore_errors=True)
(APP / "assets").mkdir(parents=True, exist_ok=True)
shutil.copytree(ROOT / "assets/templates", APP / "assets/templates")
# 锚点表数据（2026-11-11）：分类数据也在 assets 下，漏拷会静默退化为 OCR
shutil.copytree(ROOT / "assets/screen_info", APP / "assets/screen_info")
shutil.rmtree(APP / "config", ignore_errors=True)
shutil.copytree(ROOT / "config", APP / "config")
bin_dir = APP / "bin"
bin_dir.mkdir(exist_ok=True)
# 模拟器自带 adb 目录由环境变量 LDPLAYER_ADB 指定（不写死本机路径）
_ld = os.environ.get("LDPLAYER_ADB", "").strip()
ld = Path(_ld) if _ld else None
if ld is not None and ld.is_file():
    shutil.copy2(ld, bin_dir / "adb.exe")
    for dll in ("AdbWinApi.dll", "AdbWinUsbApi.dll"):
        sd = ld.parent / dll
        if sd.exists():
            shutil.copy2(sd, bin_dir / dll)
    sf = APP / "config/settings.yaml"
    s = sf.read_text(encoding="utf-8").replace(
        'adb_path: "adb"', 'adb_path: "bin/adb.exe"')
    sf.write_text(s, encoding="utf-8")
shutil.copy2(ROOT / "tools/vendor/ADBKeyboard.apk", bin_dir / "ADBKeyboard.apk")
shutil.copy2(ROOT / "使用说明.txt", APP / "使用说明.txt")
(APP / "runtime/logs").mkdir(parents=True, exist_ok=True)
(APP / "runtime/shots").mkdir(parents=True, exist_ok=True)
print("② 装配完成")

# 产物完整性校验（2026-11-11 锚点表漏拷事故）：必需资产缺失直接构建失败
_required = [
    "assets/screen_info/anchors.yml",
    "assets/templates/anchors",
    "assets/templates/run_map", "assets/templates/settle",
    "assets/templates/task", "assets/templates/popup",
    "assets/templates/invite",
    "config/settings.yaml",
]
if (bin_dir / "adb.exe").exists():
    _required.append("bin/adb.exe")
_missing = [r_ for r_ in _required if not (APP / r_).exists()]
assert not _missing, f"产物缺失必需资产: {_missing}"
print("②-校验 必需资产齐全 ✓")

# ④ 冒烟
os.chdir(APP)
p = subprocess.Popen([os.path.abspath("千里单骑助手.exe"), "--smoke"])
ok = False
for _ in range(60):
    time.sleep(1)
    if Path("runtime/smoke_ok.txt").exists():
        ok = True
        break
if p.poll() is None:
    p.terminate()
time.sleep(1)
try:
    os.remove("runtime/smoke_ok.txt")
except OSError:
    pass
os.chdir(ROOT)
print("③ SMOKE:", "通过 ✅" if ok else "失败 ❌")
assert ok, "冒烟失败"
print("④ 未加密版重建完成:", APP)
