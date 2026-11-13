"""可视化标注：把识别结果画回截图，便于人工核对与标定。

标定界面坐标时最常用： ``draw_grid`` 叠加 100px 网格，肉眼读坐标。
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional, Sequence, Tuple

import cv2
import numpy as np

_COLORS = {
    "hit": (0, 200, 0),       # BGR 绿
    "miss": (0, 0, 255),
    "info": (0, 200, 255),
    "grid": (255, 120, 0),
    "text": (60, 60, 60),
}


def read_image(path: Path | str) -> Optional[np.ndarray]:
    """读取图片，**兼容中文/非 ASCII 路径**。

    为什么不用 ``cv2.imread``：它在 Windows 上走 ANSI 编码，遇到中文路径
    （例如 ``runtime/decisions/xxx_导航失败.png``）会直接返回 None，
    表现为"文件明明存在却读不出来"。这里改用 ``np.fromfile + imdecode``
    绕过该限制，与 :func:`save` 的中文安全写法配套。
    """
    path = Path(path)
    if not path.exists():
        return None
    try:
        buf = np.fromfile(str(path), dtype=np.uint8)
    except OSError:
        return None
    if buf.size == 0:
        return None
    return cv2.imdecode(buf, cv2.IMREAD_COLOR)


def draw_grid(image: np.ndarray, step: int = 100,
              color: Tuple[int, int, int] = _COLORS["grid"],
              alpha: float = 0.45) -> np.ndarray:
    """叠加坐标网格（每 step 像素一条线，并标注坐标值）。"""
    out = image.copy()
    h, w = out.shape[:2]
    overlay = out.copy()
    for x in range(0, w, step):
        cv2.line(overlay, (x, 0), (x, h), color, 1)
        cv2.putText(overlay, str(x), (x + 3, 16),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.42, color, 1, cv2.LINE_AA)
    for y in range(0, h, step):
        cv2.line(overlay, (0, y), (w, y), color, 1)
        cv2.putText(overlay, str(y), (3, y + 16),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.42, color, 1, cv2.LINE_AA)
    cv2.addWeighted(overlay, alpha, out, 1 - alpha, 0, out)
    return out


def draw_matches(image: np.ndarray, matches: Sequence[object]) -> np.ndarray:
    """画出匹配框与分数。matches 需含 .box/.score/.name。"""
    out = image.copy()
    for m in matches:
        x1, y1, x2, y2 = m.box           # type: ignore[attr-defined]
        cv2.rectangle(out, (x1, y1), (x2, y2), _COLORS["hit"], 2)
        label = f"{m.name} {m.score:.2f}"  # type: ignore[attr-defined]
        cv2.putText(out, label, (x1, max(0, y1 - 6)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, _COLORS["hit"], 1, cv2.LINE_AA)
    return out


def draw_ocr(image: np.ndarray, items: Sequence[object]) -> np.ndarray:
    """画出 OCR 文本框与文字。"""
    out = image.copy()
    for it in items:
        box = it.box                       # type: ignore[attr-defined]
        pts = np.array([[int(p[0]), int(p[1])] for p in box], dtype=np.int32)
        cv2.polylines(out, [pts], True, _COLORS["info"], 2)
        x, y = int(box[0][0]), int(box[0][1])
        cv2.putText(out, f"{it.text}({it.score:.2f})", (x, max(0, y - 5)),  # type: ignore[attr-defined]
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, _COLORS["info"], 1, cv2.LINE_AA)
    return out


def draw_points(image: np.ndarray,
                points: Sequence[Tuple[Sequence[float], str]]) -> np.ndarray:
    """标记一组 (坐标, 标签)。"""
    out = image.copy()
    for pt, label in points:
        x, y = int(pt[0]), int(pt[1])
        cv2.drawMarker(out, (x, y), _COLORS["miss"], cv2.MARKER_CROSS, 22, 2)
        cv2.putText(out, f"{label}({x},{y})", (x + 8, y - 8),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, _COLORS["miss"], 1, cv2.LINE_AA)
    return out


def draw_region(image: np.ndarray, box: Sequence[int],
                label: str = "region") -> np.ndarray:
    out = image.copy()
    x1, y1, x2, y2 = [int(v) for v in box]
    cv2.rectangle(out, (x1, y1), (x2, y2), _COLORS["info"], 2)
    cv2.putText(out, label, (x1, max(0, y1 - 6)),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, _COLORS["info"], 1, cv2.LINE_AA)
    return out


def save(image: np.ndarray, path: Path | str) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # 中文路径安全写法
    ext = path.suffix or ".png"
    ok, buf = cv2.imencode(ext, image)
    if not ok:
        raise RuntimeError(f"图像编码失败: {path}")
    buf.tofile(str(path))
    return path
