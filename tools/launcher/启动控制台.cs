// 启动器（2026-11-13）：双击启动 GUI，不显示命令行窗口。
//
// 它**不是**把程序打包成 exe：程序本身仍是源码运行（.venv + run.py）。
// 本启动器只做一件事——用 pythonw.exe（无控制台解释器）启动 `run.py gui`，
// 全程不弹黑窗口；若后台启动失败，自动改用带控制台的 python 重跑一次，
// 把真实报错显示给用户，避免"双击没反应"。
//
// 编译（无需 VS，Windows 自带 .NET Framework 即可）：
//   tools\build_launcher.bat
using System;
using System.Diagnostics;
using System.IO;
using System.Windows.Forms;

internal static class Launcher
{
    [STAThread]
    private static int Main()
    {
        string baseDir = AppDomain.CurrentDomain.BaseDirectory;
        string pythonw = Path.Combine(baseDir, @".venv\Scripts\pythonw.exe");
        string python = Path.Combine(baseDir, @".venv\Scripts\python.exe");

        if (!File.Exists(pythonw))
        {
            MessageBox.Show(
                "没有找到虚拟环境：" + Environment.NewLine + pythonw +
                Environment.NewLine + Environment.NewLine +
                "请先按《部署文档.md》创建 .venv 并安装依赖，再双击本程序。",
                "启动失败", MessageBoxButtons.OK, MessageBoxIcon.Error);
            return 1;
        }

        try
        {
            var psi = new ProcessStartInfo(pythonw, "run.py gui")
            {
                WorkingDirectory = baseDir,
                UseShellExecute = false,
                CreateNoWindow = true,
            };
            using (Process p = Process.Start(psi))
            {
                if (p == null) return Fallback(baseDir, python);
                p.WaitForExit();
                if (p.ExitCode != 0) return Fallback(baseDir, python);
                return 0;
            }
        }
        catch (Exception ex)
        {
            MessageBox.Show(
                "启动失败：" + ex.Message,
                "启动失败", MessageBoxButtons.OK, MessageBoxIcon.Error);
            return Fallback(baseDir, python);
        }
    }

    // 后台启动失败 → 用带控制台的 python 重跑，让用户看到真实报错
    private static int Fallback(string baseDir, string python)
    {
        try
        {
            if (!File.Exists(python)) return 1;
            Process.Start(new ProcessStartInfo(python, "run.py gui")
            {
                WorkingDirectory = baseDir,
                UseShellExecute = true,
            });
        }
        catch (Exception)
        {
            // 连兜底都失败时，前面的 MessageBox 已经给过提示
        }
        return 1;
    }
}
