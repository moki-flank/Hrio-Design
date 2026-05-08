# FILE: banana_logger.py
# 简化版日志。如果你嫌原来的颜色/emoji/线程日志太乱，可以用这个替换。
# 如果不嫌乱，banana_logger.py 可以完全不改。

from __future__ import annotations

import sys
import threading
from datetime import datetime


class _Logger:
    def __init__(self):
        self._lock = threading.Lock()

    def _print(self, level: str, msg: str):
        ts = datetime.now().strftime("%H:%M:%S")
        thread = threading.current_thread().name
        line = f"[{ts}][{thread}][{level}] {msg}"
        with self._lock:
            print(line, file=sys.stdout, flush=True)

    def info(self, msg: str):
        self._print("INFO", msg)

    def success(self, msg: str):
        self._print("OK", msg)

    def warning(self, msg: str):
        self._print("WARN", msg)

    def error(self, msg: str):
        self._print("ERR", msg)

    def summary(self, title: str, items: dict):
        with self._lock:
            print(f"\n===== {title} =====", flush=True)
            for k, v in (items or {}).items():
                print(f"{k}: {v}", flush=True)
            print("", flush=True)


logger = _Logger()

__all__ = ["logger"]
