"""路径解析与配置加载。

所有相对路径均以项目根目录（本文件所在目录的上一级）为基准解析，
因此无论从哪个工作目录启动脚本，行为都一致。
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

# --------------------------------------------------------------------------
# 目录常量
# --------------------------------------------------------------------------
# 冻结版（PyInstaller exe）：ROOT=exe 所在目录（config/assets 与 exe 同级）；
# 源码运行：ROOT=项目根目录
ROOT: Path = (
    Path(sys.executable).resolve().parent if getattr(sys, "frozen", False)
    else Path(__file__).resolve().parent.parent
)
CONFIG_DIR: Path = ROOT / "config"
ASSETS_DIR: Path = ROOT / "assets"
TEMPLATES_DIR: Path = ASSETS_DIR / "templates"
SCREENSHOTS_DIR: Path = ASSETS_DIR / "screenshots"
DOCS_DIR: Path = ROOT / "docs"
TOOLS_DIR: Path = ROOT / "tools"


def _read_yaml(path: Path) -> Dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"配置文件不存在: {path}")
    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data or {}


def _resolve(p: Optional[str]) -> Optional[Path]:
    """把配置里的相对路径解析为绝对路径。"""
    if not p:
        return None
    path = Path(p)
    return path if path.is_absolute() else (ROOT / path)


class Config:
    """全局配置容器。

    Examples
    --------
    >>> cfg = Config.load()
    >>> cfg.tap(960, 540)          # 占位示例
    """

    def __init__(self, settings: Dict[str, Any], coords: Dict[str, Any],
                 ocr_rules: Dict[str, Any]) -> None:
        self.settings = settings
        self.coords = coords
        self.ocr = ocr_rules

    # ---------------------------------------------------------------- 加载
    @classmethod
    def load(cls,
             settings_file: str = "settings.yaml",
             coords_file: str = "coords.yaml",
             ocr_file: str = "ocr_rules.yaml") -> "Config":
        return cls(
            _read_yaml(CONFIG_DIR / settings_file),
            _read_yaml(CONFIG_DIR / coords_file),
            _read_yaml(CONFIG_DIR / ocr_file),
        )

    def save_coords(self) -> None:
        """把（可能被程序更新过的）坐标表写回磁盘。"""
        path = CONFIG_DIR / "coords.yaml"
        with path.open("w", encoding="utf-8") as f:
            yaml.safe_dump(self.coords, f, allow_unicode=True,
                           sort_keys=False, default_flow_style=False)

    # ------------------------------------------------------------ 便捷取值
    def get(self, path: str, default: Any = None) -> Any:
        """按 "a.b.c" 路径取值。"""
        node: Any = self.settings
        for key in path.split("."):
            if not isinstance(node, dict) or key not in node:
                return default
            node = node[key]
        return node

    @property
    def adb_path(self) -> str:
        return self.get("device.adb_path", "adb")

    @property
    def serial(self) -> str:
        return self.get("device.serial", "") or ""

    @property
    def base_size(self) -> Tuple[int, int]:
        return (int(self.get("screen.base_width", 1920)),
                int(self.get("screen.base_height", 1080)))

    @property
    def log_dir(self) -> Path:
        return _resolve(self.get("runtime.log_dir", "runtime/logs"))  # type: ignore[return-value]

    @property
    def shot_dir(self) -> Path:
        return _resolve(self.get("runtime.shot_dir", "runtime/shots"))  # type: ignore[return-value]

    @property
    def decision_dir(self) -> Path:
        return _resolve(self.get("runtime.decision_dir", "runtime/decisions"))  # type: ignore[return-value]

    @property
    def templates_dir(self) -> Path:
        return _resolve(self.get("vision.template_dir", "assets/templates"))  # type: ignore[return-value]

    # --------------------------------------------------------------- 坐标表
    def screen(self, screen_name: str) -> Dict[str, Any]:
        return (self.coords.get("screens") or {}).get(screen_name, {}) or {}

    def element(self, screen_name: str, element: str) -> Optional[Dict[str, Any]]:
        return self.screen(screen_name).get(element)

    def point(self, screen_name: str, element: str) -> Optional[List[int]]:
        """取某元素的重心/单点坐标（基准分辨率）。"""
        el = self.element(screen_name, element)
        if not el:
            return None
        if "xy" in el:
            return list(el["xy"])
        if "center" in el:
            return list(el["center"])
        if "box" in el:
            x1, y1, x2, y2 = el["box"]
            return [int((x1 + x2) / 2), int((y1 + y2) / 2)]
        return None

    def box(self, screen_name: str, element: str) -> Optional[List[int]]:
        el = self.element(screen_name, element)
        if el and "box" in el:
            return list(el["box"])
        return None
