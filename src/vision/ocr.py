"""中文 OCR 封装（RapidOCR / onnxruntime）。

选型理由
--------
* 离线可用、纯 pip 安装，不需要额外装 tesseract 二进制
* 自带中英文识别模型，对中文美术字体比 tesseract 明显更好
* 依赖 onnxruntime，CPU 推理，单帧整屏约 100~300ms（可裁剪区域提速）

用途
----
读取「模板匹配读不到」的动态文本/数值：里程数、关卡进度、增益文本、
结算文案、按钮上的可变文字等。
"""
from __future__ import annotations

import logging
import os
import re
import unicodedata
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence

import numpy as np


@dataclass
class OCRItem:
    """一段被识别出的文本。"""
    text: str
    score: float
    box: Sequence[Sequence[float]]      # 四点坐标

    @property
    def center(self):
        xs = [p[0] for p in self.box]
        ys = [p[1] for p in self.box]
        return int(sum(xs) / len(xs)), int(sum(ys) / len(ys))

    @property
    def rect(self):
        xs = [p[0] for p in self.box]
        ys = [p[1] for p in self.box]
        return int(min(xs)), int(min(ys)), int(max(xs)), int(max(ys))


def normalize_text(text: str) -> str:
    """归一化：全角转半角、去除空白、统一大小写无关比对基准。"""
    if not text:
        return ""
    text = unicodedata.normalize("NFKC", text)
    return re.sub(r"\s+", "", text)


#: 推理设备：auto=有 DirectML 就用 GPU / cpu / dml（强制，失败回落 cpu）
DEVICE_CHOICES = ("auto", "cpu", "dml")


def resolve_device(requested: str = "auto", providers=None,
                   system: Optional[str] = None) -> str:
    """决定实际推理设备，返回 ``"dml"`` 或 ``"cpu"``。

    纯函数（可传入 providers/system 便于离线测试）：
    * ``cpu`` → 永远 CPU
    * ``auto`` / ``dml`` → Windows 且有 DmlExecutionProvider 才用 GPU，
      否则回落 CPU（DirectML 只支持 Windows 10+；没装 DML 版 onnxruntime
      或显卡不支持 DX12 时都必须能安全降级）
    """
    import platform

    req = (requested or "auto").strip().lower()
    if req == "cpu":
        return "cpu"
    if system is None:
        system = platform.system()
    if system != "Windows":
        return "cpu"
    try:
        if providers is None:
            import onnxruntime as ort
            providers = ort.get_available_providers()
        if "DmlExecutionProvider" in list(providers):
            return "dml"
    except Exception:  # noqa: BLE001 — 没有 onnxruntime 就按 CPU 处理
        pass
    return "cpu"


class OCREngine:
    """OCR 引擎包装：惰性加载，加载失败自动降级为空实现。

    ``intra_threads``：onnxruntime 会话线程数（2026-09-25 加，默认 2）。
    旧默认 -1 = 占满全部 CPU 核，整屏 OCR 时会把模拟器/系统饿死
    （实测挂机时整屏 OCR 从 ~2s 涨到 4–6s）。限到 2 核后单次略慢
    但整机流畅、总吞吐反而更高。
    """

    def __init__(self,
                 engine: str = "rapidocr",
                 min_score: float = 0.5,
                 normalize: bool = True,
                 logger: Optional[logging.Logger] = None,
                 intra_threads: int = 2,
                 cache_frames: bool = True,
                 device: str = "auto") -> None:
        self.engine_name = engine
        self.min_score = min_score
        self.normalize = normalize
        self.log = logger or logging.getLogger("mjs.ocr")
        self.intra_threads = max(1, int(intra_threads))
        self.cache_frames = cache_frames
        #: 期望设备（auto/cpu/dml）；实际设备见 self.device
        self.requested_device = (device or "auto").strip().lower()
        self.device = "cpu"
        self._engine: Any = None
        self._failed = False
        self._cache: Dict[Any, List[OCRItem]] = {}
        #: 同一帧 + 同一区域的识别结果缓存（2026-11-12，CPU 优化）
        #: 用「对象身份」而不是 id()：帧对象在调用方存活期间不会被复用，
        #: 且只保留最近一帧，内存开销可忽略。
        self._last_img: Optional[np.ndarray] = None
        self._last_region: Optional[tuple] = None
        self._last_items: List[OCRItem] = []
        self._hits = 0
        self._runs = 0

    # ----------------------------------------------------------------- 加载
    def _ensure(self) -> bool:
        if self._engine is not None:
            return True
        if self._failed:
            return False
        # onnxruntime / OpenMP 默认让线程**自旋等待**（空闲也吃满 CPU 核），
        # 挂机时整机发热、还会和模拟器抢核。PASSIVE 让等待线程休眠，
        # 单次推理慢几个毫秒，但空闲 CPU 掉到接近 0（2026-11-12）。
        os.environ.setdefault("OMP_WAIT_POLICY", "PASSIVE")
        os.environ.setdefault("KMP_BLOCKTIME", "0")
        self.device = resolve_device(self.requested_device)
        try:
            from rapidocr_onnxruntime import RapidOCR  # type: ignore
            kw: Dict[str, Any] = dict(intra_op_num_threads=self.intra_threads,
                                      inter_op_num_threads=1)
            if self.device == "dml":
                # ⚠ 必须用 det/cls/rec 三个前缀分别开启：rapidocr 的
                # config.yaml 里每个模型各有 use_dml，只传全局 use_dml 无效
                # （实测：全局传参仍是 CPU 速度 985ms，per-model 传参 206ms）
                kw.update(det_use_dml=True, cls_use_dml=True, rec_use_dml=True)
            try:
                self._engine = RapidOCR(**kw)
            except Exception as exc:  # noqa: BLE001 — GPU 初始化失败回落 CPU
                if self.device != "dml":
                    raise
                self.log.warning("DirectML 初始化失败，回落到 CPU: %s", exc)
                self.device = "cpu"
                kw.pop("det_use_dml", None)
                kw.pop("cls_use_dml", None)
                kw.pop("rec_use_dml", None)
                self._engine = RapidOCR(**kw)
            self.log.info("OCR 引擎已加载: rapidocr（%s，线程 %d）",
                          "GPU/DirectML" if self.device == "dml" else "CPU",
                          self.intra_threads)
            return True
        except Exception as exc:  # noqa: BLE001
            self._failed = True
            self.log.error("OCR 引擎加载失败，OCR 功能降级为不可用: %s", exc)
            return False

    @property
    def available(self) -> bool:
        return self._ensure()

    # ----------------------------------------------------------------- 识别
    def read(self,
             image: np.ndarray,
             region: Optional[Sequence[int]] = None,
             min_score: Optional[float] = None) -> List[OCRItem]:
        """识别图像（或其中某个区域）中的全部文本。

        Parameters
        ----------
        region : [x1, y1, x2, y2]，None 表示整屏
        """
        if image is None or image.size == 0:
            return []
        x1 = y1 = 0
        canvas = image
        if region is not None:
            x1, y1, x2, y2 = [int(v) for v in region]
            canvas = image[y1:y2, x1:x2]
            if canvas.size == 0:
                return []

        if not self._ensure():
            return []

        key = tuple(int(v) for v in region) if region is not None else None
        if (self.cache_frames and self._last_img is image
                and self._last_region == key):
            self._hits += 1
            return list(self._last_items)

        self._runs += 1
        try:
            raw = self._run_engine(canvas)
        except Exception as exc:  # noqa: BLE001
            self.log.warning("OCR 识别异常: %s", exc)
            return []

        thr = self.min_score if min_score is None else min_score
        items: List[OCRItem] = []
        for entry in raw:
            try:
                box, text, score = entry[0], entry[1], float(entry[2])
            except Exception:  # noqa: BLE001
                continue
            if score < thr or not str(text).strip():
                continue
            # 把区域坐标还原为屏幕绝对坐标
            abs_box = [[float(p[0]) + x1, float(p[1]) + y1] for p in box]
            items.append(OCRItem(text=str(text), score=score, box=abs_box))
        if self.cache_frames:
            self._last_img, self._last_region, self._last_items = image, key, items
        return list(items)

    def stats(self) -> Dict[str, int]:
        """命中/推理计数（诊断用：命中率高说明同一帧被重复问过）。"""
        return {"runs": self._runs, "cache_hits": self._hits}

    def _run_engine(self, canvas: np.ndarray) -> List[Any]:
        """兼容 RapidOCR 不同版本的返回签名。"""
        result = self._engine(canvas)  # type: ignore[misc]
        if isinstance(result, tuple):
            result = result[0]
        if result is None:
            return []
        if isinstance(result, dict):           # 新版可能返回 dict
            return list(result.get("boxes") or result.get("result") or [])
        return list(result)

    # ------------------------------------------------------------- 查询工具
    def find(self,
             items: Sequence[OCRItem],
             keywords: Sequence[str],
             mode: str = "any") -> List[OCRItem]:
        """在识别结果中查找包含关键词的条目。

        mode : ``"any"`` 任一命中 | ``"all"`` 全部命中

        ⚠ ``"all"`` 是**跨条目**判定：每条关键词只要在**任意一条** OCR 结果里
        出现即算命中。界面上的多个按钮本来就是分开的文本条目，
        早期实现要求所有关键词挤在**同一段**文本里，导致
        「开始对局 + 再想一想」这类跨按钮的同现判定永远不成立（实测踩坑）。
        """
        if not keywords:
            return []
        needles = [normalize_text(k) if self.normalize else k for k in keywords]
        haystacks = [(normalize_text(it.text) if self.normalize else it.text, it)
                     for it in items]

        if mode == "all":
            hits: List[OCRItem] = []
            for n in needles:
                for hay, it in haystacks:
                    if n in hay:
                        hits.append(it)
                        break
                else:
                    return []          # 有一条关键词没命中 → 整体判否
            return hits
        return [it for hay, it in haystacks if any(n in hay for n in needles)]

    def has(self,
            image: np.ndarray,
            keywords: Sequence[str],
            region: Optional[Sequence[int]] = None,
            mode: str = "any") -> bool:
        """便捷方法：图像中是否出现关键词。"""
        return bool(self.find(self.read(image, region), keywords, mode))

    def text_of(self,
                image: np.ndarray,
                region: Optional[Sequence[int]] = None) -> str:
        """把区域内所有文本拼接成一行，便于整体匹配。"""
        return " ".join(it.text for it in self.read(image, region))

    def extract_number(self,
                       image: np.ndarray,
                       regex: str,
                       region: Optional[Sequence[int]] = None,
                       group: int = 1) -> Optional[int]:
        """按正则从区域文本中抽取数值，如 ``r"里程\\D*(\\d+)"``。"""
        items = self.read(image, region)
        for it in items:
            m = re.search(regex, it.text)
            if m:
                try:
                    return int(m.group(group))
                except (ValueError, IndexError):
                    continue
        # 跨条目兜底：把整行拼起来再匹配
        joined = " ".join(it.text for it in items)
        m = re.search(regex, joined)
        if m:
            try:
                return int(m.group(group))
            except (ValueError, IndexError):
                return None
        return None
