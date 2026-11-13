# -*- coding: utf-8 -*-
"""脱敏扫描器测试（锁定 tools/scan_sensitive.py 的拦截能力）。"""
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCAN = ROOT / "tools" / "scan_sensitive.py"


def run_scan(*paths: Path):
    p = subprocess.run(
        [sys.executable, str(SCAN), "--path", *[str(x) for x in paths]],
        capture_output=True, cwd=str(ROOT))
    text = p.stdout.decode("utf-8", "replace") + p.stderr.decode("utf-8", "replace")
    return p.returncode, text


class TestPrivacyScan(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _write(self, name: str, content: str) -> Path:
        p = self.tmp / name
        p.write_text(content, encoding="utf-8")
        return p

    def test_clean_file_passes(self):
        p = self._write("clean.py", "def add(a, b):\n    return a + b\n")
        code, out = run_scan(p)
        self.assertEqual(code, 0, out)

    def test_aws_key_detected(self):
        token = "AKIA" + "ABCDEFGHIJKLMNOP"
        p = self._write("conf.py", f"AWS_KEY = '{token}'\n")
        code, out = run_scan(p)
        self.assertEqual(code, 1, out)
        self.assertIn("AWS_AKID", out)

    def test_windows_user_path_detected(self):
        path = "C:" + "/Users/alice/project/tool.exe"
        p = self._write("note.md", f"本地路径：{path}\n")
        code, out = run_scan(p)
        self.assertEqual(code, 1, out)
        self.assertIn("LOCAL_PATH", out)

    def test_unix_home_detected(self):
        p = self._write("note.md", "配置在 " + "/home/alice/.config\n")
        code, out = run_scan(p)
        self.assertEqual(code, 1, out)
        self.assertIn("LOCAL_PATH", out)

    def test_credential_assignment_detected(self):
        p = self._write("conf.ini", "api_key = 1234567890abcdef\n")
        code, out = run_scan(p)
        self.assertEqual(code, 1, out)
        self.assertIn("CRED_ASSIGN", out)

    def test_forbidden_binary_ext_detected(self):
        p = self.tmp / "tool.exe"
        p.write_bytes(b"MZ\x00\x00binary")
        code, out = run_scan(p)
        self.assertEqual(code, 1, out)
        self.assertIn("FORBIDDEN_EXT", out)

    def test_oversize_file_detected(self):
        p = self.tmp / "big.txt"
        p.write_bytes(b"a" * (51 * 1024 * 1024))
        code, out = run_scan(p)
        self.assertEqual(code, 1, out)
        self.assertIn("FILE_TOO_LARGE", out)

    def test_multiple_files_reports_all(self):
        a = self._write("a.py", "password = 'hunter2hunter2'\n")
        b = self._write("b.py", "token = 'x'\n")
        code, out = run_scan(a, b)
        self.assertEqual(code, 1, out)
        self.assertIn("a.py", out)


if __name__ == "__main__":
    unittest.main()
