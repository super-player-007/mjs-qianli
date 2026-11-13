"""离线单元测试：不依赖模拟器，只跑纯逻辑与本地夹具图。

运行方式（项目根目录）::

    .venv/Scripts/python.exe -m unittest discover -s tests -v

夹具
----
``tests/fixtures/map_layer1.png``  第 1 层地图（3 个战斗节点，x≈667）
``tests/fixtures/map_layer2.png``  第 2 层地图（3 个战斗节点 x≈1082 +
                                   已通关节点 + 云中君精灵 2 个干扰圆）
"""
from __future__ import annotations

from pathlib import Path

from src.vision.annotate import read_image

PROJECT_ROOT = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).resolve().parent / "fixtures"
TPL_DIR = PROJECT_ROOT / "assets" / "templates" / "run_map"


def load_fixture(name: str):
    img = read_image(str(FIXTURES / name))
    assert img is not None, f"夹具图读取失败: {name}"
    return img
