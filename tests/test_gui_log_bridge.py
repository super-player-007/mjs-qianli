"""GUI 日志队列桥测试（2026-10-10 事故：GUI 首次启动运行日志空白）。

根因：setup_logger 的 handlers.clear() 把 GUI 队列桥一起清掉——
命令行/文件有日志、GUI 界面没有；第二次起 configured 短路反而正常。
修复：持久标记 _persistent=True 的 handler 重配置时保留。
"""
from __future__ import annotations

import logging
import queue
import unittest

from src.core.logger import setup_logger


class PersistentQueueHandler(logging.Handler):
    """模拟 GUI 的 _QueueHandler（带持久标记）。"""

    def __init__(self, q):
        super().__init__(level=logging.INFO)
        self.q = q
        self._persistent = True

    def emit(self, record):
        self.q.put(record.getMessage())


class TestSetupLoggerKeepsBridge(unittest.TestCase):
    def setUp(self):
        # 还原 mjs logger 状态，防测试间污染
        self.logger = logging.getLogger("mjs")
        self._handlers = list(self.logger.handlers)
        from src.core import logger as logger_mod
        logger_mod._configured.pop("mjs", None)
        self.logger.handlers.clear()

    def tearDown(self):
        self.logger.handlers.clear()
        self.logger.handlers.extend(self._handlers)
        from src.core import logger as logger_mod
        logger_mod._configured.pop("mjs", None)

    def test_first_setup_keeps_bridge(self):
        """首次启动时序：先挂队列桥 → setup_logger → 桥仍在且收到日志。"""
        q = queue.Queue()
        self.logger.addHandler(PersistentQueueHandler(q))
        setup_logger("mjs", log_dir=None)           # 模拟 _build_runtime
        kinds = [type(h).__name__ for h in self.logger.handlers]
        self.assertIn("PersistentQueueHandler", kinds)
        self.logger.info("桥上消息")
        self.assertEqual(q.get_nowait(), "桥上消息")

    def test_second_setup_no_duplicate_console(self):
        """第二次启动：不重复挂控制台；持久桥继续保留。"""
        q = queue.Queue()
        self.logger.addHandler(PersistentQueueHandler(q))
        setup_logger("mjs", log_dir=None)
        setup_logger("mjs", log_dir=None)           # 第二次启动
        consoles = [h for h in self.logger.handlers
                    if isinstance(h, logging.StreamHandler)
                    and not isinstance(h, logging.FileHandler)]
        self.assertEqual(len(consoles), 1)          # 控制台不双份
        bridges = [h for h in self.logger.handlers
                   if isinstance(h, PersistentQueueHandler)]
        self.assertEqual(len(bridges), 1)           # 桥不重复（add/remove 平衡）
        self.logger.info("第二次")
        self.assertEqual(q.get_nowait(), "第二次")

    def test_non_persistent_handlers_cleared(self):
        """无标记的旧 handler（如遗留 FileHandler）重配置时被清掉。"""
        stale = logging.FileHandler("runtime/_stale.log", encoding="utf-8")
        self.logger.addHandler(stale)
        setup_logger("mjs", log_dir=None)
        self.assertNotIn(stale, self.logger.handlers)
        stale.close()


if __name__ == "__main__":
    unittest.main()
