"""绿色版 GUI 启动入口（PyInstaller 打包用）。

双击 exe → 冻结感知：工作目录切到 exe 所在目录（config/assets/runtime
与其同级），然后打开控制台 GUI。

``--smoke``：构建 GUI 1.5 秒后自毁，写 runtime/smoke_ok.txt——打包后
自动验证用，不打开真实界面。
"""
import os
import sys

if getattr(sys, "frozen", False):
    os.chdir(os.path.dirname(os.path.abspath(sys.executable)))


def main() -> int:
    os.makedirs("runtime", exist_ok=True)
    if "--smoke" in sys.argv:
        import tkinter as tk

        from src.gui.app import ControlApp
        root = tk.Tk()
        root.withdraw()
        ControlApp(root)
        root.after(1500, root.destroy)
        root.mainloop()
        # 顺带验证 OCR 引擎能起来（2026-11-12）：GPU 版需要把 DirectML.dll
        # 一起打进包，缺 DLL 时这里会回落 CPU —— 把实际设备写进结果文件，
        # 打包后一眼能看出 GPU 是否可用。
        device = "n/a"
        try:
            from src.vision.ocr import OCREngine
            eng = OCREngine(device="auto")
            if eng.available:
                device = eng.device
        except Exception:  # noqa: BLE001 — 冒烟只做尽力而为的探测
            device = "error"
        with open(os.path.join("runtime", "smoke_ok.txt"), "w",
                  encoding="utf-8") as f:
            f.write("ok ocr_device=%s" % device)
        return 0
    from src.gui.app import main as gui_main
    return gui_main()


if __name__ == "__main__":
    raise SystemExit(main())
