#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""推送前脱敏扫描（2026-11-13 约束，见 AGENTS.md 第八节）。

扫描 git 跟踪的文件（或指定路径），命中以下任一类别即报错并返回退出码 1：
  1. 凭据类：私钥 / 云 AK / GitHub、Slack、OpenAI token / URL 内嵌账号密码 / 高熵串
  2. 本机路径：C 盘用户目录、/home 或 /Users 用户名、模拟器安装目录
  3. 个人信息关键词：tools/privacy_rules.yml + 本机 tools/privacy_rules.local.yml
  4. 禁止入库的目录 / 二进制类型 / 超过体积上限的文件

用法：
  .venv/Scripts/python.exe tools/scan_sensitive.py              # 扫描 tracked 文件
  .venv/Scripts/python.exe tools/scan_sensitive.py --path a.py  # 只扫指定文件
  .venv/Scripts/python.exe tools/scan_sensitive.py --history    # 扫描全部历史（发布前）

退出码：0=干净，1=有命中，2=环境/配置错误。
"""
from __future__ import annotations

import argparse
import fnmatch
import math
import os
import re
import subprocess
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

BINARY_EXTS = {
    ".png", ".jpg", ".jpeg", ".gif", ".ico", ".bmp", ".webp", ".onnx",
    ".so", ".dll", ".exe", ".apk", ".ttf", ".otf", ".woff", ".woff2",
    ".pyc", ".db", ".sqlite", ".zip", ".jar", ".p12", ".pfx", ".jks",
}

# 扫描器自身与规则/测试文件：里面必然含有"像密钥/像本机路径"的示例文本
SELF_SKIP = {
    "tools/scan_sensitive.py",
    "tools/privacy_rules.yml",
    "tools/privacy_rules.local.yml",
    "tools/privacy_allowlist.txt",
    "tests/test_privacy_scan.py",
}

SECRET_PATTERNS = [
    ("PRIVATE_KEY", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("AWS_AKID", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("GITHUB_TOKEN", re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}")),
    ("OPENAI_SK", re.compile(r"\bsk-[A-Za-z0-9]{20,}")),
    ("SLACK", re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}")),
    ("GOOGLE_API", re.compile(r"AIza[0-9A-Za-z_\-]{30,}")),
    ("JWT", re.compile(r"eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}")),
    ("URL_CREDS", re.compile(r"[a-zA-Z][a-zA-Z0-9+.\-]*://[^/\s:@]+:[^/\s:@]+@")),
    ("CRED_ASSIGN", re.compile(
        r"(?i)(password|passwd|pwd|secret|api[_-]?key|apikey|access[_-]?key|"
        r"access[_-]?token|auth[_-]?token|private[_-]?token|client[_-]?secret|"
        r"app[_-]?secret)\s*[:=]\s*[\"']?[^\s\"',;}]{6,}")),
    ("BEARER", re.compile(r"(?i)authorization\s*[:=]\s*bearer\s+\S{10,}")),
]

LOCAL_PATH_PATTERNS = [
    ("LOCAL_PATH", re.compile(r"[A-Za-z]:[\\/]+Users[\\/]+[^\\/\s\"']+")),
    ("LOCAL_PATH", re.compile(r"(?<![A-Za-z:])/(?:home|Users)/[A-Za-z0-9_.\-]{2,}")),
    ("LOCAL_PATH", re.compile(r"(?i)[A-Za-z]:[\\/]+(?:leidian|LDPlayer)[\\/]")),
]

DEFAULT_RULES = {
    "forbidden_paths": [],
    "forbidden_exts": [],
    "personal_keywords": [],
    "max_file_mb": 50,
}


@dataclass
class Finding:
    kind: str
    path: str
    line: int
    match: str


def out(msg: str = "") -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass
    print(msg)


def load_rules() -> dict:
    rules = dict(DEFAULT_RULES)
    rules["personal_keywords"] = []
    for name in ("privacy_rules.yml", "privacy_rules.local.yml"):
        p = ROOT / "tools" / name
        if not p.is_file():
            continue
        try:
            import yaml  # 项目依赖里有 PyYAML
            data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        except Exception as exc:  # noqa: BLE001
            raise SystemExit(f"[scan] 读取 {name} 失败: {exc}")
        for k in ("forbidden_paths", "forbidden_exts", "personal_keywords"):
            vals = data.get(k) or []
            if k == "personal_keywords":
                rules[k].extend(str(v) for v in vals)
            else:
                rules[k].extend(str(v) for v in vals)
        if "max_file_mb" in data and data["max_file_mb"]:
            rules["max_file_mb"] = float(data["max_file_mb"])
    return rules


def load_allowlist() -> list:
    """返回 [(detector, path_glob, contains_or_None)]。"""
    p = ROOT / "tools" / "privacy_allowlist.txt"
    out_list = []
    if not p.is_file():
        return out_list
    for raw in p.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = [x.strip() for x in line.split("|")]
        if len(parts) < 2:
            continue
        detector, glob = parts[0], parts[1]
        contains = parts[2] if len(parts) > 2 and parts[2] else None
        out_list.append((detector, glob, contains))
    return out_list


def is_allowed(f: Finding, allow: list) -> bool:
    norm = f.path.replace("\\", "/")
    for detector, glob, contains in allow:
        if detector not in ("*", f.kind):
            continue
        if not fnmatch.fnmatch(norm, glob) and not fnmatch.fnmatch(os.path.basename(norm), glob):
            continue
        if contains is None or contains in f.match:
            return True
    return False


def git_ls_files() -> list:
    p = subprocess.run(["git", "-C", str(ROOT), "ls-files", "-z"],
                       capture_output=True)
    if p.returncode != 0:
        raise SystemExit("[scan] 不是 git 仓库或多文件读取失败")
    return [x for x in p.stdout.decode("utf-8", "replace").split("\0") if x]


def decode(data: bytes) -> str:
    for enc in ("utf-8", "gbk", "latin-1"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1", "replace")


def entropy(s: str) -> float:
    if not s:
        return 0.0
    c = Counter(s)
    n = len(s)
    return -sum((v / n) * math.log2(v / n) for v in c.values())


def secretish(tok: str) -> bool:
    if len(tok) < 24:
        return False
    if not re.search(r"[A-Za-z]", tok) or not re.search(r"\d", tok):
        return False
    return entropy(tok) > 4.5 and re.fullmatch(r"[A-Za-z0-9+/=_\-]+", tok) is not None


def check_path_rules(rel: str, rules: dict, findings: list) -> None:
    norm = rel.replace("\\", "/")
    for d in rules["forbidden_paths"]:
        d = d.replace("\\", "/").rstrip("/")
        if norm == d or norm.startswith(d + "/"):
            findings.append(Finding("FORBIDDEN_PATH", norm, 0, norm))
    ext = os.path.splitext(norm)[1].lower()
    if ext in {e.lower() for e in rules["forbidden_exts"]}:
        findings.append(Finding("FORBIDDEN_EXT", norm, 0, ext))


def scan_text(rel: str, text: str, rules: dict, findings: list) -> None:
    keywords = [k for k in rules["personal_keywords"] if k]
    for ln, line in enumerate(text.splitlines(), 1):
        if len(line) > 4000:
            line = line[:4000]
        for kind, rx in SECRET_PATTERNS + LOCAL_PATH_PATTERNS:
            m = rx.search(line)
            if m:
                findings.append(Finding(kind, rel, ln, m.group(0)[:160]))
        for kw in keywords:
            if kw in line:
                findings.append(Finding("PERSONAL_KEYWORD", rel, ln, kw))
        for tok in re.findall(r"[A-Za-z0-9+/=_\-]{24,}", line):
            if secretish(tok):
                findings.append(Finding("HIGH_ENTROPY", rel, ln, tok[:80]))


def scan_files(paths: list, rules: dict) -> list:
    findings: list = []
    max_mb = float(rules.get("max_file_mb") or 50)
    for rel in paths:
        if rel.replace("\\", "/") in SELF_SKIP:
            continue
        p = Path(rel)
        if not p.is_absolute():
            p = ROOT / rel
        if not p.is_file():
            continue
        rel_display = rel if not Path(rel).is_absolute() else str(p)
        check_path_rules(rel_display, rules, findings)

        size_mb = p.stat().st_size / 1048576
        if size_mb > max_mb:
            findings.append(Finding("FILE_TOO_LARGE", rel_display, 0,
                                    f"{size_mb:.1f} MB > {max_mb:g} MB"))
            continue
        if p.suffix.lower() in BINARY_EXTS:
            continue
        try:
            text = decode(p.read_bytes())
        except OSError as exc:
            findings.append(Finding("READ_ERROR", rel_display, 0, str(exc)))
            continue
        scan_text(rel_display, text, rules, findings)
    return findings


def scan_history(rules: dict) -> list:
    """扫描全部 commit 可达的历史 blob（发布前用）。"""
    findings: list = []
    p = subprocess.run(["git", "-C", str(ROOT), "rev-list", "--objects", "--all"],
                       capture_output=True, text=True)
    paths_by_blob: dict = {}
    for line in p.stdout.splitlines():
        parts = line.split(" ", 1)
        if len(parts) == 2:
            paths_by_blob.setdefault(parts[0], []).append(parts[1])
    if not paths_by_blob:
        return findings
    shas = list(paths_by_blob)
    meta = subprocess.run(["git", "-C", str(ROOT), "cat-file", "--batch-check"],
                          input=("\n".join(shas)).encode(), capture_output=True)
    sizes = {}
    for sha, row in zip(shas, meta.stdout.decode().splitlines()):
        f = row.split()
        if len(f) >= 3 and f[1] == "blob":
            try:
                sizes[sha] = int(f[2])
            except ValueError:
                pass
    for sha, paths in paths_by_blob.items():
        if sha not in sizes:
            continue
        rel = paths[0]
        if rel.replace("\\", "/") in SELF_SKIP:
            continue
        if sizes[sha] > 3 * 1024 * 1024:
            continue
        if os.path.splitext(rel)[1].lower() in BINARY_EXTS:
            continue
        data = subprocess.run(["git", "-C", str(ROOT), "cat-file", "blob", sha],
                              capture_output=True).stdout
        if not data:
            continue
        scan_text("history:" + rel, decode(data), rules, findings)
    return findings


def main() -> int:
    ap = argparse.ArgumentParser(description="推送前脱敏扫描")
    ap.add_argument("--path", nargs="*", default=None,
                    help="只扫描指定文件/目录（默认扫描 git tracked 文件）")
    ap.add_argument("--history", action="store_true", help="同时扫描全部历史 blob")
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    args = ap.parse_args()

    rules = load_rules()
    allow = load_allowlist()

    if args.path:
        targets = []
        for item in args.path:
            q = Path(item)
            if not q.is_absolute():
                q = ROOT / item
            if q.is_dir():
                for base, dirs, files in os.walk(q):
                    dirs[:] = [d for d in dirs if d not in (".git", ".venv", "__pycache__")]
                    targets.extend(str(Path(base) / f) for f in files)
            elif q.is_file():
                targets.append(str(q))
    else:
        targets = git_ls_files()

    findings = scan_files(targets, rules)
    if args.history:
        findings.extend(scan_history(rules))

    findings = [f for f in findings if not is_allowed(f, allow)]

    if args.json:
        import json
        out(json.dumps([f.__dict__ for f in findings], ensure_ascii=False, indent=1))

    if findings:
        out(f"[scan] 发现 {len(findings)} 处疑似敏感信息：")
        seen = set()
        for f in findings:
            key = (f.kind, f.path, f.line, f.match)
            if key in seen:
                continue
            seen.add(key)
            loc = f"{f.path}:{f.line}" if f.line else f.path
            out(f"  [{f.kind}] {loc}  {f.match}")
        out("")
        out("[scan] 处理方式：未提交→删除/打码/加 .gitignore；已提交未推→修好后 amend；"
            "已推送→改写历史后强推。确认属于误报可在 tools/privacy_allowlist.txt 加例外。")
        return 1

    out(f"[scan] 干净：扫描 {len(targets)} 个文件，未发现敏感信息。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
