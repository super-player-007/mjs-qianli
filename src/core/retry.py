"""重试与等待原语 —— 容错能力的基础。"""
from __future__ import annotations

import functools
import logging
import time
from typing import Any, Callable, Iterable, Optional, TypeVar

T = TypeVar("T")


class WaitTimeout(RuntimeError):
    """等待条件超时。"""


def retry(times: int = 3,
          delay: float = 0.8,
          backoff: float = 2.0,
          exceptions: Iterable[type] = (Exception,),
          logger: Optional[logging.Logger] = None,
          desc: str = ""):
    """失败自动重试装饰器。

    Parameters
    ----------
    times      : 总尝试次数（含首次）
    delay      : 首次重试前的等待秒数
    backoff    : 每次重试等待时间的放大倍数
    exceptions : 需要捕获并重试的异常类型
    """
    def deco(func: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> T:
            wait = delay
            last_exc: Optional[BaseException] = None
            for attempt in range(1, times + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as exc:  # type: ignore[misc]
                    last_exc = exc
                    tag = desc or func.__name__
                    if attempt >= times:
                        if logger:
                            logger.error("「%s」重试 %d 次仍失败: %s", tag, times, exc)
                        break
                    if logger:
                        logger.warning("「%s」第 %d 次失败(%s)，%.1fs 后重试",
                                       tag, attempt, exc, wait)
                    time.sleep(wait)
                    wait *= backoff
            assert last_exc is not None
            raise last_exc
        return wrapper
    return deco


def wait_until(predicate: Callable[[], T],
               timeout: float = 10.0,
               interval: float = 0.35,
               desc: str = "",
               logger: Optional[logging.Logger] = None) -> T:
    """轮询直到 predicate 返回真值。

    Returns
    -------
    predicate 的最后一次返回值

    Raises
    ------
    WaitTimeout : 超时仍不满足
    """
    deadline = time.time() + timeout
    result: Any = None
    while True:
        result = predicate()
        if result:
            return result
        if time.time() >= deadline:
            raise WaitTimeout(f"等待超时({timeout}s): {desc or '未命名条件'}")
        if logger:
            logger.debug("等待中... %s", desc)
        time.sleep(interval)


def retry_call(func: Callable[[], T],
               times: int = 3,
               delay: float = 0.8,
               backoff: float = 2.0,
               exceptions: Iterable[type] = (Exception,),
               logger: Optional[logging.Logger] = None,
               desc: str = "") -> T:
    """函数式版本的重试（用于包装任意可调用对象）。"""
    return retry(times=times, delay=delay, backoff=backoff,
                 exceptions=exceptions, logger=logger, desc=desc)(func)()
